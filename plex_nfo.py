#!/usr/bin/env python3
"""Build spoiler-free Plex NFO files from the existing published ICS snapshots.

The same sources and pre-kickoff freeze policy as filter.py are used.
Only source fields already present in the score-free calendars are read.
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import pathlib
import re
import tarfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from zoneinfo import ZoneInfo

from icalendar import Calendar
from filter import ROOT, start_time
from prem import fetch_prem

UK = ZoneInfo("Europe/London")
ROUND = re.compile(r"\bRound\s+(\d+)\b", re.I)
VERSUS = re.compile(r"\s+(?:vs?\.?|versus)\s+", re.I)


def slug(value):
    value = re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_")
    return value or "Unknown"


def season_year(kickoff):
    local = kickoff.astimezone(UK)
    return local.year if local.month >= 7 else local.year - 1


def xml_bytes(tag, fields):
    root = ET.Element(tag)
    for key, value in fields:
        ET.SubElement(root, key).text = str(value)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def build(config, source_dir, now):
    output = {}
    manifest = {"schema_version": 1, "generated_at": now.isoformat(), "fixtures": []}
    for entry in config["calendars"] + config.get("plex_sources", []):
        if entry.get("type") == "prem":
            calendar = fetch_prem(entry["url"], comp_id=entry["compId"], season=entry["season"])
        else:
            path = source_dir / (entry["slug"] + ".ics")
            if not path.exists():
                raise ValueError(f"Missing source snapshot: {path}")
            calendar = Calendar.from_ical(path.read_bytes())
        grouped = defaultdict(list)
        for event in calendar.walk("VEVENT"):
            kickoff = start_time(event, UK)
            if kickoff is None:
                continue
            # Never publish scores, and never treat an all-day/TBC event as a timed fixture.
            if not isinstance(event.decoded("DTSTART"), dt.datetime):
                continue
            title = str(event.get("SUMMARY", ""))
            teams = VERSUS.split(title, maxsplit=1)
            if len(teams) != 2:
                continue
            description = str(event.get("DESCRIPTION", ""))
            round_match = ROUND.search(description)
            if entry.get("type") == "world-rugby":
                round_no = 1  # No real rounds: one chronological season per calendar year.
                year = kickoff.astimezone(UK).year
            else:
                if not round_match:
                    continue
                round_no = int(round_match.group(1))
                if not 1 <= round_no <= 99:
                    continue
                year = season_year(kickoff)
            grouped[(year, round_no)].append((kickoff.astimezone(dt.timezone.utc), str(event.get("UID", "")), teams, event))
        for (year, round_no), matches in sorted(grouped.items()):
            show = f"{slug(entry['slug'])}_{year}"
            # Keep show identifiers stable and filesystem-safe.
            show_dir = f"{show}/"
            output[show_dir + "tvshow.nfo"] = xml_bytes("tvshow", [
                ("title", f"{entry['name']} {year}" if entry.get("type") == "world-rugby" else f"{entry['name']} {year}-{str((year + 1) % 100).zfill(2)}"),
                ("plot", "Spoiler-free rugby fixture metadata"),
            ])
            # Deterministic order for simultaneous kickoffs.
            matches.sort(key=lambda x: (x[0], slug(x[2][0]), slug(x[2][1]), x[1]))
            if len(matches) > 99:
                raise ValueError(f"More than 99 matches in {show} round {round_no}")
            for number, (kickoff, uid, teams, event) in enumerate(matches, 1):
                home, away = (s.strip() for s in teams)
                prefix = f"{show}-s{round_no:02d}e{number:02d}"
                basename = f"{prefix}-{kickoff.astimezone(UK):%Y%m%d}-{slug(home)}_v_{slug(away)}"
                relative = f"{show_dir}Season_{round_no:02d}/{basename}.nfo"
                venue = str(event.get("LOCATION", "")).strip()
                fields = [
                    ("title", f"{home} vs {away}"),
                    ("season", round_no),
                    ("episode", number),
                    ("aired", kickoff.astimezone(UK).date().isoformat()),
                    ("plot", (str(event.get("DESCRIPTION", entry["name"])) if entry.get("type") == "world-rugby" else f"{entry['name']}, Round {round_no}") + (f". Venue: {venue}" if venue else "")),
                ]
                output[relative] = xml_bytes("episodedetails", fields)
                manifest["fixtures"].append({
                    "id": f"{entry['slug']}:{uid}",
                    "competition": entry["slug"],
                    "season": year,
                    "round": round_no,
                    "episode": number,
                    "kickoff_utc": kickoff.isoformat(),
                    "home": home, "away": away,
                    "nfo": relative,
                })
    if not manifest["fixtures"]:
        raise ValueError("No round-numbered fixtures found; refusing to publish empty metadata")
    manifest["fixtures"].sort(key=lambda x: x["nfo"])
    manifest["files"] = {p: hashlib.sha256(data).hexdigest() for p, data in sorted(output.items())}
    return output, manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=pathlib.Path, default=ROOT / "calendars.json")
    parser.add_argument("--source", type=pathlib.Path, default=ROOT / "docs")
    parser.add_argument("--output", type=pathlib.Path, default=ROOT / "docs")
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    output, manifest = build(json.loads(args.config.read_text()), args.source, now)
    payload = json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / "rugby-metadata.tar.gz"
    # Reproducible archive bytes except for manifest generation timestamp.
    with tarfile.open(archive.with_suffix(".tmp"), "w:gz") as tar:
        for name, data in sorted(output.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        info.mtime = 0
        tar.addfile(info, io.BytesIO(payload))
    archive.with_suffix(".tmp").replace(archive)
    (args.output / "rugby-metadata-manifest.json").write_bytes(payload)
    print(f"Published {len(manifest['fixtures'])} rugby fixtures")


if __name__ == "__main__":
    main()
