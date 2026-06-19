import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from marathon_tracker.discover import (
    _guess_region,
    _slugify,
    _WikiTableParser,
    clean_country_cell,
    merge_races,
)
from marathon_tracker.models import Race, RaceResult


class SlugifyTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_slugify("Tokyo Marathon"), "tokyo-marathon")

    def test_special_chars_removed(self):
        self.assertEqual(_slugify("Boston Marathon (2027)"), "boston-marathon-2027")

    def test_multiple_spaces_and_dashes(self):
        self.assertEqual(_slugify("New  York   Marathon"), "new-york-marathon")

    def test_already_slug(self):
        self.assertEqual(_slugify("berlin-marathon"), "berlin-marathon")

    def test_leading_trailing_dashes(self):
        self.assertEqual(_slugify("---london-marathon---"), "london-marathon")


class GuessRegionTest(unittest.TestCase):
    def test_north_america(self):
        self.assertEqual(_guess_region("United States"), "North America")
        self.assertEqual(_guess_region("Canada"), "North America")
        self.assertEqual(_guess_region("Mexico"), "North America")

    def test_south_america(self):
        self.assertEqual(_guess_region("Brazil"), "South America")
        self.assertEqual(_guess_region("Argentina"), "South America")

    def test_europe(self):
        self.assertEqual(_guess_region("Germany"), "Europe")
        self.assertEqual(_guess_region("France"), "Europe")
        self.assertEqual(_guess_region("United Kingdom"), "Europe")

    def test_asia(self):
        self.assertEqual(_guess_region("Japan"), "Asia")
        self.assertEqual(_guess_region("China"), "Asia")
        self.assertEqual(_guess_region("India"), "Asia")

    def test_africa(self):
        self.assertEqual(_guess_region("South Africa"), "Africa")
        self.assertEqual(_guess_region("Kenya"), "Africa")
        self.assertEqual(_guess_region("Ethiopia"), "Africa")

    def test_oceania(self):
        self.assertEqual(_guess_region("Australia"), "Oceania")
        self.assertEqual(_guess_region("New Zealand"), "Oceania")

    def test_unknown(self):
        self.assertEqual(_guess_region("Atlantis"), "Unknown")


class CleanCountryTest(unittest.TestCase):
    def test_strips_flags(self):
        self.assertEqual(clean_country_cell("Germany "), "Germany")

    def test_strips_bracketed_text(self):
        self.assertEqual(clean_country_cell("United States [note 1]"), "United States")

    def test_removes_alpha3_code(self):
        self.assertEqual(clean_country_cell("Germany GER"), "Germany")


class WikiTableParserTest(unittest.TestCase):
    def test_parses_simple_table(self):
        html = """<table>
<tr><td>Berlin Marathon</td><td>Berlin</td><td>Germany GER</td></tr>
<tr><td>Tokyo Marathon</td><td>Tokyo</td><td>Japan JPN</td></tr>
</table>"""
        parser = _WikiTableParser()
        parser.feed(html)
        self.assertEqual(len(parser.rows), 2)
        self.assertEqual(parser.rows[0], ("Berlin Marathon", "Berlin", "Germany"))
        self.assertEqual(parser.rows[1], ("Tokyo Marathon", "Tokyo", "Japan"))

    def test_skips_rows_with_fewer_than_3_cells(self):
        html = "<table><tr><td>Name</td><td>City</td></tr></table>"
        parser = _WikiTableParser()
        parser.feed(html)
        self.assertEqual(len(parser.rows), 0)

    def test_skips_script_contents(self):
        html = """<table>
<tr><td>London Marathon</td><td>London</td><td>United Kingdom GBR</td></tr>
<script>var x = 1;</script>
</table>"""
        parser = _WikiTableParser()
        parser.feed(html)
        self.assertEqual(len(parser.rows), 1)
        self.assertEqual(parser.rows[0][0], "London Marathon")


class MergeRacesTest(unittest.TestCase):
    def setUp(self):
        self.curated = [
            Race(id="tokyo-marathon", name="Tokyo Marathon", city="Tokyo", country="Japan",
                 region="Asia", official_url="https://marathon.tokyo/"),
            Race(id="boston-marathon", name="Boston Marathon", city="Boston", country="United States",
                 region="North America", official_url="https://baa.org/"),
        ]

    def test_curated_appears_first(self):
        discovered = [
            Race(id="paris-marathon", name="Paris Marathon", city="Paris", country="France",
                 region="Europe", official_url=""),
        ]
        merged = merge_races(self.curated, discovered)
        ids = [r.id for r in merged]
        self.assertIn("tokyo-marathon", ids)
        self.assertIn("boston-marathon", ids)
        self.assertIn("paris-marathon", ids)
        self.assertEqual(len(merged), 3)

    def test_discovered_duplicate_id_skipped(self):
        discovered = [
            Race(id="tokyo-marathon", name="Tokyo Marathon Dup", city="Tokyo", country="Japan",
                 region="Asia", official_url=""),
        ]
        merged = merge_races(self.curated, discovered)
        self.assertEqual(len(merged), 2)

    def test_discovered_duplicate_url_skipped(self):
        discovered = [
            Race(id="tokyo-dup", name="Tokyo Marathon", city="Tokyo", country="Japan",
                 region="Asia", official_url="https://marathon.tokyo/"),
        ]
        merged = merge_races(self.curated, discovered)
        self.assertEqual(len(merged), 2)

    def test_empty_discovered(self):
        merged = merge_races(self.curated, [])
        self.assertEqual(len(merged), 2)

    def test_previous_fills_gap(self):
        previous = {
            "paris-marathon": Race(id="paris-marathon", name="Paris Marathon", city="Paris",
                                    country="France", region="Europe", official_url="https://paris.fr/"),
        }
        merged = merge_races(self.curated, [], previous)
        ids = [r.id for r in merged]
        self.assertIn("paris-marathon", ids)
        self.assertEqual(len(merged), 3)

    def test_curated_overrides_previous(self):
        previous = {
            "tokyo-marathon": Race(id="tokyo-marathon", name="Tokyo Old", city="Old City",
                                    country="Old", region="Old", official_url="https://old.com/"),
        }
        merged = merge_races(self.curated, [], previous)
        tokyo = next(r for r in merged if r.id == "tokyo-marathon")
        self.assertEqual(tokyo.official_url, "https://marathon.tokyo/")

    def test_none_previous(self):
        merged = merge_races(self.curated, [], None)
        self.assertEqual(len(merged), 2)


class RaceResultModelTest(unittest.TestCase):
    def test_to_dict_includes_status(self):
        r = RaceResult(id="test", name="Test", city="City", country="Country",
                       region="Region", official_url="https://example.com",
                       registration_url=None)
        d = r.to_dict()
        self.assertEqual(d["status"], "active")
        self.assertIn("status", d)

    def test_from_dict_roundtrip(self):
        orig = RaceResult(id="test", name="Test", city="City", country="Country",
                          region="Region", official_url="https://example.com",
                          registration_url=None, status="carried-over",
                          extraction_method="carried-over")
        d = orig.to_dict()
        restored = RaceResult.from_dict(d)
        self.assertEqual(restored.id, "test")
        self.assertEqual(restored.status, "carried-over")
        self.assertEqual(restored.extraction_method, "carried-over")

    def test_from_dict_missing_status_defaults(self):
        d = {"id": "x", "name": "X", "city": "C", "country": "C", "region": "R",
             "official_url": "https://x.com"}
        r = RaceResult.from_dict(d)
        self.assertEqual(r.status, "active")

    def test_from_dict_with_previous_output_shape(self):
        d = {
            "id": "test", "name": "Test", "city": "City", "country": "Country",
            "region": "Region", "official_url": "https://example.com",
            "registration_url": None, "source_url": "https://example.com",
            "event_date": "2026-06-01", "extracted_at": "2026-01-01T00:00:00+00:00",
            "extraction_method": "seed", "confidence": "high", "status": "active",
            "notes": "", "raw_evidence": [],
        }
        r = RaceResult.from_dict(d)
        self.assertEqual(r.event_date, "2026-06-01")
        self.assertEqual(r.extracted_at, "2026-01-01T00:00:00+00:00")


class LoadPreviousOutputTest(unittest.TestCase):
    def test_missing_file_returns_none(self):
        from marathon_tracker.config import load_previous_output
        result = load_previous_output(Path("/nonexistent/path.json"))
        self.assertIsNone(result)

    def test_reads_valid_previous_output(self):
        from marathon_tracker.config import load_previous_output
        from marathon_tracker.db import init_db
        import sqlite3
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp = Path(f.name)
        try:
            conn = sqlite3.connect(tmp)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO locations (city, country, region) VALUES ('City', 'Country', 'Region')")
            location_id = cursor.execute("SELECT id FROM locations").fetchone()["id"]
            cursor.execute("INSERT INTO races (id, name, location_id, official_url) VALUES ('test', 'Test', ?, 'https://example.com')", (location_id,))
            cursor.execute("INSERT INTO race_events (race_id, year, event_date, status) VALUES ('test', 2026, '2026-06-01', 'active')")
            event_id = cursor.execute("SELECT id FROM race_events").fetchone()["id"]
            cursor.execute("INSERT INTO extraction_metadata (event_id, source_url, extracted_at, extraction_method, confidence, notes, raw_evidence) VALUES (?, 'https://example.com', '2026-01-01T00:00:00+00:00', 'seed', 'high', '', '[]')", (event_id,))
            
            # Insert official url and link to registration window
            cursor.execute("INSERT INTO official_urls (url) VALUES ('https://official-window.com')")
            url_id = cursor.execute("SELECT id FROM official_urls").fetchone()["id"]
            cursor.execute("""
                INSERT INTO registration_windows (event_id, window_type, description, open_date, close_date, official_url_id)
                VALUES (?, 'standard', 'Standard Entry', '2026-01-01', '2026-02-01', ?)
            """, (event_id, url_id))
            
            conn.commit()
            conn.close()
            
            result = load_previous_output(tmp)
            self.assertIsNotNone(result)
            self.assertIn(("test", 2026), result)
            self.assertEqual(result[("test", 2026)].name, "Test")
            self.assertEqual(result[("test", 2026)].status, "active")
            
            # Verify window loading and official URL mapping
            windows = result[("test", 2026)].registration_windows
            self.assertEqual(len(windows), 1)
            self.assertEqual(windows[0].window_type, "standard")
            self.assertEqual(windows[0].description, "Standard Entry")
            self.assertEqual(windows[0].open_date, "2026-01-01")
            self.assertEqual(windows[0].close_date, "2026-02-01")
            self.assertEqual(windows[0].official_url, "https://official-window.com")
        finally:
            tmp.unlink()


class CheckUrlTest(unittest.TestCase):
    @patch("marathon_tracker.fetch.urllib.request.urlopen")
    def test_reachable(self, mock_urlopen):
        from marathon_tracker.fetch import check_url
        mock_urlopen.return_value.__enter__.return_value.getcode.return_value = 200
        reachable, error = check_url("https://example.com")
        self.assertTrue(reachable)
        self.assertIsNone(error)

    @patch("marathon_tracker.fetch.urllib.request.urlopen")
    def test_unreachable(self, mock_urlopen):
        from marathon_tracker.fetch import check_url
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://example.com", 404, "Not Found", {}, None
        )
        reachable, error = check_url("https://example.com")
        self.assertFalse(reachable)
        self.assertIn("404", error)


class NeedsRefreshTest(unittest.TestCase):
    def setUp(self):
        from marathon_tracker.update import _needs_refresh, _days_until
        self._needs_refresh = _needs_refresh
        self._days_until = _days_until

    def _make_result(self, **kwargs) -> RaceResult:
        defaults = dict(
            id="test", name="Test", city="C", country="C", region="R",
            official_url="https://example.com", registration_url=None,
        )
        defaults.update(kwargs)
        return RaceResult(**defaults)

    def test_days_until_far_future(self):
        d = self._days_until("2027-12-25")
        self.assertIsNotNone(d)
        self.assertGreater(d, 365)

    def test_days_until_past(self):
        d = self._days_until("2020-01-01")
        self.assertIsNotNone(d)
        self.assertLess(d, 0)

    def test_days_until_none(self):
        self.assertIsNone(self._days_until(None))

    def test_days_until_invalid(self):
        self.assertIsNone(self._days_until("not-a-date"))

    def test_milestone_window_triggers_refresh(self):
        from datetime import timedelta
        from marathon_tracker.update import _now
        soon = (_now() + timedelta(days=10)).isoformat(timespec="seconds")
        r = self._make_result(event_date=soon)
        self.assertTrue(self._needs_refresh(r))

    def test_far_future_no_refresh(self):
        from marathon_tracker.models import RegistrationWindow
        r = self._make_result(
            event_date="2028-12-25",
            registration_windows=[
                RegistrationWindow("standard", "2028-06-01", "2028-09-01"),
                RegistrationWindow("lottery", None, "2028-08-01"),
                RegistrationWindow("qualification", None, "2028-07-01")
            ]
        )
        self.assertFalse(self._needs_refresh(r))

    def test_missing_milestones_triggers_refresh(self):
        r = self._make_result(
            event_date="2027-06-01",
            registration_windows=[]
        )
        self.assertTrue(self._needs_refresh(r))

    def test_far_future_with_all_dates_no_refresh(self):
        from marathon_tracker.models import RegistrationWindow
        r = self._make_result(
            event_date="2027-12-25",
            registration_windows=[
                RegistrationWindow("standard", "2027-01-01", "2027-11-01"),
                RegistrationWindow("lottery", None, "2027-10-01"),
                RegistrationWindow("qualification", None, "2027-09-01")
            ]
        )
        self.assertFalse(self._needs_refresh(r))

    def test_stale_data_triggers_refresh(self):
        from marathon_tracker.models import RegistrationWindow
        old = "2020-01-01T00:00:00+00:00"
        r = self._make_result(
            event_date="2027-12-25",
            registration_windows=[
                RegistrationWindow("standard", "2027-01-01", "2027-11-01")
            ],
            extracted_at=old
        )
        self.assertTrue(self._needs_refresh(r))


if __name__ == "__main__":
    unittest.main()
