import unittest

from marathon_tracker.extract import extract_dates, normalize_date
from marathon_tracker.models import Race


class ExtractTest(unittest.TestCase):
    def test_normalize_date(self):
        self.assertEqual(normalize_date("April 20, 2026"), "2026-04-20")
        self.assertEqual(normalize_date("20 April 2026"), "2026-04-20")
        self.assertEqual(normalize_date("2026-04-20"), "2026-04-20")

    def test_regex_extracts_registration_deadline(self):
        race = Race(
            id="sample",
            name="Sample Marathon",
            city="Sample City",
            country="Sample Country",
            region="Sample Region",
            official_url="https://example.com",
        )
        text = """
        Race day is April 20, 2026.
        Registration deadline: March 1, 2026.
        The qualifying period closes on January 15, 2026.
        """
        result = extract_dates(race, text)
        self.assertEqual(result.event_date, "2026-04-20")
        self.assertEqual(result.registration_deadline, "2026-03-01")
        self.assertEqual(result.extraction_method, "regex")
        self.assertEqual(result.confidence, "medium")

    def test_normalize_date_rejects_stale_history(self):
        self.assertIsNone(normalize_date("March 2, 2007"))


if __name__ == "__main__":
    unittest.main()
