"""Tests for the raw-observation storage and read-time derivation in db.py."""
import unittest
import os
import sys
import sqlite3
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db import (init_schema, record_observation, record_status, history, latest_usage,
                metrics, prune, _USAGE_FIELDS)
from parsers.base import ParserResult, ModelUsage


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

    def test_counter_reset_clamps_to_zero(self):
        record_observation(self.conn, 'codex', 1000, _result(5000))
        record_observation(self.conn, 'codex', 1600, _result(6000))
        record_observation(self.conn, 'codex', 2200, _result(100))   # reset
        record_observation(self.conn, 'codex', 2800, _result(400))   # resumes
        rows = history(self.conn, 'codex')
        self.assertEqual([r['input_tokens'] for r in rows], [0, 1000, 1000, 1300])

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
