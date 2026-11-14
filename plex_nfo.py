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



def rugby_observations(path):
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("source") != "rugbypass" or not isinstance(data.get("records"), list):
        raise ValueError("Invalid RugbyPass catalogue JSON")
    return data["records"]


def normal_team(value):
    aliases = {"allblacks": "newzealand", "wallabies": "australia",
               "springboks": "southafrica"}
    key = re.sub(r"[^a-z0-9]", "", value.casefold())
    return aliases.get(key, key)


def replay_observation(record):
    if record.get("type") != "VOD":
        return None
    parts = [p.strip() for p in record.get("title", "").replace("\xa0", " ").split("|")]
    if len(parts) < 3 or "full match replay" not in parts[-1].lower():
        return None
    teams = VERSUS.split(parts[0], maxsplit=1)
    round_name = next((ROUND.search(p) for p in parts if ROUND.search(p)), None)
    comp = next((p for p in parts if "nations championship" in p.casefold()), None)
    if len(teams) != 2 or round_name is None or not comp:
        return None
    pub = record.get("publishedDate")
    if not isinstance(pub, str):
        return None
    try:
        pub_date = dt.datetime.fromisoformat(pub.replace("Z", "+00:00")).date()
    except ValueError:
        return None
    return (normal_team(teams[0]), normal_team(teams[1]), pub_date,
            int(round_name.group(1)), str(record["id"]))


def resolve_round(kickoff, home, away, observations):
    # Match replay publication dates to fixtures, allowing a one-day calendar
    # difference and preserving competition/team identity. Never pick ties.
    date = kickoff.date()
    candidates = [r for r in observations if r[0] == normal_team(home) and
                  r[1] == normal_team(away) and
                  abs((r[2] - date).days) <= 1]
    if len({(r[3], r[4]) for r in candidates}) == 1:
        return candidates[0][3], candidates[0][4]
    return None, None


def build(config, source_dir, now):
    output = {}
    manifest = {"schema_version": 2, "generated_at": now.isoformat(), "fixtures": []}
    observations = [r for record in rugby_observations(source_dir.parent / "data" / "rugbypass.json")
                    if (r := replay_observation(record)) is not None]
    previous = source_dir / "rugby-metadata-manifest.json"
    old_assignments = {}
    if previous.exists():
        old_data = json.loads(previous.read_text(encoding="utf-8"))
        if old_data.get("schema_version") == 2:
            old_assignments = {f["id"]: f for f in old_data.get("fixtures", [])}
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
                year = kickoff.astimezone(UK).year
                if entry["slug"] == "rugby-nations":
                    assigned = old_assignments.get(f"{entry['slug']}:{event.get('UID', '')}")
                    replay_round, _ = resolve_round(kickoff, teams[0], teams[1], observations)
                    round_no = (assigned["round"] if assigned and
                                assigned.get("episode") is not None and
                                assigned.get("round") is not None else replay_round)
                    if round_no is None:
                        # Publish the fixture without fabricating a round/episode.
                        manifest["fixtures"].append({
                            "id": f"{entry['slug']}:{event.get('UID', '')}",
                            "competition": entry["slug"], "season": year,
                            "round": None, "episode": None,
                            "kickoff_utc": kickoff.astimezone(dt.timezone.utc).isoformat(),
                            "home": teams[0].strip(), "away": teams[1].strip(),
                            "venue": str(event.get("LOCATION", "")).strip(),
                            "rugbypass_id": None, "nfo": None,
                        })
                        continue
                else:
                    round_no = 1
            else:
                if not round_match:
                    continue
                round_no = int(round_match.group(1))
                if not 1 <= round_no <= 99:
                    continue
                year = season_year(kickoff)
            grouped[(year, round_no)].append((kickoff.astimezone(dt.timezone.utc), str(event.get("UID", "")), teams, event))
        for (year, round_no), matches in sorted(grouped.items()):
            show = {"rugby-nations": "Rugby_Nations"}.get(entry["slug"], slug(entry["slug"]))
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
            used = {f["episode"] % 100 for f in old_assignments.values()
                    if f.get("competition") == entry["slug"] and f.get("season") == year
                    and f.get("round") == round_no and isinstance(f.get("episode"), int)}
            next_number = 1
            for kickoff, uid, teams, event in matches:
                home, away = (s.strip() for s in teams)
                fixture_id = f"{entry['slug']}:{uid}"
                prior = old_assignments.get(fixture_id)
                if prior and prior.get("round") == round_no and prior.get("episode") is not None:
                    number = prior["episode"] % 100
                else:
                    while next_number in used:
                        next_number += 1
                    number = next_number
                    used.add(number)
                episode = round_no * 100 + number
                prefix = f"{show}-s{year}e{episode:03d}"
                basename = f"{prefix}-{slug(home)}_v_{slug(away)}_{kickoff.astimezone(UK):%Y%m%d}"
                relative = f"{show_dir}Season_{year}/{basename}.nfo"
                venue = str(event.get("LOCATION", "")).strip()
                fields = [
                    ("title", f"{home} vs {away}"),
                    ("season", year),
                    ("episode", episode),
                    ("aired", kickoff.astimezone(UK).date().isoformat()),
                    ("plot", (str(event.get("DESCRIPTION", entry["name"])) if entry.get("type") == "world-rugby" else f"{entry['name']}, Round {round_no}") + (f". Venue: {venue}" if venue else "")),
                ]
                output[relative] = xml_bytes("episodedetails", fields)
                manifest["fixtures"].append({
                    "id": f"{entry['slug']}:{uid}",
                    "competition": entry["slug"],
                    "season": year,
                    "round": round_no,
                    "episode": episode,
                    "kickoff_utc": kickoff.isoformat(),
                    "home": home, "away": away,
                    "venue": venue,
                    "rugbypass_id": (
                        resolve_round(kickoff, home, away, observations)[1]
                        or (prior.get("rugbypass_id") if prior else None)
                    ) if entry["slug"] == "rugby-nations" else None,
                    "nfo": relative,
                })
    if not manifest["fixtures"]:
        raise ValueError("No round-numbered fixtures found; refusing to publish empty metadata")
    manifest["fixtures"].sort(key=lambda x: (x["competition"], x["season"],
                                               x["kickoff_utc"], x["id"]))
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
