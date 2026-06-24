import unittest
import sqlite3
import json
from marathon_tracker.db import init_db

@unittest.skip("SQL triggers are currently paused during system building")
class TestTriggers(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_triggers_logging(self):
        # Seed region & country
        self.conn.execute("INSERT OR IGNORE INTO loc_regions (name) VALUES ('Test Region')")
        self.conn.execute("INSERT OR IGNORE INTO loc_countries (name, region_name) VALUES ('Testland', 'Test Region')")

        # 1. Insert mock location
        self.conn.execute("""
            INSERT OR IGNORE INTO loc_locations (city, state_province, country_name)
            VALUES ('Test City', NULL, 'Testland')
        """)
        cursor = self.conn.execute("SELECT id FROM loc_locations WHERE city='Test City' AND country_name='Testland'")
        location_id = cursor.fetchone()["id"]
        
        # Insert mock URLs
        self.conn.execute("INSERT INTO race_official_urls (url) VALUES ('https://test.com')")
        off_url_id = self.conn.execute("SELECT id FROM race_official_urls WHERE url='https://test.com'").fetchone()["id"]
        
        # 2. Insert mock race
        self.conn.execute("""
            INSERT INTO race_races (id, name, location_id, official_url_id)
            VALUES ('test-marathon', 'Test Marathon', ?, ?)
        """, (location_id, off_url_id))
        
        self.conn.execute("""
            INSERT INTO race_offerings (race_id, distance)
            VALUES ('test-marathon', 'marathon')
        """)
        offering_id = self.conn.execute("SELECT id FROM race_offerings WHERE race_id='test-marathon' AND distance='marathon'").fetchone()["id"]
        
        # Check change_log for race insert
        log_races = self.conn.execute("SELECT * FROM change_log WHERE record_id = 'test-marathon' AND action = 'INSERT'").fetchall()
        self.assertEqual(len(log_races), 1)
        self.assertEqual(log_races[0]["table_name"], "race_races")
        details = json.loads(log_races[0]["details"])
        self.assertEqual(details["new_values"]["name"], "Test Marathon")
        
        # 3. Insert mock race event
        self.conn.execute("""
            INSERT INTO race_events (race_offering_id, event_date, status)
            VALUES (?, '2027-10-10', 'active')
        """, (offering_id,))
        cursor = self.conn.execute("SELECT id FROM race_events WHERE race_offering_id=? AND event_date='2027-10-10'", (offering_id,))
        event_id = cursor.fetchone()["id"]
        
        # Check change_log for event insert
        log_events_ins = self.conn.execute(
            "SELECT * FROM change_log WHERE record_id = 'test-marathon - marathon (2027-10-10)' AND table_name = 'race_events' AND action = 'INSERT'"
        ).fetchall()
        self.assertEqual(len(log_events_ins), 1)
        details = json.loads(log_events_ins[0]["details"])
        self.assertEqual(details["new_values"]["event_date"], "2027-10-10")
        
        # Get count before updates
        count_before = self.conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
        
        # 4. Update mock race event date
        self.conn.execute("""
            UPDATE race_events 
            SET event_date = '2027-10-17' 
            WHERE id = ?
        """, (event_id,))
        
        # Check change_log for event update
        log_events_upd = self.conn.execute(
            "SELECT * FROM change_log WHERE record_id = 'test-marathon - marathon (2027-10-17)' AND table_name = 'race_events' AND action = 'UPDATE'"
        ).fetchall()
        self.assertEqual(len(log_events_upd), 1)
        details = json.loads(log_events_upd[0]["details"])
        self.assertEqual(details["old_values"]["event_date"], "2027-10-10")
        self.assertEqual(details["new_values"]["event_date"], "2027-10-17")
        
        # 5. Attempt event no-op update
        self.conn.execute("""
            UPDATE race_events 
            SET event_date = '2027-10-17' 
            WHERE id = ?
        """, (event_id,))
        
        # Verify no new change log entries were created
        count_after = self.conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
        self.assertEqual(count_after, count_before + 1)
        
        # 6. Insert mock registration window linked to official URL
        self.conn.execute("INSERT INTO race_official_urls (url) VALUES ('https://official-window-url.com')")
        url_id = self.conn.execute("SELECT id FROM race_official_urls WHERE url = 'https://official-window-url.com'").fetchone()["id"]
        
        self.conn.execute("""
            INSERT INTO race_registration_windows (event_id, window_type, description, open_date, close_date, official_url_id)
            VALUES (?, 'standard', 'Standard Registration', '2027-01-01', '2027-09-01', ?)
        """, (event_id, url_id))
        
        # Check change_log for window insert
        log_windows_ins = self.conn.execute(
            "SELECT * FROM change_log WHERE record_id = 'test-marathon - marathon (2027-10-17)' AND table_name = 'race_registration_windows' AND action = 'INSERT'"
        ).fetchall()
        self.assertEqual(len(log_windows_ins), 1)
        details = json.loads(log_windows_ins[0]["details"])
        self.assertEqual(details["new_values"]["window_type"], "standard")
        self.assertEqual(details["new_values"]["close_date"], "2027-09-01")
        self.assertEqual(details["new_values"]["official_url"], "https://official-window-url.com")
        
        # 7. Delete mock registration window
        self.conn.execute("DELETE FROM race_registration_windows WHERE event_id = ?", (event_id,))
        
        # Check change_log for window delete
        log_windows_del = self.conn.execute(
            "SELECT * FROM change_log WHERE record_id = 'test-marathon - marathon (2027-10-17)' AND table_name = 'race_registration_windows' AND action = 'DELETE'"
        ).fetchall()
        self.assertEqual(len(log_windows_del), 1)
        details = json.loads(log_windows_del[0]["details"])
        self.assertEqual(details["old_values"]["window_type"], "standard")
        self.assertEqual(details["old_values"]["close_date"], "2027-09-01")
        self.assertEqual(details["old_values"]["official_url"], "https://official-window-url.com")

if __name__ == "__main__":
    unittest.main()
