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

    def test_empty_db_is_ok(self):
        report = check_integrity(self.conn, poll_interval=600)
        self.assertTrue(report['ok'])


if __name__ == '__main__':
    unittest.main()
