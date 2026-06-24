import sqlite3
import tempfile
import unittest
from pathlib import Path

from marathon_tracker.config import load_races, save_races, load_previous_output, save_race_results
from marathon_tracker.db import init_db
from marathon_tracker.models import Race, RaceResult


class TestConfigDistance(unittest.TestCase):
    def setUp(self):
        # Create a temporary database file
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            self.db_path = Path(f.name)

    def tearDown(self):
        # Clean up temporary database file
        if self.db_path.exists():
            self.db_path.unlink()

    def test_load_races_includes_distance(self):
        # Insert a race with distance='half-marathon' into SQLite
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        cursor = conn.cursor()
        
        cursor.execute("INSERT OR IGNORE INTO loc_regions (name) VALUES ('Asia')")
        cursor.execute("INSERT OR IGNORE INTO loc_countries (name, region_name) VALUES ('Japan', 'Asia')")
        cursor.execute("INSERT INTO loc_locations (city, country_name) VALUES ('Tokyo', 'Japan')")
        loc_id = cursor.execute("SELECT id FROM loc_locations WHERE city = 'Tokyo'").fetchone()["id"]
        cursor.execute("INSERT INTO race_official_urls (url) VALUES ('https://tokyohalf.example.com')")
        url_id = cursor.execute("SELECT id FROM race_official_urls WHERE url = 'https://tokyohalf.example.com'").fetchone()["id"]
        
        cursor.execute(
            "INSERT INTO race_races (id, name, location_id, official_url_id) VALUES ('tokyo-half', 'Tokyo Half', ?, ?)",
            (loc_id, url_id)
        )
        cursor.execute("INSERT INTO race_offerings (race_id, distance) VALUES ('tokyo-half', 'half-marathon')")
        conn.commit()
        conn.close()

        races = load_races(self.db_path)
        self.assertEqual(len(races), 1)
        self.assertEqual(races[0].id, "tokyo-half")
        self.assertEqual(races[0].distance, "half-marathon")
        self.assertIsNone(races[0].state_province)

    def test_save_races_persists_distance(self):
        # save_races() with a Race(distance="half-marathon") -> query DB confirms distance='half-marathon'
        race = Race(
            id="boston-half",
            name="Boston Half Marathon",
            city="Boston",
            state_province="MA",
            country="United States",
            region="North America",
            official_url="https://bostonhalf.example.com",
            distance="half-marathon",
        )
        save_races([race], self.db_path)

        # Open connection and query directly to verify normalization and distance
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Verify loc_locations table has state_province
        loc = cursor.execute("SELECT * FROM loc_locations WHERE city = 'Boston'").fetchone()
        self.assertIsNotNone(loc)
        self.assertEqual(loc["state_province"], "MA")

        # Verify offering distance
        offering = cursor.execute("SELECT * FROM race_offerings WHERE race_id = 'boston-half'").fetchone()
        self.assertIsNotNone(offering)
        self.assertEqual(offering["distance"], "half-marathon")
        
        conn.close()

    def test_load_previous_output_includes_distance(self):
        # Save a RaceResult with distance='half-marathon' -> load_previous_output() returns it with correct distance
        result = RaceResult(
            id="london-half",
            name="London Half Marathon",
            city="London",
            state_province=None,
            country="United Kingdom",
            region="Europe",
            official_url="https://londonhalf.example.com",
            registration_url=None,
            distance="half-marathon",
            event_date="2026-05-10",
            year=2026,
            confidence="high",
            status="active"
        )
        
        save_race_results([result], self.db_path)
        
        previous = load_previous_output(self.db_path)
        self.assertIsNotNone(previous)
        key = ("london-half", "half-marathon", 2026)
        self.assertIn(key, previous)
        
        loaded = previous[key]
        self.assertEqual(loaded.distance, "half-marathon")
        self.assertEqual(loaded.name, "London Half Marathon")
        self.assertEqual(loaded.confidence, "high")
        self.assertEqual(loaded.state_province, None)

    def test_event_level_official_url_saved_and_loaded(self):
        # 1. Create a RaceResult with an event-level official URL that differs from the race level
        result = RaceResult(
            id="chicago-marathon",
            name="Chicago Marathon",
            city="Chicago",
            state_province="IL",
            country="United States",
            region="North America",
            official_url="https://chicagomarathon2026.example.com",
            registration_url=None,
            distance="marathon",
            event_date="2026-10-11",
            year=2026,
            confidence="high",
            status="active"
        )
        
        # 2. Save the race result
        save_race_results([result], self.db_path)
        
        # 3. Verify event official_url is saved and loaded correctly
        previous = load_previous_output(self.db_path)
        self.assertIsNotNone(previous)
        key = ("chicago-marathon", "marathon", 2026)
        self.assertIn(key, previous)
        self.assertEqual(previous[key].official_url, "https://chicagomarathon2026.example.com")
        
        # 4. Connect to database and directly query race_events to check if official_url_id is set
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Check event's official_url_id joins to our new URL
        row = cursor.execute("""
            SELECT e.official_url_id, ou.url
            FROM race_events e
            JOIN race_official_urls ou ON e.official_url_id = ou.id
        """).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["url"], "https://chicagomarathon2026.example.com")
        
        conn.close()


if __name__ == "__main__":
    unittest.main()

