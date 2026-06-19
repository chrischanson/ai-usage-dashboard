import sqlite3
import json
import sys
from pathlib import Path

from marathon_tracker.db import init_db

# Paths
DB_PATH = Path("research/marathon_tracker/docs/marathons.db")

def test_triggers():
    if not DB_PATH.exists():
        print(f"Error: Database file not found at {DB_PATH}")
        sys.exit(1)
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    init_db(conn)
    
    # We use a transaction so we can rollback at the end, keeping the DB clean.
    conn.execute("BEGIN;")
    
    try:
        print("1. Inserting mock location...")
        conn.execute("""
            INSERT OR IGNORE INTO locations (city, country, region)
            VALUES ('Test City', 'Testland', 'Test Region')
        """)
        cursor = conn.execute("SELECT id FROM locations WHERE city='Test City' AND country='Testland'")
        location_id = cursor.fetchone()["id"]
        print(f"   Location inserted with ID {location_id}.")
        
        print("2. Inserting mock race...")
        conn.execute("""
            INSERT INTO races (id, name, location_id, distance, official_url, registration_url)
            VALUES ('test-marathon', 'Test Marathon', ?, 'marathon', 'https://test.com', 'https://test.com/register')
        """, (location_id,))
        
        # Check change_log for race insert
        log_races = conn.execute("SELECT * FROM change_log WHERE record_id = 'test-marathon' AND action = 'INSERT'").fetchall()
        assert len(log_races) == 1, f"Expected 1 log entry, found {len(log_races)}"
        assert log_races[0]["table_name"] == "races"
        details = json.loads(log_races[0]["details"])
        assert details["new_values"]["name"] == "Test Marathon"
        print("   ✅ Race insert logged correctly.")
        
        print("3. Inserting mock race event...")
        conn.execute("""
            INSERT INTO race_events (race_id, year, event_date, status)
            VALUES ('test-marathon', 2027, '2027-10-10', 'active')
        """)
        cursor = conn.execute("SELECT id FROM race_events WHERE race_id='test-marathon' AND year=2027")
        event_id = cursor.fetchone()["id"]
        
        # Check change_log for event insert
        log_events_ins = conn.execute("SELECT * FROM change_log WHERE record_id = 'test-marathon (2027)' AND table_name = 'race_events' AND action = 'INSERT'").fetchall()
        assert len(log_events_ins) == 1, f"Expected 1 log entry, found {len(log_events_ins)}"
        details = json.loads(log_events_ins[0]["details"])
        assert details["new_values"]["event_date"] == "2027-10-10"
        print("   ✅ Race event insert logged correctly.")
        
        # Get count before updates
        count_before = conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
        
        print("4. Updating mock race event date...")
        conn.execute("""
            UPDATE race_events 
            SET event_date = '2027-10-17' 
            WHERE id = ?
        """, (event_id,))
        
        # Check change_log for event update
        log_events_upd = conn.execute("SELECT * FROM change_log WHERE record_id = 'test-marathon (2027)' AND table_name = 'race_events' AND action = 'UPDATE'").fetchall()
        assert len(log_events_upd) == 1, f"Expected 1 update log entry, found {len(log_events_upd)}"
        details = json.loads(log_events_upd[0]["details"])
        assert details["old_values"]["event_date"] == "2027-10-10"
        assert details["new_values"]["event_date"] == "2027-10-17"
        print("   ✅ Race event update logged correctly.")
        
        print("5. Attempting event no-op update...")
        conn.execute("""
            UPDATE race_events 
            SET event_date = '2027-10-17' 
            WHERE id = ?
        """, (event_id,))
        
        # Verify no new change log entries were created
        count_after = conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
        assert count_after == count_before + 1, f"No-op update generated log entry! Before: {count_before+1}, After: {count_after}"
        print("   ✅ Event no-op update successfully bypassed by the trigger WHEN condition.")
        
        print("6. Inserting mock registration window linked to official URL...")
        conn.execute("INSERT INTO official_urls (url) VALUES ('https://official-window-url.com')")
        url_id = conn.execute("SELECT id FROM official_urls WHERE url = 'https://official-window-url.com'").fetchone()["id"]
        
        conn.execute("""
            INSERT INTO registration_windows (event_id, window_type, description, open_date, close_date, official_url_id)
            VALUES (?, 'standard', 'Standard Registration', '2027-01-01', '2027-09-01', ?)
        """, (event_id, url_id))
        
        # Check change_log for window insert
        log_windows_ins = conn.execute("SELECT * FROM change_log WHERE record_id = 'test-marathon (2027)' AND table_name = 'registration_windows' AND action = 'INSERT'").fetchall()
        assert len(log_windows_ins) == 1, f"Expected 1 log entry, found {len(log_windows_ins)}"
        details = json.loads(log_windows_ins[0]["details"])
        assert details["new_values"]["window_type"] == "standard"
        assert details["new_values"]["close_date"] == "2027-09-01"
        assert details["new_values"]["official_url"] == "https://official-window-url.com"
        print("   ✅ Registration window insert logged correctly with official URL.")
        
        print("7. Deleting mock registration window...")
        conn.execute("DELETE FROM registration_windows WHERE event_id = ?", (event_id,))
        
        # Check change_log for window delete
        log_windows_del = conn.execute("SELECT * FROM change_log WHERE record_id = 'test-marathon (2027)' AND table_name = 'registration_windows' AND action = 'DELETE'").fetchall()
        assert len(log_windows_del) == 1, f"Expected 1 log entry, found {len(log_windows_del)}"
        details = json.loads(log_windows_del[0]["details"])
        assert details["old_values"]["window_type"] == "standard"
        assert details["old_values"]["close_date"] == "2027-09-01"
        assert details["old_values"]["official_url"] == "https://official-window-url.com"
        print("   ✅ Registration window deletion logged correctly with official URL.")
        
        print("\nAll database triggers are functioning perfectly under the registration windows schema! 🎉")
        
    except AssertionError as e:
        print(f"\n❌ Verification failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
    finally:
        print("\nRolling back transaction to keep the database clean...")
        conn.execute("ROLLBACK;")
        conn.close()

if __name__ == "__main__":
    test_triggers()
