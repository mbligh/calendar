#!/usr/bin/env python3
"""Publish spoiler-free mirrors of public Google ICS calendars.

Existing events are frozen at their last accepted DTSTART. A source update
whose LAST-MODIFIED/DTSTAMP is later than kickoff is never accepted, even if
the updater first encounters it after the match. Missing timestamps cannot
prove safety; an event is only updated while its saved kickoff is future.
"""
import argparse
import datetime as dt
import json
import pathlib
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

ROOT = pathlib.Path(__file__).resolve().parent
UTC = dt.timezone.utc


def start_time(event, default_tz):
    if "DTSTART" not in event:
        return None
    value = event.decoded("DTSTART")
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=default_tz) if value.tzinfo is None else value
    return dt.datetime.combine(value, dt.time.min, tzinfo=default_tz)


def event_key(event):
    uid = str(event.get("UID", ""))
    recurrence = event.get("RECURRENCE-ID")
    return (uid, str(recurrence.to_ical()) if recurrence else "")


def modified_time(event):
    values = []
    for prop in ("LAST-MODIFIED", "DTSTAMP"):
        if prop in event:
            value = event.decoded(prop)
            if isinstance(value, dt.datetime):
                values.append(value if value.tzinfo else value.replace(tzinfo=UTC))
    return max(values) if values else None


def events(calendar):
    return {event_key(c): c for c in calendar.walk("VEVENT") if event_key(c)[0]}


def read_existing(path):
    if not path.exists():
        return None
    return Calendar.from_ical(path.read_bytes())


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "calendar-spoiler-filter/1.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        data = response.read()
    cal = Calendar.from_ical(data)
    if not any(c.name == "VEVENT" for c in cal.walk()):
        raise ValueError("No VEVENT entries found; refusing to replace existing output")
    return cal


def merge(source, previous, now, tz, name):
    old = events(previous) if previous else {}
    current = events(source)
    accepted = dict(old)
    for key, incoming in current.items():
        start = start_time(incoming, tz)
        if start is None:
            continue
        saved = old.get(key)
        cutoff = start_time(saved, tz) if saved is not None else start
        # Never import past events for the first time, or modify an event
        # after its previously accepted kickoff, even if source reschedules it.
        if cutoff <= now:
            continue
        modified = modified_time(incoming)
        # Reject a source revision timestamped after the saved kickoff.
        # For new events, use their source kickoff as the cutoff.
        if modified is not None and modified > cutoff:
            continue
        accepted[key] = incoming

    result = Calendar()
    result.add("prodid", "-//mbligh/calendar//Spoiler-free calendar//EN")
    result.add("version", "2.0")
    result.add("x-wr-calname", name + " (No Spoilers)")
    result.add("x-wr-timezone", str(tz))
    # Retain timezone definitions for event DTSTART with TZID parameters.
    # The previous output may reference older timezone definitions.
    seen = set()
    for cal in (source, previous):
        if cal is None:
            continue
        for component in cal.subcomponents:
            if component.name == "VTIMEZONE":
                tzid = str(component.get("TZID", ""))
                if tzid not in seen:
                    result.add_component(component)
                    seen.add(tzid)
    for key in sorted(accepted):
        result.add_component(accepted[key])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=pathlib.Path, default=ROOT / "calendars.json")
    parser.add_argument("--output", type=pathlib.Path, default=ROOT / "docs")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    tz = ZoneInfo(config.get("timezone", "UTC"))
    now = dt.datetime.now(UTC)
    args.output.mkdir(parents=True, exist_ok=True)
    failures = 0
    for entry in config["calendars"]:
        slug = entry["slug"]
        path = args.output / (slug + ".ics")
        url = entry.get("url") or ("https://calendar.google.com/calendar/ical/" + urllib.parse.quote(entry["id"], safe="") + "/public/basic.ics")
        try:
            source = fetch(url)
            previous = read_existing(path)
            result = merge(source, previous, now, tz, entry["name"])
            payload = result.to_ical()
            if not path.exists() or path.read_bytes() != payload:
                path.write_bytes(payload)
                print(f"{slug}: updated ({len(events(result))} events)")
            else:
                print(f"{slug}: unchanged ({len(events(result))} events)")
        except Exception as exc:
            failures += 1
            print(f"{slug}: ERROR: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
