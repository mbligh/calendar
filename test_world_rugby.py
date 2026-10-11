"""Offline tests for World Rugby classification and spoiler-free fields."""
import datetime as dt
import unittest
from unittest.mock import patch

from world_rugby import competition_base, convert_match, fetch_world_rugby


def fixture(name, sport, match_id):
    return {
        "matchId": match_id, "competition": name, "sport": sport,
        "teams": [{"name": "Ireland"}, {"name": "Japan"}],
        "time": {"millis": 1791032400000},
        "venue": {"name": "Dublin"},
        "scores": [43, 19], "status": "C", "outcome": "A",
    }


class WorldRugbyTests(unittest.TestCase):
    def test_year_suffix(self):
        self.assertEqual(competition_base("Women's Internationals 2026"), "Women's Internationals")
        self.assertEqual(competition_base("WXV 2026"), "WXV")

    def test_spoiler_free(self):
        event = convert_match(fixture("Women's Internationals 2026", "WRU", "one"))
        serialized = event.to_ical().decode()
        self.assertIn("Ireland vs Japan", serialized)
        self.assertNotIn("43", serialized)
        self.assertNotIn("19", serialized)
        self.assertNotIn("outcome", serialized.lower())

    @patch("world_rugby.months", return_value=[(dt.date(2026, 10, 1), dt.date(2026, 10, 31))])
    @patch("world_rugby.request_page")
    def test_women_includes_wxv_but_excludes_bledisloe(self, request, _months):
        request.return_value = {
            "pageInfo": {"numPages": 1},
            "content": [
                fixture("Women's Internationals 2026", "WRU", "one"),
                fixture("WXV 2026", "WRU", "two"),
                fixture("Bledisloe Cup 2026", "MRU", "three"),
            ],
        }
        cal = fetch_world_rugby("womens-intl")
        self.assertEqual(len(cal.walk("VEVENT")), 2)


if __name__ == "__main__":
    unittest.main()
