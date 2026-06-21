import json
import unittest
from unittest.mock import MagicMock, patch

from marathon_tracker.discover import (
    discover_from_world_athletics,
    discover_from_wikipedia_page,
    merge_races,
)
from marathon_tracker.models import Race


class TestDiscoverHalf(unittest.TestCase):
    @patch("marathon_tracker.discover.urllib.request.urlopen")
    @patch("marathon_tracker.discover._load_country_map")
    def test_wa_half_marathon_discovery(self, mock_load_country, mock_urlopen):
        mock_load_country.return_value = {"USA": "United States"}
        
        # Mock GraphQL response for half-marathon competition
        mock_response_data = {
            "data": {
                "competitions": [
                    {
                        "id": "1",
                        "name": "Super Half Marathon",
                        "startDate": "2026-11-23",
                        "venue": {"city": "New York", "countryCode": "USA"},
                        "competitionSubgroup": "Gold",
                    }
                ]
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        races = discover_from_world_athletics()
        self.assertEqual(len(races), 1)
        self.assertEqual(races[0].distance, "half-marathon")
        self.assertEqual(races[0].id, "super-half-marathon")
        self.assertEqual(races[0].name, "Super Half Marathon")

    @patch("marathon_tracker.discover.urllib.request.urlopen")
    @patch("marathon_tracker.discover._load_country_map")
    def test_wa_mixed_distances(self, mock_load_country, mock_urlopen):
        mock_load_country.return_value = {"JPN": "Japan"}
        
        # Mock GraphQL response with both marathon and half-marathon
        mock_response_data = {
            "data": {
                "competitions": [
                    {
                        "id": "1",
                        "name": "Tokyo Half Marathon",
                        "startDate": "2026-03-01",
                        "venue": {"city": "Tokyo", "countryCode": "JPN"},
                        "competitionSubgroup": "Platinum",
                    },
                    {
                        "id": "2",
                        "name": "Tokyo Marathon",
                        "startDate": "2026-03-01",
                        "venue": {"city": "Tokyo", "countryCode": "JPN"},
                        "competitionSubgroup": "Platinum",
                    }
                ]
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        races = discover_from_world_athletics()
        # Since seasons list has two years [current_year, current_year-1], and both years might yield results,
        # we might get duplicates, but discover_from_world_athletics has a local seen_keys set to deduplicate.
        # But wait, since we mock urlopen to return the same output for each call, they will be deduplicated.
        self.assertEqual(len(races), 2)
        
        half_race = next(r for r in races if r.distance == "half-marathon")
        full_race = next(r for r in races if r.distance == "marathon")
        
        self.assertEqual(half_race.id, "tokyo-half-marathon")
        self.assertEqual(full_race.id, "tokyo-marathon")

    def test_merge_same_name_different_distance(self):
        # merge_races should NOT deduplicate the same base name if distance is different
        curated = [
            Race(
                id="tokyo-marathon",
                name="Tokyo Marathon",
                city="Tokyo",
                country="Japan",
                region="Asia",
                official_url="https://example.com/full",
                distance="marathon",
            )
        ]
        discovered = [
            Race(
                id="tokyo-marathon-half-marathon",
                name="Tokyo Marathon",
                city="Tokyo",
                country="Japan",
                region="Asia",
                official_url="https://example.com/half",
                distance="half-marathon",
            )
        ]
        
        merged = merge_races(curated, discovered)
        self.assertEqual(len(merged), 2)
        ids = {r.id for r in merged}
        self.assertIn("tokyo-marathon", ids)
        self.assertIn("tokyo-marathon-half-marathon", ids)

    def test_merge_same_name_same_distance(self):
        # merge_races SHOULD deduplicate same name and same distance
        curated = [
            Race(
                id="tokyo-marathon",
                name="Tokyo Marathon",
                city="Tokyo",
                country="Japan",
                region="Asia",
                official_url="https://example.com/full",
                distance="marathon",
            )
        ]
        discovered = [
            Race(
                id="tokyo-marathon",
                name="Tokyo Marathon",
                city="Tokyo",
                country="Japan",
                region="Asia",
                official_url="https://example.com/full",
                distance="marathon",
            )
        ]
        
        merged = merge_races(curated, discovered)
        self.assertEqual(len(merged), 1)

    @patch("marathon_tracker.discover.urllib.request.urlopen")
    def test_wikipedia_half_marathon_table(self, mock_urlopen):
        # Mock HTML returned by Wikipedia parse action
        html_content = """
        <table>
          <tr><th>Event</th><th>City</th><th>Country</th></tr>
          <tr>
            <td>Valencia Half Marathon</td>
            <td>Valencia</td>
            <td>Spain ESP</td>
          </tr>
        </table>
        """
        mock_response_data = {
            "parse": {
                "text": {
                    "*": html_content
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        races = discover_from_wikipedia_page("List_of_World_Athletics_Label_half_marathon_races", "half-marathon")
        self.assertEqual(len(races), 1)
        self.assertEqual(races[0].distance, "half-marathon")
        self.assertEqual(races[0].id, "valencia-half-marathon")
        self.assertEqual(races[0].city, "Valencia")
        self.assertEqual(races[0].country, "Spain")


if __name__ == "__main__":
    unittest.main()
