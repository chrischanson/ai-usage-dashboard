import unittest
from unittest.mock import patch

from marathon_tracker.extract import apply_extraction, extract_dates, normalize_date
from marathon_tracker.models import Race, RaceResult


def _make_race(**kwargs):
    defaults = dict(
        id="test",
        name="Test Marathon",
        city="Testville",
        country="Testland",
        region="Test Region",
        official_url="https://x.example.com",
    )
    defaults.update(kwargs)
    return Race(**defaults)


def _make_result(**kwargs):
    return RaceResult.from_race(_make_race(**kwargs))


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


class TestHallucinationGuard(unittest.TestCase):
    """Verifier tests for Issue 1: hallucination guard in apply_extraction()."""

    def test_mock_note_downgrades_confidence_and_clears_date(self):
        """LLM note containing 'mock' must force confidence=low and discard event_date."""
        result = _make_result()
        apply_extraction(result, {
            "event_date": "2027-04-19",
            "confidence": "high",
            "notes": "Successfully extracted mock registration dates.",
            "raw_evidence": [],
            "registration_windows": [],
        }, replace_existing=True)
        self.assertEqual(result.confidence, "low")    # MUST be downgraded
        self.assertIsNone(result.event_date)           # MUST be rejected
        self.assertIn("HALLUCINATION GUARD", result.notes)

    def test_suspicious_words_trigger_guard(self):
        """All suspicious vocabulary must trigger the guard."""
        suspicious_notes = [
            "This is sample data",
            "Used a placeholder date",
            "Hallucinated from training",
            "Fictional race details",
            "Fake dates provided",
            "Dummy extraction result",
            "Hypothetical registration period",
            "Test data inserted",
        ]
        for note in suspicious_notes:
            result = _make_result()
            apply_extraction(result, {
                "event_date": "2027-01-01",
                "confidence": "high",
                "notes": note,
                "raw_evidence": [],
                "registration_windows": [],
            }, replace_existing=True)
            self.assertEqual(result.confidence, "low", f"Guard not triggered for note: {note!r}")
            self.assertIsNone(result.event_date, f"event_date not cleared for note: {note!r}")

    def test_legitimate_note_passes_through(self):
        """A genuine LLM note must not trigger the guard."""
        result = _make_result()
        apply_extraction(result, {
            "event_date": "2026-10-11",
            "confidence": "high",
            "notes": "Event date confirmed from official race page. Registration opens July 2026.",
            "raw_evidence": ["Race Day: October 11, 2026"],
            "registration_windows": [],
        }, replace_existing=True)
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.event_date, "2026-10-11")

    def test_duplicate_date_across_batch_flagged(self):
        """_flag_duplicate_event_dates must flag a date shared by >= threshold races."""
        from marathon_tracker.update import _flag_duplicate_event_dates

        # Build 5 results all carrying the same bogus date
        results = []
        for i in range(5):
            r = _make_result(id=f"race-{i}", name=f"Race {i}")
            r.event_date = "2027-04-19"
            r.extraction_method = "llm"
            r.confidence = "high"
            results.append(r)

        flagged = _flag_duplicate_event_dates(results, threshold=3)

        self.assertIn("2027-04-19", flagged)
        for r in results:
            self.assertIsNone(r.event_date, "Flagged event_date must be cleared")
            self.assertEqual(r.confidence, "low", "Flagged race must be downgraded")
            self.assertIn("DUPLICATE DATE GUARD", r.notes)

    def test_duplicate_date_below_threshold_not_flagged(self):
        """Dates shared by fewer than threshold races must NOT be flagged."""
        from marathon_tracker.update import _flag_duplicate_event_dates

        results = []
        for i in range(2):  # only 2, threshold=3
            r = _make_result(id=f"race-{i}", name=f"Race {i}")
            r.event_date = "2027-04-19"
            r.extraction_method = "llm"
            results.append(r)

        flagged = _flag_duplicate_event_dates(results, threshold=3)
        self.assertEqual(flagged, [])
        for r in results:
            self.assertEqual(r.event_date, "2027-04-19")  # unchanged

    def test_unrealistically_short_window_rejected(self):
        """A 4-day registration window must be silently dropped."""
        result = _make_result()
        apply_extraction(result, {
            "confidence": "high",
            "notes": "Extracted registration windows.",
            "raw_evidence": [],
            "registration_windows": [
                {
                    "window_type": "standard",
                    "open_date": "2026-09-14",
                    "close_date": "2026-09-18",   # only 4 days — too short
                }
            ],
        }, replace_existing=True)
        self.assertEqual(len(result.registration_windows), 0)  # MUST be rejected

    def test_window_exactly_at_minimum_is_accepted(self):
        """A window of exactly _MIN_WINDOW_DAYS days must be kept."""
        from marathon_tracker.extract import _MIN_WINDOW_DAYS
        result = _make_result()
        apply_extraction(result, {
            "confidence": "high",
            "notes": "Extracted registration windows.",
            "raw_evidence": [],
            "registration_windows": [
                {
                    "window_type": "standard",
                    "open_date": "2026-09-01",
                    "close_date": f"2026-09-{1 + _MIN_WINDOW_DAYS:02d}",  # exactly _MIN_WINDOW_DAYS days later
                }
            ],
        }, replace_existing=True)
        self.assertEqual(len(result.registration_windows), 1)

    def test_window_with_only_close_date_is_not_filtered(self):
        """A window with only a close_date (no open_date) cannot be length-checked and must pass."""
        result = _make_result()
        apply_extraction(result, {
            "confidence": "medium",
            "notes": "Lottery deadline only.",
            "raw_evidence": [],
            "registration_windows": [
                {
                    "window_type": "lottery",
                    "open_date": None,
                    "close_date": "2026-11-30",
                }
            ],
        }, replace_existing=True)
        self.assertEqual(len(result.registration_windows), 1)


if __name__ == "__main__":
    unittest.main()
