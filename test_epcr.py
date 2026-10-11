"""Offline regression tests for the Champions Cup adapter and Plex metadata."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from epcr import convert_epcr
from plex_nfo import build


class RugbyEUTest(unittest.TestCase):
    def test_filter_rounds_and_nfo(self):
        matches = []
        for index, stage in enumerate(["1", "2", "3", "4", "R16", "QF", "SF", "TF"]):
            matches.append({
                "id": f"epcr-{index}", "tournament": "Investec Champions Cup",
                "round": stage, "homeTeam": "TBC" if index > 3 else "Home",
                "awayTeam": "TBC" if index > 3 else "Away",
                "dateTime": f"2027-01-{index+10:02d}T14:00:00.000Z",
                "venue": "TBD", "score": "DO NOT PUBLISH",
            })
        matches.append({**matches[0], "id": "other", "tournament": "European Challenge Cup"})
        calendar = convert_epcr({"seasonId": "202601", "matches": matches})
        self.assertEqual(len(calendar.walk("VEVENT")), 8)
        self.assertNotIn(b"DO NOT PUBLISH", calendar.to_ical())
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, "rugby-eu.ics").write_bytes(calendar.to_ical())
            output, manifest = build(
                {"calendars": [{"slug": "rugby-eu", "name": "Rugby EU"}]},
                Path(temp), dt.datetime(2026, 10, 11, tzinfo=dt.timezone.utc))
            self.assertEqual(len(manifest["fixtures"]), 8)
            self.assertEqual({x["round"] for x in manifest["fixtures"]}, set(range(1, 9)))
            self.assertTrue(any("Season_08/" in p for p in output))
            self.assertNotIn(b"DO NOT PUBLISH", b"".join(output.values()))

    def test_reject_unknown_round(self):
        with self.assertRaises(ValueError):
            convert_epcr({"seasonId": "202601", "matches": [{
                "id": "1", "tournament": "Investec Champions Cup",
                "round": "UNKNOWN", "dateTime": "2027-01-01T12:00:00Z",
                "homeTeam": "A", "awayTeam": "B",
            }]})


if __name__ == "__main__":
    unittest.main()
