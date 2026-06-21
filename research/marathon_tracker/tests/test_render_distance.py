import tempfile
import unittest
from pathlib import Path

from marathon_tracker.models import RaceResult
from marathon_tracker.render import write_outputs


class TestRenderDistance(unittest.TestCase):
    def setUp(self):
        self.tmp_dir_obj = tempfile.TemporaryDirectory()
        self.docs_dir = Path(self.tmp_dir_obj.name)

        self.full_marathon = RaceResult(
            id="chicago-marathon",
            name="Chicago Marathon",
            city="Chicago",
            country="United States",
            region="North America",
            official_url="https://chicagomarathon.com",
            registration_url=None,
            confidence="high",
            event_date="2026-10-11",
            year=2026,
            distance="marathon",
            status="active"
        )
        self.half_marathon = RaceResult(
            id="chicago-half",
            name="Chicago Half",
            city="Chicago",
            country="United States",
            region="North America",
            official_url="https://chicagohalf.com",
            registration_url=None,
            confidence="medium",
            event_date="2026-09-27",
            year=2026,
            distance="half-marathon",
            status="active"
        )

    def tearDown(self):
        self.tmp_dir_obj.cleanup()

    def test_render_shows_distance_column(self):
        results = [self.full_marathon, self.half_marathon]
        write_outputs(results, self.docs_dir)

        md_content = (self.docs_dir / "marathons.md").read_text(encoding="utf-8")
        html_content = (self.docs_dir / "index.html").read_text(encoding="utf-8")

        # Verify Distance column in markdown table header
        self.assertIn("| Race | Distance | Location |", md_content)
        
        # Verify Distance header in html table
        self.assertIn("<th>Distance</th>", html_content)

    def test_render_marathon_label(self):
        results = [self.full_marathon]
        write_outputs(results, self.docs_dir)

        md_content = (self.docs_dir / "marathons.md").read_text(encoding="utf-8")
        html_content = (self.docs_dir / "index.html").read_text(encoding="utf-8")

        # In markdown, the line should contain the label "Marathon" in the column
        # Markdown row format: | **Chicago Marathon (2026)** | Marathon | Chicago, United States | ... |
        self.assertIn("| **Chicago Marathon (2026)** | Marathon | Chicago, United States |", md_content)

        # In html, the row should have data-distance="marathon" and the text cell "<td>Marathon</td>"
        self.assertIn('<tr data-distance="marathon">', html_content)
        self.assertIn('<td>Marathon</td>', html_content)

    def test_render_half_marathon_label(self):
        results = [self.half_marathon]
        write_outputs(results, self.docs_dir)

        md_content = (self.docs_dir / "marathons.md").read_text(encoding="utf-8")
        html_content = (self.docs_dir / "index.html").read_text(encoding="utf-8")

        # In markdown, the line should contain the label "Half Marathon" in the column
        self.assertIn("| **Chicago Half (2026)** | Half Marathon | Chicago, United States |", md_content)

        # In html, the row should have data-distance="half-marathon" and the text cell "<td>Half Marathon</td>"
        self.assertIn('<tr data-distance="half-marathon">', html_content)
        self.assertIn('<td>Half Marathon</td>', html_content)


if __name__ == "__main__":
    unittest.main()
