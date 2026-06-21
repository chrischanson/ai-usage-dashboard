import tempfile
import unittest
from pathlib import Path

from marathon_tracker.models import RaceResult
from marathon_tracker.render import write_outputs


class TestRenderConfidence(unittest.TestCase):
    def setUp(self):
        self.tmp_dir_obj = tempfile.TemporaryDirectory()
        self.docs_dir = Path(self.tmp_dir_obj.name)

        # Create race results with varying confidence levels
        self.high_conf = RaceResult(
            id="boston-marathon",
            name="Boston Marathon",
            city="Boston",
            country="United States",
            region="North America",
            official_url="https://baa.org",
            registration_url=None,
            confidence="high",
            event_date="2026-04-20",
            year=2026,
            status="active"
        )
        self.med_conf = RaceResult(
            id="tokyo-marathon",
            name="Tokyo Marathon",
            city="Tokyo",
            country="Japan",
            region="Asia",
            official_url="https://tokyomarathon.jp",
            registration_url=None,
            confidence="medium",
            event_date="2026-03-01",
            year=2026,
            status="active"
        )
        self.low_conf = RaceResult(
            id="paris-marathon",
            name="Paris Marathon",
            city="Paris",
            country="France",
            region="Europe",
            official_url="https://parismarathon.fr",
            registration_url=None,
            confidence="low",
            event_date="2026-04-05",
            year=2026,
            status="active"
        )
        self.unknown_conf = RaceResult(
            id="berlin-marathon",
            name="Berlin Marathon",
            city="Berlin",
            country="Germany",
            region="Europe",
            official_url="https://berlinmarathon.de",
            registration_url=None,
            confidence="unknown",
            event_date="2026-09-27",
            year=2026,
            status="active"
        )

    def tearDown(self):
        self.tmp_dir_obj.cleanup()

    def test_render_excludes_low_confidence(self):
        # Pass a mix of confidence levels
        results = [self.high_conf, self.med_conf, self.low_conf, self.unknown_conf]
        write_outputs(results, self.docs_dir)

        md_file = self.docs_dir / "marathons.md"
        html_file = self.docs_dir / "index.html"
        self.assertTrue(md_file.exists())
        self.assertTrue(html_file.exists())

        md_content = md_file.read_text(encoding="utf-8")
        html_content = html_file.read_text(encoding="utf-8")

        # Verify high/medium are included, low/unknown are excluded
        self.assertIn("Boston Marathon", md_content)
        self.assertIn("Tokyo Marathon", md_content)
        self.assertNotIn("Paris Marathon", md_content)
        self.assertNotIn("Berlin Marathon", md_content)

        self.assertIn("Boston Marathon", html_content)
        self.assertIn("Tokyo Marathon", html_content)
        self.assertNotIn("Paris Marathon", html_content)
        self.assertNotIn("Berlin Marathon", html_content)

    def test_render_includes_medium_confidence(self):
        results = [self.med_conf]
        write_outputs(results, self.docs_dir)

        md_content = (self.docs_dir / "marathons.md").read_text(encoding="utf-8")
        self.assertIn("Tokyo Marathon", md_content)

    def test_render_includes_high_confidence(self):
        results = [self.high_conf]
        write_outputs(results, self.docs_dir)

        md_content = (self.docs_dir / "marathons.md").read_text(encoding="utf-8")
        self.assertIn("Boston Marathon", md_content)

    def test_render_count_reflects_filtered(self):
        # We pass 4, but only 2 should be published
        results = [self.high_conf, self.med_conf, self.low_conf, self.unknown_conf]
        write_outputs(results, self.docs_dir)

        md_content = (self.docs_dir / "marathons.md").read_text(encoding="utf-8")
        html_content = (self.docs_dir / "index.html").read_text(encoding="utf-8")

        # The count header should show "2 races tracked"
        self.assertIn("2 races tracked", md_content)
        self.assertIn("2 races tracked", html_content)

    def test_render_footer_note(self):
        results = [self.high_conf]
        write_outputs(results, self.docs_dir)

        md_content = (self.docs_dir / "marathons.md").read_text(encoding="utf-8")
        html_content = (self.docs_dir / "index.html").read_text(encoding="utf-8")

        note_md = "Only races with medium or high confidence are shown. See the database for all tracked races."
        self.assertIn(note_md, md_content)
        self.assertIn(note_md, html_content)


if __name__ == "__main__":
    unittest.main()
