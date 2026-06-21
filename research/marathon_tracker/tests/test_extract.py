import unittest
from unittest.mock import patch

from marathon_tracker.extract import extract_dates, normalize_date
from marathon_tracker.models import Race


class ExtractTest(unittest.TestCase):
    def test_normalize_date(self):
        self.assertEqual(normalize_date("April 20, 2026"), "2026-04-20")
        self.assertEqual(normalize_date("20 April 2026"), "2026-04-20")
        self.assertEqual(normalize_date("2026-04-20"), "2026-04-20")

    @patch("marathon_tracker.extract.extract_with_llm")
    def test_regex_extracts_registration_deadline(self, mock_extract_llm):
        mock_extract_llm.return_value = None
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
        
        # Verify registration windows instead of deleted registration_deadline
        self.assertEqual(len(result.registration_windows), 2)
        standard_window = next(w for w in result.registration_windows if w.window_type == "standard")
        self.assertEqual(standard_window.close_date, "2026-03-01")
        qual_window = next(w for w in result.registration_windows if w.window_type == "qualification")
        self.assertEqual(qual_window.close_date, "2026-01-15")
        
        self.assertEqual(result.extraction_method, "regex")
        self.assertEqual(result.confidence, "medium")

    def test_normalize_date_rejects_stale_history(self):
        self.assertIsNone(normalize_date("March 2, 2007"))


if __name__ == "__main__":
    unittest.main()
