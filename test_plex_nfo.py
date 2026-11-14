#!/usr/bin/env python3
"""Unit tests for RugbyPass/fixture metadata reconciliation."""
import datetime as dt
import unittest

from plex_nfo import replay_observation, resolve_round, infer_week_round


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

    def test_week_round(self):
        kickoff = dt.datetime(2026, 11, 14, 20, 10, tzinfo=dt.timezone.utc)
        self.assertEqual(infer_week_round(kickoff, [self.observation]), 5)


if __name__ == "__main__":
    unittest.main()
