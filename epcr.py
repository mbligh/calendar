"""Spoiler-free Investec Champions Cup fixtures from EPCR's broadcaster JSON."""
import datetime as dt
import json
import urllib.request

from icalendar import Calendar, Event

ROUNDS = {"R16": 5, "QF": 6, "SF": 7, "TF": 8}
TOURNAMENT = "Investec Champions Cup"


def convert_epcr(payload):
    if not isinstance(payload.get("matches"), list) or not payload["matches"]:
        raise ValueError("EPCR feed has no matches")
    if str(payload.get("seasonId")) != "202601":
        raise ValueError("Unexpected EPCR season")
    matches = [m for m in payload["matches"] if m.get("tournament") == TOURNAMENT]
    if not matches:
        raise ValueError("No Champions Cup fixtures found")
    calendar = Calendar()
    calendar.add("prodid", "-//mbligh/calendar//Rugby EU//EN")
    calendar.add("version", "2.0")
    seen = set()
    for match in matches:
        uid = str(match["id"])
        if uid in seen:
            raise ValueError(f"Duplicate EPCR fixture {uid}")
        seen.add(uid)
        raw_round = str(match["round"])
        number = ROUNDS.get(raw_round)
        if number is None:
            if not raw_round.isdecimal() or not 1 <= int(raw_round) <= 4:
                raise ValueError(f"Unknown EPCR round {raw_round}")
            number = int(raw_round)
        kickoff = dt.datetime.fromisoformat(match["dateTime"].replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            raise ValueError(f"Naive kickoff for {uid}")
        home, away = str(match["homeTeam"]).strip(), str(match["awayTeam"]).strip()
        if not home or not away:
            raise ValueError(f"Missing teams for {uid}")
        event = Event()
        event.add("uid", f"{uid}@mbligh.github.io")
        event.add("summary", f"{home} vs {away}")
        event.add("dtstart", kickoff)
        event.add("dtend", kickoff + dt.timedelta(hours=2))
        event.add("description", f"{TOURNAMENT} — Round {number}")
        venue = str(match.get("venue") or "").strip()
        if venue and venue.upper() not in {"TBC", "TBD"}:
            event.add("location", venue)
        # Broadcast coverage is not needed; never propagate unrelated fields.
        calendar.add_component(event)
    return calendar


def fetch_epcr(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": "calendar-spoiler-filter/1.0", "Accept": "application/json"
    })
    with urllib.request.urlopen(request, timeout=45) as response:
        return convert_epcr(json.load(response))
