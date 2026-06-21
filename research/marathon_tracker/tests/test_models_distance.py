import unittest
from marathon_tracker.models import Race, RaceResult, RegistrationWindow


class TestModelsDistance(unittest.TestCase):
    def test_race_default_distance(self):
        race = Race(
            id="test-race",
            name="Test Race",
            city="Seattle",
            country="United States",
            region="North America",
            official_url="https://example.com",
        )
        self.assertEqual(race.distance, "marathon")
        self.assertIsNone(race.state_province)

    def test_race_half_marathon_distance(self):
        race = Race(
            id="test-race-half",
            name="Test Race Half",
            city="Seattle",
            state_province="WA",
            country="United States",
            region="North America",
            official_url="https://example.com",
            distance="half-marathon",
        )
        self.assertEqual(race.distance, "half-marathon")
        self.assertEqual(race.state_province, "WA")

        raw = race.to_dict()
        self.assertEqual(raw["distance"], "half-marathon")
        self.assertEqual(raw["state_province"], "WA")

        restored = Race.from_dict(raw)
        self.assertEqual(restored.distance, "half-marathon")
        self.assertEqual(restored.state_province, "WA")

    def test_race_result_from_race_copies_distance(self):
        race = Race(
            id="test-race-half",
            name="Test Race Half",
            city="Seattle",
            state_province="WA",
            country="United States",
            region="North America",
            official_url="https://example.com",
            distance="half-marathon",
        )
        result = RaceResult.from_race(race)
        self.assertEqual(result.distance, "half-marathon")
        self.assertEqual(result.state_province, "WA")

    def test_race_result_to_dict_includes_distance(self):
        result = RaceResult(
            id="test-race-half",
            name="Test Race Half",
            city="Seattle",
            state_province="WA",
            country="United States",
            region="North America",
            official_url="https://example.com",
            registration_url=None,
            distance="half-marathon",
        )
        raw = result.to_dict()
        self.assertEqual(raw["distance"], "half-marathon")
        self.assertEqual(raw["state_province"], "WA")

        restored = RaceResult.from_dict(raw)
        self.assertEqual(restored.distance, "half-marathon")
        self.assertEqual(restored.state_province, "WA")

    def test_race_from_dict_missing_distance(self):
        raw = {
            "id": "test-race",
            "name": "Test Race",
            "city": "Seattle",
            "country": "United States",
            "region": "North America",
            "official_url": "https://example.com",
        }
        race = Race.from_dict(raw)
        self.assertEqual(race.distance, "marathon")
        self.assertIsNone(race.state_province)


if __name__ == "__main__":
    unittest.main()
