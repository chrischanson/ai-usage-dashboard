import sqlite3
import tempfile
import unittest
from pathlib import Path

from marathon_tracker.config import load_races, save_races, load_previous_output, save_race_results
from marathon_tracker.db import init_db
from marathon_tracker.models import Race, RaceResult
from marathon_tracker.render import render_markdown, render_html


class TestSubdivisions(unittest.TestCase):
    def setUp(self):
        # Create a temporary database file
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            self.db_path = Path(f.name)

    def tearDown(self):
        # Clean up temporary database file
        if self.db_path.exists():
            self.db_path.unlink()

    def test_database_seeding(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        cursor = conn.cursor()

        # Check US-MA
        cursor.execute(
            "SELECT name FROM loc_subdivisions WHERE code = 'MA' AND country_name = 'United States'"
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Massachusetts")

        # Check AU-QLD
        cursor.execute(
            "SELECT name FROM loc_subdivisions WHERE code = 'QLD' AND country_name = 'Australia'"
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Queensland")

        # Check UK Home Nation (Northern Ireland)
        cursor.execute(
            "SELECT name FROM loc_subdivisions WHERE code = 'NIR' AND country_name = 'Northern Ireland'"
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Northern Ireland")

        # Check Mexico City manual fallback
        cursor.execute(
            "SELECT name FROM loc_subdivisions WHERE code = 'CMX' AND country_name = 'Mexico'"
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Ciudad de México")

        conn.close()

    def test_save_and_load_races_with_subdivision(self):
        race = Race(
            id="boston-marathon",
            name="Boston Marathon",
            city="Boston",
            state_province="MA",
            country="United States",
            region="North America",
            official_url="https://baa.org",
        )
        save_races([race], self.db_path)

        loaded_races = load_races(self.db_path)
        self.assertEqual(len(loaded_races), 1)
        self.assertEqual(loaded_races[0].state_province, "MA")
        self.assertEqual(loaded_races[0].state_province_name, "Massachusetts")

    def test_dynamic_unknown_subdivision_insertion(self):
        # Insert a race with a custom state_province not in the standard JSON seed
        race = Race(
            id="custom-race",
            name="Custom Race",
            city="Custom City",
            state_province="XYZ",
            country="United States",
            region="North America",
            official_url="https://custom.example.com",
        )
        save_races([race], self.db_path)

        # Load it and verify that state_province_name falls back to "XYZ"
        loaded_races = load_races(self.db_path)
        self.assertEqual(len(loaded_races), 1)
        self.assertEqual(loaded_races[0].state_province, "XYZ")
        self.assertEqual(loaded_races[0].state_province_name, "XYZ")

        # Check database directly
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM loc_subdivisions WHERE code = 'XYZ' AND country_name = 'United States'"
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "XYZ")
        conn.close()

    def test_rendering_prefers_human_readable_name(self):
        payload = {
            "generated_at": "2026-06-21T23:00:00Z",
            "count": 1,
            "races": [
                {
                    "id": "boston-marathon",
                    "name": "Boston Marathon",
                    "distance": "marathon",
                    "city": "Boston",
                    "state_province": "MA",
                    "state_province_name": "Massachusetts",
                    "country": "United States",
                    "region": "North America",
                    "official_url": "https://baa.org",
                    "confidence": "high",
                    "event_date": "2026-04-20",
                    "registration_windows": [],
                }
            ],
        }

        md = render_markdown(payload)
        html = render_html(payload)

        self.assertIn("Boston, Massachusetts, United States", md)
        self.assertNotIn("Boston, MA, United States", md)

        self.assertIn("Boston, Massachusetts, United States", html)
        self.assertNotIn("Boston, MA, United States", html)


if __name__ == "__main__":
    unittest.main()
