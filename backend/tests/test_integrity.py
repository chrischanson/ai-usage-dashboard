import unittest
import sqlite3
from datetime import datetime, timezone
from integrity import fix_cycle_integrity, fix_all_integrity
from db import init_schema


class TestDataIntegrity(unittest.TestCase):
    def setUp(self):
        # Create an in-memory SQLite database for testing
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_fix_cycle_integrity_carries_forward(self):
        cursor = self.conn.cursor()
        
        # Insert a valid cycle for all sources at T=1000
        cursor.execute('''
            INSERT INTO usage_history (source, cycle_ts, timestamp, sessions, messages, input_tokens, output_tokens)
            VALUES ('opencode', 1000, '1970-01-01 00:16:40', 10, 100, 1000, 200)
        ''')
        cursor.execute('''
            INSERT INTO usage_history (source, cycle_ts, timestamp, sessions, messages, input_tokens, output_tokens)
            VALUES ('agy', 1000, '1970-01-01 00:16:40', 20, 200, 2000, 400)
        ''')
        cursor.execute('''
            INSERT INTO usage_history (source, cycle_ts, timestamp, sessions, messages, input_tokens, output_tokens)
            VALUES ('codex', 1000, '1970-01-01 00:16:40', 30, 300, 3000, 600)
        ''')
        
        # Insert model usage for opencode at T=1000
        cursor.execute('''
            INSERT INTO model_usage (source, cycle_ts, timestamp, model_name, messages, input_tokens, output_tokens, cost)
            VALUES ('opencode', 1000, '1970-01-01 00:16:40', 'gpt-4', 100, 1000, 200, 0.05)
        ''')
        
        # In the next cycle (T=2000), only 'opencode' reports
        cursor.execute('''
            INSERT INTO usage_history (source, cycle_ts, timestamp, sessions, messages, input_tokens, output_tokens)
            VALUES ('opencode', 2000, '1970-01-01 00:33:20', 11, 105, 1100, 210)
        ''')
        
        self.conn.commit()

        # Run integrity fix on T=2000
        fix_cycle_integrity(self.conn, 2000)
        self.conn.commit()

        # Verify that 'agy' and 'codex' were successfully carried forward to T=2000
        cursor.execute("SELECT * FROM usage_history WHERE cycle_ts=2000 ORDER BY source")
        rows = [dict(r) for r in cursor.fetchall()]
        
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['source'], 'agy')
        self.assertEqual(rows[0]['sessions'], 20)  # Carried forward
        self.assertEqual(rows[0]['input_tokens'], 2000)  # Carried forward
        self.assertEqual(rows[0]['timestamp'], '1970-01-01 00:33:20')  # Aligned timestamp
        
        self.assertEqual(rows[1]['source'], 'codex')
        self.assertEqual(rows[1]['sessions'], 30)  # Carried forward
        
        self.assertEqual(rows[2]['source'], 'opencode')
        self.assertEqual(rows[2]['sessions'], 11)  # Original new value

    def test_fix_all_integrity_back_fixes_correctly(self):
        cursor = self.conn.cursor()
        
        # T=1000 has all sources in both usage_history and collection_status
        for src in ['opencode', 'agy', 'codex']:
            cursor.execute('''
                INSERT INTO usage_history (source, cycle_ts, timestamp, sessions, messages, input_tokens, output_tokens)
                VALUES (?, 1000, '1970-01-01 00:16:40', 10, 10, 10, 10)
            ''', (src,))
            cursor.execute('''
                INSERT INTO collection_status (source, cycle_ts, ok, error, duration_ms)
                VALUES (?, 1000, 1, NULL, 100)
            ''', (src,))
            
        # T=2000 only has agy (but collection_status for all three to trigger the fix)
        cursor.execute('''
            INSERT INTO usage_history (source, cycle_ts, timestamp, sessions, messages, input_tokens, output_tokens)
            VALUES ('agy', 2000, '1970-01-01 00:33:20', 15, 15, 15, 15)
        ''')
        for src in ['opencode', 'agy', 'codex']:
            cursor.execute('''
                INSERT INTO collection_status (source, cycle_ts, ok, error, duration_ms)
                VALUES (?, 2000, 1, NULL, 100)
            ''', (src,))
        
        self.conn.commit()

        # Run full back-fix
        fix_all_integrity(self.conn)
        self.conn.commit()

        # Check total rows at T=2000 (should be 3)
        cursor.execute("SELECT COUNT(*) FROM usage_history WHERE cycle_ts=2000")
        self.assertEqual(cursor.fetchone()[0], 3)


if __name__ == '__main__':
    unittest.main()
