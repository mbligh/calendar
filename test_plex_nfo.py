#!/usr/bin/env python3
"""Unit tests for RugbyPass/fixture metadata reconciliation."""
import datetime as dt
import unittest
from pathlib import Path
from icalendar import Calendar
from filter import start_time
from zoneinfo import ZoneInfo

from plex_nfo import replay_observation, resolve_round, infer_week_round, rugby_observations


class RugbyPassRoundTests(unittest.TestCase):
    def setUp(self):
        record = {
            "type": "VOD", "id": "1051364",
            "title": "France v South Africa | Nations Championship 2026 | Round 5 | Full Match Replay",
            "publishedDate": "2026-11-13T22:31:00Z",
        }
        self.observation = replay_observation(record)

    def test_read_round(self):
        self.assertEqual(self.observation[3:], (5, "1051364"))

    def test_match_same_day(self):
        kickoff = dt.datetime(2026, 11, 13, 20, 10, tzinfo=dt.timezone.utc)
        self.assertEqual(resolve_round(kickoff, "France", "South Africa",
                                       [self.observation]), (5, "1051364"))

    def test_one_day_tolerance(self):
        kickoff = dt.datetime(2026, 11, 12, 20, 10, tzinfo=dt.timezone.utc)
        self.assertEqual(resolve_round(kickoff, "France", "South Africa",
                                       [self.observation]), (5, "1051364"))

    def test_no_other_teams(self):
        kickoff = dt.datetime(2026, 11, 13, 20, 10, tzinfo=dt.timezone.utc)
        self.assertEqual(resolve_round(kickoff, "Wales", "South Africa",
                                       [self.observation]), (None, None))

    def test_repository_snapshot_resolves_france_south_africa(self):
        root = Path(__file__).resolve().parent
        observations = [r for item in rugby_observations(root / "data" / "rugbypass.json")
                        if (r := replay_observation(item)) is not None]
        self.assertGreater(len(observations), 0)
        cal = Calendar.from_ical((root / "docs" / "rugby-nations.ics").read_bytes())
        fixtures = [e for e in cal.walk("VEVENT")
                    if str(e.get("SUMMARY", "")) == "France vs South Africa"]
        self.assertEqual(len(fixtures), 1)
        kickoff = start_time(fixtures[0], ZoneInfo("Europe/London"))
        self.assertEqual(resolve_round(kickoff, "France", "South Africa", observations),
                         (5, "1051364"))

    def test_week_round(self):
        kickoff = dt.datetime(2026, 11, 14, 20, 10, tzinfo=dt.timezone.utc)
        self.assertEqual(infer_week_round(kickoff, [self.observation]), 5)


if __name__ == "__main__":
    unittest.main()
