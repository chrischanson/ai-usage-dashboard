"""Tests for the raw-observation storage and read-time derivation in db.py."""
import unittest
import os
import sys
import sqlite3
import json
import tempfile
import shutil
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db import (init_schema, connect, record_observation, record_quota, record_status,
                history, latest_usage, latest_quota, metrics, prune, rebase_reset_history,
                _USAGE_FIELDS, _MODEL_REBASE_FIELDS)
from parsers.base import ParserResult, ModelUsage
from integrity import check_integrity


def _result(input_tokens, output_tokens=0, sessions=1, messages=1, models=None):
    return ParserResult(sessions=sessions, messages=messages,
                        input_tokens=input_tokens, output_tokens=output_tokens,
                        models=models or [])


class DerivationTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_raw_values_stored_verbatim(self):
        record_observation(self.conn, 'codex', 1000, _result(30_000_000))
        row = self.conn.execute("SELECT input_tokens FROM usage_history").fetchone()
        self.assertEqual(row['input_tokens'], 30_000_000)

    def test_first_observation_contributes_zero(self):
        # A tool with months of lifetime history must not appear as a spike.
        record_observation(self.conn, 'codex', 1000, _result(30_000_000))
        rows = history(self.conn, 'codex')
        self.assertEqual(rows[0]['input_tokens'], 0)
        self.assertEqual(rows[0]['delta_input_tokens'], 0)

    def test_growth_accumulates(self):
        record_observation(self.conn, 'codex', 1000, _result(30_000_000))
        record_observation(self.conn, 'codex', 1600, _result(30_000_500))
        record_observation(self.conn, 'codex', 2200, _result(30_001_500))
        rows = history(self.conn, 'codex')
        self.assertEqual([r['input_tokens'] for r in rows], [0, 500, 1500])
        self.assertEqual([r['delta_input_tokens'] for r in rows], [0, 500, 1000])

    def test_hard_reset_rebases_at_write_time(self):
        # A drop below half the previous reading is tool-state loss, not a
        # real decrease: the write path carries the old baseline forward, so
        # the stored series (and its derived deltas) stay cumulative through
        # the reset instead of clamping to 0.
        record_observation(self.conn, 'codex', 1000, _result(5000))
        record_observation(self.conn, 'codex', 1600, _result(6000))
        record_observation(self.conn, 'codex', 2200, _result(100))   # hard drop -> rebased
        record_observation(self.conn, 'codex', 2800, _result(400))   # resumes from new baseline
        stored = [r['input_tokens'] for r in self.conn.execute(
            "SELECT input_tokens FROM usage_history WHERE source='codex' ORDER BY cycle_ts").fetchall()]
        self.assertEqual(stored, [5000, 6000, 6100, 6400])
        rows = history(self.conn, 'codex')
        self.assertEqual([r['input_tokens'] for r in rows], [0, 1000, 1100, 1400])
        self.assertEqual([r['delta_input_tokens'] for r in rows], [0, 1000, 100, 300])

    def test_external_write_decrease_still_clamps_at_read_time(self):
        # The write-side rebase only guards record_observation's own callers
        # (the poller). A decrease that reaches storage some other way (a
        # direct SQL write, a bug, a restored backup) must still have its
        # delta clamped to 0 at read time -- this is the same fixture shape
        # as the old clamp test, now written directly to bypass the rebase.
        def _raw_insert(cycle_ts, input_tokens):
            ts = datetime.fromtimestamp(cycle_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            self.conn.execute(
                "INSERT INTO usage_history (source, cycle_ts, timestamp, sessions, messages, "
                "input_tokens, output_tokens) VALUES ('codex', ?, ?, 1, 1, ?, 0)",
                (cycle_ts, ts, input_tokens))

        for cts, tok in [(1000, 5000), (1600, 6000), (2200, 100), (2800, 400)]:
            _raw_insert(cts, tok)
        self.conn.commit()
        rows = history(self.conn, 'codex')
        self.assertEqual([r['input_tokens'] for r in rows], [0, 1000, 1000, 1300])
        self.assertEqual([r['delta_input_tokens'] for r in rows], [0, 1000, 0, 300])

    def test_hard_reset_offset_persists_across_connections(self):
        # The offset that absorbs a hard reset is meta-table state, not
        # in-memory bookkeeping: it must survive the writing connection
        # closing and a later poll landing on a fresh connection.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'usage.db')
            conn1 = sqlite3.connect(path)
            conn1.row_factory = sqlite3.Row
            init_schema(conn1)
            record_observation(conn1, 'codex', 1000, _result(30_000_000))
            record_observation(conn1, 'codex', 1600, _result(500_000))  # hard drop
            offsets_row = conn1.execute(
                "SELECT value FROM meta WHERE key='reset_offsets:codex'").fetchone()
            self.assertIsNotNone(offsets_row)
            self.assertEqual(json.loads(offsets_row['value'])['source']['input_tokens'], 30_000_000)
            conn1.close()

            conn2 = sqlite3.connect(path)
            conn2.row_factory = sqlite3.Row
            record_observation(conn2, 'codex', 2200, _result(500_100))
            stored = [r['input_tokens'] for r in conn2.execute(
                "SELECT input_tokens FROM usage_history WHERE source='codex' ORDER BY cycle_ts"
            ).fetchall()]
            conn2.close()
        self.assertEqual(stored, [30_000_000, 30_500_000, 30_500_100])

    def test_ghost_model_rows_keep_per_cycle_sums_matching_after_reset(self):
        # When the source resets and a model the tool used to report
        # vanishes with it, a frozen "ghost" row must keep being written for
        # that model every cycle so the per-cycle model-token sum keeps
        # matching the rebased source row (integrity check #3).
        old_model = [ModelUsage('gpt-5.5', messages=16, input_tokens=28_000_000)]
        record_observation(self.conn, 'codex', 1000, _result(28_000_000, sessions=16, messages=16, models=old_model))
        # Hard reset: sessions/messages/tokens all collapse, and gpt-5.5 is
        # gone from the parser's own view starting next cycle. gpt-4o's own
        # reading grows in step with the overview so the sums line up
        # exactly (matching the source data's own internal consistency).
        record_observation(self.conn, 'codex', 1600, _result(
            38_000, sessions=1, messages=1,
            models=[ModelUsage('gpt-4o', messages=1, input_tokens=38_000)]))
        record_observation(self.conn, 'codex', 2200, _result(
            40_000, sessions=1, messages=2,
            models=[ModelUsage('gpt-4o', messages=2, input_tokens=40_000)]))

        for cycle_ts in (1600, 2200):
            source_row = self.conn.execute(
                "SELECT * FROM usage_history WHERE source='codex' AND cycle_ts=?", (cycle_ts,)).fetchone()
            model_total = self.conn.execute(
                "SELECT SUM(input_tokens) FROM model_usage WHERE source='codex' AND cycle_ts=?",
                (cycle_ts,)).fetchone()[0]
            self.assertEqual(model_total, source_row['input_tokens'])
            ghost = self.conn.execute(
                "SELECT * FROM model_usage WHERE source='codex' AND cycle_ts=? AND model_name='gpt-5.5'",
                (cycle_ts,)).fetchone()
            self.assertIsNotNone(ghost)
            self.assertEqual(ghost['input_tokens'], 28_000_000)

        report = check_integrity(self.conn, poll_interval=600)
        codex_mismatches = [m for m in report['checks']['model_sum_mismatches'] if m['source'] == 'codex']
        self.assertEqual(codex_mismatches, [])

    def test_model_derivation(self):
        m1 = [ModelUsage('gpt-5', messages=10, input_tokens=1000)]
        m2 = [ModelUsage('gpt-5', messages=12, input_tokens=1600),
              ModelUsage('o3', messages=1, input_tokens=99)]
        record_observation(self.conn, 'codex', 1000, _result(1000, models=m1))
        record_observation(self.conn, 'codex', 1600, _result(1699, models=m2))
        rows = history(self.conn, 'codex')
        models_last = {m['model_name']: m for m in rows[-1]['models']}
        self.assertEqual(models_last['gpt-5']['input_tokens'], 600)
        self.assertEqual(models_last['gpt-5']['delta_input_tokens'], 600)
        # o3 first seen at second cycle -> contributes zero
        self.assertEqual(models_last['o3']['input_tokens'], 0)

    def test_latest_usage_matches_history_tail(self):
        record_observation(self.conn, 'codex', 1000, _result(1000))
        record_observation(self.conn, 'codex', 1600, _result(4000))
        latest = latest_usage(self.conn, 'codex')['codex']
        tail = history(self.conn, 'codex')[-1]
        for f in _USAGE_FIELDS:
            self.assertEqual(latest[f], tail[f])

    def test_combined_history_forward_fills(self):
        record_observation(self.conn, 'codex', 1000, _result(1000))
        record_observation(self.conn, 'codex', 1600, _result(2000))
        record_observation(self.conn, 'agy', 1000, _result(500))
        # agy misses cycle 1600: its total must carry forward, not dip.
        combined = history(self.conn, None)
        self.assertEqual([r['cycle_ts'] for r in combined], [1000, 1600])
        self.assertEqual(combined[1]['input_tokens'], 1000)  # codex 1000 + agy 0 carried
        self.assertEqual(combined[1]['delta_input_tokens'], 1000)

    def test_status_row_paired_with_every_write(self):
        record_observation(self.conn, 'codex', 1000, _result(1))
        row = self.conn.execute(
            "SELECT ok FROM collection_status WHERE source='codex' AND kind='usage' AND cycle_ts=1000"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['ok'], 1)

    def test_model_cost_derivation_and_clamp(self):
        m1 = [ModelUsage('claude-3-5-sonnet', messages=10, input_tokens=1000, cost=10.50)]
        m2 = [ModelUsage('claude-3-5-sonnet', messages=20, input_tokens=2000, cost=15.75)]
        m3 = [ModelUsage('claude-3-5-sonnet', messages=5, input_tokens=500, cost=2.00)] # counter drop / reset
        m4 = [ModelUsage('claude-3-5-sonnet', messages=10, input_tokens=1000, cost=4.50)]

        record_observation(self.conn, 'claude', 1000, _result(1000, models=m1))
        record_observation(self.conn, 'claude', 1600, _result(2000, models=m2))
        record_observation(self.conn, 'claude', 2200, _result(2500, models=m3))
        record_observation(self.conn, 'claude', 2800, _result(3000, models=m4))

        rows = history(self.conn, 'claude')
        models_by_cycle = {r['cycle_ts']: r['models'][0] for r in rows if r.get('models')}

        # First observation -> delta 0
        self.assertAlmostEqual(models_by_cycle[1000]['cost'], 0.0)
        self.assertAlmostEqual(models_by_cycle[1000]['delta_cost'], 0.0)

        # Rising cost -> delta 15.75 - 10.50 = 5.25, total 5.25
        self.assertAlmostEqual(models_by_cycle[1600]['cost'], 5.25)
        self.assertAlmostEqual(models_by_cycle[1600]['delta_cost'], 5.25)

        # Drop (2.00 < 15.75) -> clamped to 0.0, total stays 5.25
        self.assertAlmostEqual(models_by_cycle[2200]['cost'], 5.25)
        self.assertAlmostEqual(models_by_cycle[2200]['delta_cost'], 0.0)

        # Resume (4.50 > 2.00) -> delta 4.50 - 2.00 = 2.50, total 7.75
        self.assertAlmostEqual(models_by_cycle[2800]['cost'], 7.75)
        self.assertAlmostEqual(models_by_cycle[2800]['delta_cost'], 2.50)

    def test_schema_v5_indexes_exist(self):
        row = self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        self.assertEqual(row['value'], '5')
        cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {r['name'] for r in cursor.fetchall()}
        expected_indexes = {
            'idx_usage_history_cycle_ts',
            'idx_model_usage_cycle_ts',
            'idx_quota_snapshots_cycle_ts',
            'idx_usage_history_source_ts',
            'idx_model_usage_source_ts',
            'idx_quota_snapshots_source_ts',
            'idx_quota_ts',
            'idx_model_usage_source_model_ts',
            'idx_quota_plans_source_ts',
        }
        self.assertTrue(expected_indexes.issubset(indexes))

    def test_schema_v5_has_quota_plans_table(self):
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='quota_plans'"
        ).fetchone()
        self.assertIsNotNone(row, 'quota_plans table missing')


class RebaseResetHistoryTest(unittest.TestCase):
    """rebase_reset_history replays *historical* rows that were written
    before offset tracking existed -- i.e. genuinely raw at every cycle,
    never previously adjusted. These fixtures go in directly via SQL (not
    record_observation) to reproduce that shape, including the one wrinkle
    real codex data had: a poller restart landing mid-reset left the reset
    cycle's model_usage holding the union of the old and new model rows
    (both survive an INSERT OR REPLACE keyed on (source, cycle_ts,
    model_name) since the model_name differs)."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)
        import time
        now_cycle = (int(time.time()) // 600) * 600
        self.c1, self.c2, self.c3, self.c4, self.c5 = (
            now_cycle - 2400, now_cycle - 1800, now_cycle - 1200, now_cycle - 600, now_cycle)

    def tearDown(self):
        self.conn.close()

    def _usage(self, cycle_ts, sessions, messages, input_tokens):
        ts = datetime.fromtimestamp(cycle_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        self.conn.execute(
            "INSERT INTO usage_history (source, cycle_ts, timestamp, sessions, messages, "
            "input_tokens, output_tokens) VALUES ('codex', ?, ?, ?, ?, ?, 0)",
            (cycle_ts, ts, sessions, messages, input_tokens))
        record_status(self.conn, 'codex', 'usage', cycle_ts, True, None)

    def _model(self, cycle_ts, model_name, messages, input_tokens):
        ts = datetime.fromtimestamp(cycle_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        self.conn.execute(
            "INSERT INTO model_usage (source, cycle_ts, timestamp, model_name, messages, "
            "input_tokens, output_tokens, cache_read, cache_write, cost) "
            "VALUES ('codex', ?, ?, ?, ?, ?, 0, 0, 0, 0)",
            (cycle_ts, ts, model_name, messages, input_tokens))

    def test_replay_reproduces_real_reset_shape(self):
        # c1, c2: steady growth, single model.
        self._usage(self.c1, 10, 10, 1_000_000)
        self._model(self.c1, 'modelA', 10, 1_000_000)
        self._usage(self.c2, 20, 20, 2_000_000)
        self._model(self.c2, 'modelA', 20, 2_000_000)
        # c3: the reset cycle. Source counters collapse; model_usage holds
        # the union (stale modelA row still present + brand-new modelB).
        self._usage(self.c3, 2, 2, 50_000)
        self._model(self.c3, 'modelA', 20, 2_000_000)
        self._model(self.c3, 'modelB', 2, 50_000)
        # c4, c5: modelA has genuinely dropped out of the parser's view.
        self._usage(self.c4, 3, 3, 60_000)
        self._model(self.c4, 'modelB', 3, 60_000)
        self._usage(self.c5, 4, 4, 70_000)
        self._model(self.c5, 'modelB', 4, 70_000)
        self.conn.commit()

        summary = rebase_reset_history(self.conn, 'codex')
        self.assertEqual(summary['source_resets'], 1)
        self.assertEqual(summary['rows_rebased'], 3)
        self.assertEqual(summary['model_rows_rebased'], 0)
        self.assertEqual(summary['ghost_rows_added'], 2)
        self.assertEqual(summary['ghost_models'], ['modelA'])

        stored = {r['cycle_ts']: r for r in self.conn.execute(
            "SELECT * FROM usage_history WHERE source='codex' ORDER BY cycle_ts")}
        self.assertEqual((stored[self.c1]['sessions'], stored[self.c1]['messages'],
                          stored[self.c1]['input_tokens']), (10, 10, 1_000_000))
        self.assertEqual((stored[self.c2]['sessions'], stored[self.c2]['messages'],
                          stored[self.c2]['input_tokens']), (20, 20, 2_000_000))
        self.assertEqual((stored[self.c3]['sessions'], stored[self.c3]['messages'],
                          stored[self.c3]['input_tokens']), (22, 22, 2_050_000))
        self.assertEqual((stored[self.c4]['sessions'], stored[self.c4]['messages'],
                          stored[self.c4]['input_tokens']), (23, 23, 2_060_000))
        self.assertEqual((stored[self.c5]['sessions'], stored[self.c5]['messages'],
                          stored[self.c5]['input_tokens']), (24, 24, 2_070_000))

        # Ghost rows for modelA start the cycle *after* the reset cycle (the
        # reset cycle itself already sums correctly via the union row).
        ghost_c4 = self.conn.execute(
            "SELECT * FROM model_usage WHERE source='codex' AND cycle_ts=? AND model_name='modelA'",
            (self.c4,)).fetchone()
        ghost_c5 = self.conn.execute(
            "SELECT * FROM model_usage WHERE source='codex' AND cycle_ts=? AND model_name='modelA'",
            (self.c5,)).fetchone()
        for ghost in (ghost_c4, ghost_c5):
            self.assertIsNotNone(ghost)
            self.assertEqual(ghost['messages'], 20)
            self.assertEqual(ghost['input_tokens'], 2_000_000)

        offsets_row = self.conn.execute(
            "SELECT value FROM meta WHERE key='reset_offsets:codex'").fetchone()
        offsets = json.loads(offsets_row['value'])
        self.assertEqual(offsets['source'], {'sessions': 20, 'messages': 20, 'input_tokens': 2_000_000})
        self.assertEqual(offsets['models']['modelA']['messages'], 20)
        self.assertEqual(offsets['models']['modelA']['input_tokens'], 2_000_000)

        report = check_integrity(self.conn, poll_interval=600)
        codex_resets = [r for r in report['checks']['counter_resets'] if r['source'] == 'codex']
        codex_mismatches = [m for m in report['checks']['model_sum_mismatches'] if m['source'] == 'codex']
        self.assertEqual(codex_resets, [])
        self.assertEqual(codex_mismatches, [])


class PruneTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_prune_keeps_anchor_row(self):
        # Three ancient cycles plus one recent: pruning keeps the newest
        # ancient row so the first retained delta still has a reference.
        import time
        now_cycle = (int(time.time()) // 600) * 600
        for i, cts in enumerate((1000, 1600, 2200, now_cycle)):
            record_observation(self.conn, 'codex', cts, _result(1000 * (i + 1)))
        prune(self.conn, retention_days=1)
        cycles = [r['cycle_ts'] for r in self.conn.execute(
            "SELECT cycle_ts FROM usage_history ORDER BY cycle_ts").fetchall()]
        self.assertEqual(cycles, [2200, now_cycle])
        # Derived delta of the retained recent row is measured from the anchor.
        rows = history(self.conn, 'codex')
        self.assertEqual(rows[-1]['delta_input_tokens'], 1000)


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_last_success_at_survives_a_later_failure(self):
        # Newest attempt failed, but an earlier attempt succeeded: the report
        # must still surface when the source last actually succeeded, not
        # None just because the most recent poll errored out.
        record_status(self.conn, 'codex', 'usage', 1000, ok=True, error=None, duration_ms=5.0)
        record_status(self.conn, 'codex', 'usage', 1600, ok=False, error='boom', duration_ms=1.0)
        result = metrics(self.conn)
        info = result['per_source']['codex']['usage']
        self.assertEqual(info['last_success_at'], '1970-01-01 00:16:40')
        self.assertEqual(info['last_error'], 'boom')
        self.assertEqual(info['last_duration_ms'], 1.0)

    def test_consecutive_same_kind_rows_dont_hide_other_kind(self):
        # Two consecutive 'usage' rows must not push the only 'quota' row out
        # of an "ORDER BY id DESC LIMIT 2" style window.
        record_status(self.conn, 'agy', 'quota', 900, ok=True, error=None, duration_ms=2.0)
        record_status(self.conn, 'agy', 'usage', 1000, ok=True, error=None, duration_ms=3.0)
        record_status(self.conn, 'agy', 'usage', 1600, ok=True, error=None, duration_ms=4.0)
        result = metrics(self.conn)
        src_info = result['per_source']['agy']
        self.assertIn('quota', src_info)
        self.assertIn('usage', src_info)
        self.assertEqual(src_info['quota']['last_success_at'], '1970-01-01 00:15:00')
        self.assertEqual(src_info['usage']['last_duration_ms'], 4.0)

    def test_no_success_yet_reports_none(self):
        record_status(self.conn, 'codex', 'usage', 1000, ok=False, error='nope', duration_ms=0.5)
        info = metrics(self.conn)['per_source']['codex']['usage']
        self.assertIsNone(info['last_success_at'])
        self.assertEqual(info['last_error'], 'nope')


if __name__ == '__main__':
    unittest.main()


class QuotaPlanPersistenceTest(unittest.TestCase):
    """The plan a source reports must survive a restart.

    Before schema v5 the normalizers produced `_plan` but nothing stored it:
    `_do_insert_quota` skipped it because it is a scalar, not a limit group.
    `/api/quota/latest` reads from the DB, so every plan badge silently fell
    back to a hardcoded default ("Claude Pro", "Gemini Code Assist", "free")
    unless a forced live refresh had just run.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'plans.db')
        self.conn = connect(self.path)
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _quota(self, plan):
        return {
            '_plan': plan,
            'gemini_models': {
                'weekly_limit': {'used': 10.0, 'total': 100.0,
                                 'remaining_pct': 90.0, 'refreshes_in_seconds': 60},
            },
        }

    def test_plan_round_trips(self):
        record_quota(self.conn, 'agy', 1000, self._quota('Gemini Advanced Plan'))
        self.assertEqual(latest_quota(self.conn)['agy']['_plan'], 'Gemini Advanced Plan')

    def test_plan_survives_a_new_connection(self):
        record_quota(self.conn, 'agy', 1000, self._quota('Gemini Advanced Plan'))
        self.conn.close()
        self.conn = connect(self.path)
        self.assertEqual(latest_quota(self.conn)['agy']['_plan'], 'Gemini Advanced Plan')

    def test_latest_cycle_wins(self):
        record_quota(self.conn, 'agy', 1000, self._quota('Old Plan'))
        record_quota(self.conn, 'agy', 1600, self._quota('New Plan'))
        self.assertEqual(latest_quota(self.conn)['agy']['_plan'], 'New Plan')

    def test_plan_carries_forward_when_a_cycle_omits_it(self):
        record_quota(self.conn, 'agy', 1000, self._quota('Gemini Advanced Plan'))
        later = self._quota('ignored')
        del later['_plan']
        record_quota(self.conn, 'agy', 1600, later)
        # limits came from cycle 1600, plan from the newest cycle that had one
        self.assertEqual(latest_quota(self.conn)['agy']['_plan'], 'Gemini Advanced Plan')

    def test_absent_plan_is_omitted_not_invented(self):
        q = self._quota('x')
        del q['_plan']
        record_quota(self.conn, 'agy', 1000, q)
        self.assertNotIn('_plan', latest_quota(self.conn)['agy'])

    def test_plan_is_per_source(self):
        record_quota(self.conn, 'agy', 1000, self._quota('Gemini Advanced Plan'))
        record_quota(self.conn, 'claude', 1000, self._quota('Claude Pro'))
        result = latest_quota(self.conn)
        self.assertEqual(result['agy']['_plan'], 'Gemini Advanced Plan')
        self.assertEqual(result['claude']['_plan'], 'Claude Pro')
