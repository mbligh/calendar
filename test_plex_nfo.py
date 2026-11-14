#!/usr/bin/env python3
"""Unit tests for RugbyPass/fixture metadata reconciliation."""
import datetime as dt
import unittest
import json
import tempfile
from pathlib import Path
from icalendar import Calendar
from filter import start_time
from zoneinfo import ZoneInfo

from plex_nfo import replay_observation, resolve_round, rugby_observations, build


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

    def test_unassigned_fixtures_and_stable_batch_numbering(self):
        from icalendar import Event
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            data = root / "data"
            docs.mkdir()
            data.mkdir()
            cal = Calendar()
            cal.add("version", "2.0")
            for uid, home, away, minute in [
                ("late", "England", "Japan", 30),
                ("early", "France", "South Africa", 10),
                ("future", "Wales", "Australia", 50),
            ]:
                event = Event()
                event.add("uid", uid)
                event.add("summary", f"{home} vs {away}")
                event.add("dtstart", dt.datetime(2026, 11, 13, 20, minute,
                                                  tzinfo=dt.timezone.utc))
                event.add("description", "Nations Championship 2026")
                cal.add_component(event)
            (docs / "rugby-nations.ics").write_bytes(cal.to_ical())
            records = []
            for uid, home, away, stamp in [
                ("later", "England", "Japan", "2026-11-14T08:00:00Z"),
                ("earlier", "France", "South Africa", "2026-11-14T09:00:00Z"),
            ]:
                records.append({"type": "VOD", "id": uid,
                    "title": f"{home} v {away} | Nations Championship 2026 | Round 5 | Full Match Replay",
                    "publishedDate": stamp})
            (data / "rugbypass.json").write_text(
                json.dumps({"source": "rugbypass", "records": records}))
            config = {"calendars": [{"slug": "rugby-nations", "name": "Rugby Nations",
                                    "type": "world-rugby"}]}
            now = dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc)
            _, manifest = build(config, docs, now)
            by_id = {f["id"]: f for f in manifest["fixtures"]}
            self.assertEqual(by_id["rugby-nations:early"]["episode"], 501)
            self.assertEqual(by_id["rugby-nations:late"]["episode"], 502)
            self.assertIsNone(by_id["rugby-nations:future"]["episode"])
            self.assertIsNone(by_id["rugby-nations:future"]["round"])
            (docs / "rugby-metadata-manifest.json").write_text(json.dumps(manifest))
            # Newly discovered earlier-kickoff fixture does not renumber old IDs.
            _, second = build(config, docs, now)
            self.assertEqual({f["id"]: f["episode"] for f in second["fixtures"]},
                             {f["id"]: f["episode"] for f in manifest["fixtures"]})


if __name__ == "__main__":
    unittest.main()
