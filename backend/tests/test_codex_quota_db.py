"""Schema and persistence tests for Codex quota snapshots (db.py).

Covers the v6 columns (`reset_at`, `window_minutes`, `limit_label`) that let
quota_snapshots describe which window a row belongs to and count down from an
absolute reset time, plus the general record_quota/latest_quota contract as
exercised by the Codex normalizer's output shape.
"""
import os
import sys
import sqlite3
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db import init_schema, connect, record_quota, latest_quota


def _codex_quota(plan='Codex (Free)', **rate_limit_overrides):
    rate_limit = {
        'used': 25.0, 'total': 100.0, 'remaining_pct': 75.0,
        'refreshes_in_seconds': 500, 'reset_at': 1789514532,
        'window_minutes': 43200, 'limit_label': 'Monthly',
    }
    rate_limit.update(rate_limit_overrides)
    return {'_plan': plan, 'openai': {'rate_limit': rate_limit}}


class FreshSchemaTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_schema_version_is_6(self):
        row = self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        self.assertEqual(row['value'], '6')

    def test_quota_snapshots_has_v6_columns(self):
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(quota_snapshots)").fetchall()}
        self.assertIn('reset_at', cols)
        self.assertIn('window_minutes', cols)
        self.assertIn('limit_label', cols)


class V5ToV6MigrationTest(unittest.TestCase):
    """Simulates a database created before the v6 columns existed."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        cur = self.conn.cursor()
        cur.execute('''
            CREATE TABLE meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        cur.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '5')")
        cur.execute('''
            CREATE TABLE quota_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL DEFAULT 'agy',
                cycle_ts INTEGER DEFAULT 0,
                timestamp TEXT,
                model_group TEXT NOT NULL,
                limit_type TEXT NOT NULL,
                used REAL,
                total REAL,
                remaining_pct REAL,
                refreshes_in_seconds INTEGER,
                UNIQUE(source, cycle_ts, model_group, limit_type)
            )
        ''')
        cur.execute('''
            INSERT INTO quota_snapshots
                (source, cycle_ts, timestamp, model_group, limit_type,
                 used, total, remaining_pct, refreshes_in_seconds)
            VALUES ('codex', 1000, '2026-01-01 00:00:00', 'openai', 'rate_limit',
                    10.0, 100.0, 90.0, 500)
        ''')
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _old_row(self):
        return self.conn.execute(
            "SELECT * FROM quota_snapshots WHERE source='codex' AND cycle_ts=1000"
        ).fetchone()

    def test_migration_adds_columns_and_stamps_version(self):
        init_schema(self.conn)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(quota_snapshots)").fetchall()}
        self.assertIn('reset_at', cols)
        self.assertIn('window_minutes', cols)
        self.assertIn('limit_label', cols)
        version = self.conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()['value']
        self.assertEqual(version, '6')

    def test_existing_row_preserved_with_null_new_columns(self):
        init_schema(self.conn)
        row = self._old_row()
        self.assertIsNotNone(row)
        self.assertEqual(row['used'], 10.0)
        self.assertEqual(row['remaining_pct'], 90.0)
        self.assertIsNone(row['reset_at'])
        self.assertIsNone(row['window_minutes'])
        self.assertIsNone(row['limit_label'])

    def test_migration_is_idempotent(self):
        init_schema(self.conn)
        init_schema(self.conn)  # must not raise (e.g. duplicate ALTER COLUMN)
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(quota_snapshots)").fetchall()]
        # Each new column appears exactly once.
        for col in ('reset_at', 'window_minutes', 'limit_label'):
            self.assertEqual(cols.count(col), 1)
        row = self._old_row()
        self.assertEqual(row['used'], 10.0)
        self.assertIsNone(row['reset_at'])


class RoundTripTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_reset_at_window_minutes_and_label_round_trip(self):
        record_quota(self.conn, 'codex', 1000, _codex_quota())
        result = latest_quota(self.conn, source='codex')
        row = result['codex']['openai']['rate_limit']
        self.assertEqual(row['reset_at'], 1789514532)
        self.assertEqual(row['window_minutes'], 43200)
        self.assertEqual(row['limit_label'], 'Monthly')
        self.assertEqual(result['codex']['_plan'], 'Codex (Free)')

    def test_multiple_meters_in_one_cycle_all_persist(self):
        data = {
            '_plan': 'Codex (Free)',
            'openai': {
                'rate_limit': {
                    'used': 40.0, 'total': 100.0, 'remaining_pct': 60.0,
                    'refreshes_in_seconds': 100, 'reset_at': 111,
                    'window_minutes': 43200, 'limit_label': 'Monthly',
                },
                'rate_limit_secondary': {
                    'used': 5.0, 'total': 100.0, 'remaining_pct': 95.0,
                    'refreshes_in_seconds': 50, 'reset_at': 222,
                    'window_minutes': 1440, 'limit_label': 'Secondary (Daily)',
                },
            },
        }
        record_quota(self.conn, 'codex', 2000, data)
        result = latest_quota(self.conn, source='codex')
        group = result['codex']['openai']
        self.assertEqual(set(group.keys()), {'rate_limit', 'rate_limit_secondary'})
        self.assertEqual(group['rate_limit']['reset_at'], 111)
        self.assertEqual(group['rate_limit_secondary']['reset_at'], 222)
        self.assertEqual(group['rate_limit_secondary']['limit_label'], 'Secondary (Daily)')

    def test_status_key_does_not_become_a_quota_group(self):
        data = _codex_quota()
        data['_status'] = {'live': True, 'observed_at': 1000, 'age_seconds': 0, 'stale': False}
        record_quota(self.conn, 'codex', 3000, data)
        result = latest_quota(self.conn, source='codex')
        self.assertEqual(result['codex']['_plan'], 'Codex (Free)')
        self.assertIn('openai', result['codex'])
        self.assertNotIn('_status', result['codex'])
        groups = {r['model_group'] for r in self.conn.execute(
            "SELECT DISTINCT model_group FROM quota_snapshots WHERE source='codex'")}
        self.assertNotIn('_status', groups)

    def test_plan_only_snapshot_is_returned_without_being_skipped(self):
        record_quota(self.conn, 'codex', 4000, {'_plan': 'Codex (Free)'})
        result = latest_quota(self.conn, source='codex')
        self.assertEqual(result, {'codex': {'_plan': 'Codex (Free)'}})
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM quota_snapshots WHERE source='codex'").fetchone()
        self.assertEqual(rows['n'], 0)


if __name__ == '__main__':
    unittest.main()
