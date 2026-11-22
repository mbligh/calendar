"""Offline regression tests for the opt-in PVR Atlas rugby ICS publisher."""
import datetime as dt
import importlib.machinery
import io
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from icalendar import Calendar, Event

ROOT = pathlib.Path(__file__).resolve().parent
CLI = importlib.machinery.SourceFileLoader(
    "calendar_build_rugby_calendars", str(ROOT / "build_rugby_calendars")).load_module()
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 21, 12, tzinfo=UTC)
SLUG = "Rugby_Mens_Intl"
WOMEN = "Rugby_Womens_PWR"
WXV = "Rugby_Womens_WXV"
INTL = "Rugby_Womens_Intl"
CONFIG = {"timezone": "America/New_York", "calendars": [
    {"slug": SLUG, "name": "Rugby Mens Intl"},
    {"slug": WOMEN, "name": "Rugby Womens PWR"},
]}


def episode(slug, uid, when, **extra):
    return {"_id": f"{slug}:{uid}", "series_id": slug,
            "home": "England", "away": "Ireland", "scheduled": when,
            "season": 2026, "episode": 101, "round": 1,
            "venue": "Neutral Ground",
            **extra}


def old_calendar(*events):
    calendar = Calendar()
    calendar.add("prodid", "-//Test//EN")
    calendar.add("version", "2.0")
    for uid, title, instant in events:
        e = Event()
        e.add("uid", uid)
        e.add("summary", title)
        e.add("dtstart", instant)
        e.add("dtend", instant + dt.timedelta(hours=2))
        calendar.add_component(e)
    return calendar


class FakeEpisodes:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query):
        return [dict(row) for row in self.docs
                if row.get("series_id") == query["series_id"]]


class FakeDB:
    def __init__(self, docs):
        self.episodes = FakeEpisodes(docs)


class AtlasCalendarExportTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.directory = pathlib.Path(self.work.name) / "docs"
        self.directory.mkdir()
        self.future = NOW + dt.timedelta(days=2)
        self.docs = [
            episode(SLUG, "world-rugby-m001@mbligh.github.io",
                    self.future, raw_score={"home": 45, "away": 0}),
            episode(WOMEN, "pwr-289126@mbligh.github.io",
                    self.future + dt.timedelta(days=1)),
        ]

    def test_uid_stable_and_output_is_score_free(self):
        source, report = CLI.build_source([self.docs[0]], SLUG)
        event, = source.walk("VEVENT")
        self.assertEqual(str(event.get("uid")),
                         "world-rugby-m001@mbligh.github.io")
        payload = source.to_ical().decode()
        self.assertIn("England vs Ireland", payload)
        for secret in ("raw_score", "45", "outcome", "finalScore"):
            self.assertNotIn(secret, payload)
        self.assertEqual(report["source_fixtures"], 1)

    def test_preview_does_not_write_and_apply_only_writes_selected(self):
        db = FakeDB(self.docs)
        result = CLI.run(db, CONFIG, self.directory, series=[SLUG],
                         now=NOW, stream=io.StringIO())
        self.assertEqual(result[0]["added"], 1)
        self.assertFalse((self.directory / (SLUG + ".ics")).exists())
        CLI.run(db, CONFIG, self.directory, series=[SLUG],
                apply=True, now=NOW, stream=io.StringIO())
        self.assertTrue((self.directory / (SLUG + ".ics")).exists())
        self.assertFalse((self.directory / (WOMEN + ".ics")).exists())
        raw = (self.directory / (SLUG + ".ics")).read_bytes()
        CLI.run(db, CONFIG, self.directory, series=[SLUG], apply=True,
                now=NOW, stream=io.StringIO())
        self.assertEqual((self.directory / (SLUG + ".ics")).read_bytes(), raw)
        self.assertEqual(len(Calendar.from_ical(raw).walk("VEVENT")), 1)

    def test_frozen_past_uid_preserved_and_future_uid_updated(self):
        past = NOW - dt.timedelta(days=5)
        path = self.directory / (SLUG + ".ics")
        path.write_bytes(old_calendar(
            ("world-rugby-past@mbligh.github.io", "Ireland vs Italy", past),
            ("world-rugby-m001@mbligh.github.io", "Old Future Title", self.future)
        ).to_ical())
        docs = [
            episode(SLUG, "world-rugby-past@mbligh.github.io",
                    past, home="Spoiler", away="Result"),
            self.docs[0],
        ]
        CLI.run(FakeDB(docs), CONFIG, self.directory, series=[SLUG],
                apply=True, now=NOW, stream=io.StringIO())
        contents = Calendar.from_ical(path.read_bytes()).walk("VEVENT")
        titles = {str(e.get("uid")): str(e.get("summary")) for e in contents}
        self.assertEqual(titles["world-rugby-past@mbligh.github.io"],
                         "Ireland vs Italy")
        self.assertEqual(titles["world-rugby-m001@mbligh.github.io"],
                         "England vs Ireland")

    def test_missing_old_episodes_never_delete_existing_events(self):
        past = NOW - dt.timedelta(days=1)
        path = self.directory / (SLUG + ".ics")
        path.write_bytes(old_calendar(
            ("google-history@google.com", "Historical fixture", past)
        ).to_ical())
        CLI.run(FakeDB([self.docs[0]]), CONFIG, self.directory,
                series=[SLUG], apply=True, now=NOW, stream=io.StringIO())
        uids = [str(e.get("uid")) for e in
                Calendar.from_ical(path.read_bytes()).walk("VEVENT")]
        self.assertCountEqual(uids, [
            "google-history@google.com", "world-rugby-m001@mbligh.github.io"])

    def test_explicit_cancellation_removes_only_named_uid(self):
        past = NOW - dt.timedelta(days=1)
        path = self.directory / (SLUG + ".ics")
        path.write_bytes(old_calendar(
            ("cancelled@source", "Postponed", past),
            ("missing@source", "Other past fixture", past)
        ).to_ical())
        docs = [
            episode(SLUG, "cancelled@source", past, status="cancelled"),
            self.docs[0]
        ]
        result = CLI.run(FakeDB(docs), CONFIG, self.directory,
                         series=[SLUG], apply=True, now=NOW, stream=io.StringIO())
        self.assertEqual(result[0]["removed_cancelled"], 1)
        uids = [str(e.get("uid")) for e in
                Calendar.from_ical(path.read_bytes()).walk("VEVENT")]
        self.assertCountEqual(uids, [
            "missing@source", "world-rugby-m001@mbligh.github.io"])

    def test_tbc_fixture_is_skipped_without_inventing_time(self):
        no_time = episode(SLUG, "no-time@source", None)
        source, report = CLI.build_source([self.docs[0], no_time], SLUG)
        self.assertEqual(len(source.walk("VEVENT")), 1)
        self.assertEqual(report["skipped_unscheduled"], 1)

    def test_empty_series_aborts_all_writes(self):
        with self.assertRaisesRegex(ValueError, "No Atlas fixtures"):
            CLI.run(FakeDB([self.docs[0]]), CONFIG, self.directory,
                    apply=True, now=NOW, stream=io.StringIO())
        self.assertFalse(list(self.directory.glob("*.ics")))

    def test_duplicate_identity_and_wrong_series_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            CLI.build_source([self.docs[0], self.docs[0]], SLUG)
        with self.assertRaisesRegex(ValueError, "does not belong"):
            CLI.build_source([self.docs[1]], SLUG)

    def test_no_retroactive_new_past_events(self):
        past = episode(SLUG, "new-past@source", NOW - dt.timedelta(days=1))
        db = FakeDB([past, self.docs[0]])
        plan, = CLI.plan(db, CONFIG, self.directory, series=[SLUG], now=NOW)
        self.assertEqual(plan["added"], 1)
        self.assertEqual(plan["published_events"], 1)

    def test_wxv_moves_frozen_events_to_dedicated_feed(self):
        # Migrate a past WXV VEVENT without re-creating it from a past
        # source record (which would violate the spoiler-free freeze).
        past = NOW - dt.timedelta(days=29)
        uid = "world-rugby-wxv-1@mbligh.github.io"
        old_intl = old_calendar(
            (uid, "Original frozen WXV match", past),
            ("international@source", "Other Intl event", past))
        for event in old_intl.walk("VEVENT"):
            if str(event.get("UID")) == uid:
                event.add("description", "WXV 2026")
        (self.directory / (INTL + ".ics")).write_bytes(old_intl.to_ical())
        db = FakeDB([
            episode(INTL, "international@source", past),
            episode(WXV, uid, past, home="Updated", away="Teams")
        ])
        config = {"timezone": "America/New_York", "calendars": [
            {"slug": INTL, "name": "Rugby Womens Intl"},
            {"slug": WXV, "name": "Rugby Womens WXV"}
        ]}
        preview = CLI.run(db, config, self.directory, now=NOW,
                          stream=io.StringIO())
        self.assertEqual(preview[0]["migrated_wxv"], 1)
        self.assertFalse((self.directory / (WXV + ".ics")).exists())
        CLI.run(db, config, self.directory, now=NOW, apply=True,
                stream=io.StringIO())
        intl = Calendar.from_ical((self.directory / (INTL + ".ics")).read_bytes())
        wxv = Calendar.from_ical((self.directory / (WXV + ".ics")).read_bytes())
        self.assertEqual([str(x.get("UID")) for x in intl.walk("VEVENT")],
                         ["international@source"])
        self.assertEqual([str(x.get("UID")) for x in wxv.walk("VEVENT")], [uid])
        self.assertEqual(str(wxv.walk("VEVENT")[0].get("SUMMARY")),
                         "Original frozen WXV match")
        # Idempotent: the historic event never appears in both feeds.
        CLI.run(db, config, self.directory, now=NOW, apply=True,
                stream=io.StringIO())
        self.assertEqual(len(Calendar.from_ical(
            (self.directory / (WXV + ".ics")).read_bytes()).walk("VEVENT")), 1)

    def test_wxv_crossfeed_refuses_incomplete_cutover(self):
        uid = "world-rugby-wxv-2@mbligh.github.io"
        old = old_calendar((uid, "WXV existing", NOW - dt.timedelta(days=9)))
        old.walk("VEVENT")[0].add("description", "WXV 2026")
        (self.directory / (INTL + ".ics")).write_bytes(old.to_ical())
        db = FakeDB([episode(INTL, "other@source", self.future),
                     episode(WXV, "different@source", self.future)])
        config = {"timezone": "America/New_York", "calendars": [
            {"slug": INTL, "name": "Rugby Womens Intl"},
            {"slug": WXV, "name": "Rugby Womens WXV"},
        ]}
        with self.assertRaisesRegex(ValueError, "missing authoritative Atlas"):
            CLI.run(db, config, self.directory, apply=True,
                    now=NOW, stream=io.StringIO())
        with self.assertRaisesRegex(ValueError, "requires exporting"):
            CLI.run(db, config, self.directory, series=[INTL], apply=True,
                    now=NOW, stream=io.StringIO())
        self.assertFalse((self.directory / (WXV + ".ics")).exists())

    def test_superseded_legacy_wxv_episode_does_not_republish(self):
        old = episode(SLUG, "world-rugby-legacy@mbligh.github.io",
                      self.future, status="superseded")
        source, report = CLI.build_source([self.docs[0], old], SLUG)
        self.assertEqual(report["superseded"], 1)
        self.assertEqual(len(source.walk("VEVENT")), 1)

    def test_activation_commits_only_managed_feeds_and_switch_marker(self):
        root = pathlib.Path(self.work.name)
        (root / ".github").mkdir()
        created = []
        def execute(args, **kwargs):
            created.append(list(args))
            if args[:3] == ["git", "branch", "--show-current"]:
                return SimpleNamespace(returncode=0, stdout="main")
            if args[:3] == ["git", "diff", "--cached"]:
                return SimpleNamespace(returncode=1)
            return SimpleNamespace(returncode=0)
        with patch.object(CLI, "ROOT", root):
            outcome = CLI.publish_to_git(
                [{"path": self.directory / (SLUG + ".ics")}],
                activate=True, execute=execute)
        self.assertEqual(outcome, "pushed")
        self.assertTrue((root / ".github" / "atlas-rugby-active").exists())
        self.assertEqual(created[1][:3], ["git", "add", "--"])
        self.assertIn(str(root / ".github" / "atlas-rugby-active"), created[1])
        self.assertEqual(created[-1], ["git", "push", "origin", "main"])
        self.assertEqual(len([v for v in created if v[:2] == ["git", "commit"]]), 1)

    def test_refuse_publish_from_non_main_branch(self):
        root = pathlib.Path(self.work.name)
        called = []
        def execute(args, **kwargs):
            called.append(args)
            return SimpleNamespace(returncode=0, stdout="feature")
        with patch.object(CLI, "ROOT", root), self.assertRaisesRegex(
                ValueError, "main branch"):
            CLI.publish_to_git([{"path": self.directory / "Rugby_Mens_Intl.ics"}],
                               execute=execute)
        self.assertEqual(len(called), 1)

    def test_default_PyMongo_naive_UTC_is_interpreted_correctly(self):
        naive = self.future.replace(tzinfo=None)
        ev = CLI.event_from_episode(episode(SLUG, "utc@source", naive), SLUG)
        self.assertEqual(ev.decoded("dtstart").utcoffset(), dt.timedelta(0))


if __name__ == "__main__":
    unittest.main()
