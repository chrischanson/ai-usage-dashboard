import unittest
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sqlite3
from integrity import check_integrity
from db import init_schema, record_status
from parsers.base import ParserResult


def _insert_raw(conn, source, cycle_ts, input_tokens, output_tokens=0):
    from db import record_observation
    record_observation(conn, source, cycle_ts, ParserResult(
        sessions=1, messages=1,
        input_tokens=input_tokens, output_tokens=output_tokens,
    ))


class TestCheckIntegrity(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_clean_recent_data_is_ok(self):
        now_cycle = (int(time.time()) // 600) * 600
        _insert_raw(self.conn, 'codex', now_cycle - 600, 1000)
        _insert_raw(self.conn, 'codex', now_cycle, 1500)
        report = check_integrity(self.conn, poll_interval=600)
        self.assertTrue(report['ok'])
        self.assertEqual(report['warnings'], [])
        self.assertEqual(report['checks']['counter_resets'], [])
        self.assertEqual(report['checks']['rows_missing_status'], 0)

    def test_counter_reset_is_warned_not_fatal(self):
        now_cycle = (int(time.time()) // 600) * 600
        _insert_raw(self.conn, 'codex', now_cycle - 600, 5000)
        _insert_raw(self.conn, 'codex', now_cycle, 100)  # tool state reset
        report = check_integrity(self.conn, poll_interval=600)
        self.assertTrue(report['ok'])
        resets = report['checks']['counter_resets']
        self.assertTrue(any(r['source'] == 'codex' and r['field'] == 'input_tokens' for r in resets))
        self.assertTrue(report['warnings'])

    def test_missing_status_row_fails(self):
        # Bypass the write layer to simulate an ungoverned external write.
        now_cycle = (int(time.time()) // 600) * 600
        self.conn.execute(
            "INSERT INTO usage_history (source, cycle_ts, timestamp, sessions, messages, input_tokens, output_tokens) "
            "VALUES ('codex', ?, '2026-01-01 00:00:00', 1, 1, 10, 10)", (now_cycle,))
        self.conn.commit()
        report = check_integrity(self.conn, poll_interval=600)
        self.assertFalse(report['ok'])
        self.assertEqual(report['checks']['rows_missing_status'], 1)

    def test_stale_data_fails(self):
        _insert_raw(self.conn, 'codex', 1000, 1000)  # ancient cycle
        report = check_integrity(self.conn, poll_interval=600)
        self.assertFalse(report['ok'])
        self.assertTrue(report['checks']['stale'])

    def test_one_stale_source_fails_even_if_others_are_fresh(self):
        now_cycle = (int(time.time()) // 600) * 600
        # codex went dark hours ago; opencode is still reporting every cycle.
        _insert_raw(self.conn, 'codex', now_cycle - 6000, 1000)
        _insert_raw(self.conn, 'opencode', now_cycle - 600, 2000)
        _insert_raw(self.conn, 'opencode', now_cycle, 2500)
        report = check_integrity(self.conn, poll_interval=600)
        self.assertFalse(report['checks']['stale'])  # global newest is recent
        self.assertFalse(report['ok'])
        self.assertIn('codex', report['checks']['stale_sources'])
        self.assertNotIn('opencode', report['checks']['stale_sources'])

    def test_empty_db_is_ok(self):
        report = check_integrity(self.conn, poll_interval=600)
        self.assertTrue(report['ok'])

    def _insert_usage_row(self, source, cycle_ts, **fields):
        # Bypass the write layer so a column can be left NULL (a raw source
        # not reporting a field), which record_observation never produces.
        cols = ['source', 'cycle_ts', 'timestamp'] + list(fields.keys())
        placeholders = ', '.join('?' for _ in cols)
        values = [source, cycle_ts, '2026-01-01 00:00:00'] + list(fields.values())
        self.conn.execute(
            f"INSERT INTO usage_history ({', '.join(cols)}) VALUES ({placeholders})", values)
        self.conn.commit()

    def test_window_function_monotonicity_detects_reset_with_none_column(self):
        # cache_read goes from a real value to NULL: COALESCE(NULL,0)=0 is a
        # decrease from 500, same as the old `row[f] or 0` walk would find.
        now_cycle = (int(time.time()) // 600) * 600
        self._insert_usage_row('codex', now_cycle - 600, sessions=1, messages=1,
                               input_tokens=100, output_tokens=50, cache_read=500, cache_write=10)
        self._insert_usage_row('codex', now_cycle, sessions=2, messages=2,
                               input_tokens=150, output_tokens=60, cache_read=None, cache_write=20)
        report = check_integrity(self.conn, poll_interval=600)
        resets = report['checks']['counter_resets']
        cache_reset = [r for r in resets if r['field'] == 'cache_read']
        self.assertEqual(len(cache_reset), 1)
        self.assertEqual(cache_reset[0]['source'], 'codex')
        self.assertEqual(cache_reset[0]['previous'], 500)
        self.assertIsNone(cache_reset[0]['value'])
        # Other fields all increased, so they must not be reported.
        self.assertFalse(any(r['field'] != 'cache_read' for r in resets))

    def test_since_cycle_bounds_monotonicity_scan(self):
        now_cycle = (int(time.time()) // 600) * 600
        old_a, old_b = now_cycle - 10000, now_cycle - 9400
        recent_a, recent_b = now_cycle - 600, now_cycle
        _insert_raw(self.conn, 'codex', old_a, 5000)       # baseline
        _insert_raw(self.conn, 'codex', old_b, 100)        # reset vs old_a
        _insert_raw(self.conn, 'codex', recent_a, 200)
        _insert_raw(self.conn, 'codex', recent_b, 300)

        full = check_integrity(self.conn, poll_interval=600)
        full_cycles = {r['cycle_ts'] for r in full['checks']['counter_resets']}
        self.assertIn(old_b, full_cycles)

        bounded = check_integrity(self.conn, poll_interval=600, since_cycle=now_cycle - 5000)
        bounded_cycles = {r['cycle_ts'] for r in bounded['checks']['counter_resets']}
        self.assertNotIn(old_b, bounded_cycles)
        self.assertEqual(bounded['checks']['counter_resets'], [])

    def test_warning_truncation_caps_repeated_resets(self):
        # 8 strictly-decreasing rows -> 7 resets on the same field/source.
        now_cycle = (int(time.time()) // 600) * 600
        for i in range(8):
            _insert_raw(self.conn, 'codex', now_cycle - (7 - i) * 600, 1000 - i * 100)
        report = check_integrity(self.conn, poll_interval=600)
        resets = report['checks']['counter_resets']
        self.assertEqual(len(resets), 7)
        reset_lines = [w for w in report['warnings'] if 'decreased at cycle' in w]
        self.assertEqual(len(reset_lines), 5)  # capped, full list stays in 'checks'
        summary = [w for w in report['warnings'] if w.startswith('...and')]
        self.assertEqual(summary, ['...and 2 more counter reset(s) (see checks for full list)'])


if __name__ == '__main__':
    unittest.main()
