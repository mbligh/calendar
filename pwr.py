"""Convert PWR's public fixture JSON into a score-free source calendar.

Only allowlisted fixture fields are copied. Never copy scores, match status,
result descriptions or other potentially spoiler-bearing API fields.
"""
import datetime as dt
import json
import urllib.request
from icalendar import Calendar, Event

def fetch_pwr(url):
    request = urllib.request.Request(url, headers={"User-Agent": "calendar-spoiler-filter/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.load(response)
    fixtures = payload["data"]
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError("PWR API returned no fixtures; preserving existing calendar")
    calendar = Calendar()
    calendar.add("prodid", "-//mbligh/calendar//PWR fixtures//EN")
    calendar.add("version", "2.0")
    for match in fixtures:
        match_id = match["id"]
        kickoff = dt.datetime.fromisoformat(match["dateTime"].replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            raise ValueError(f"PWR fixture {match_id} has timezone-naive kickoff")
        home = match["homeTeam"]["name"]
        away = match["awayTeam"]["name"]
        event = Event()
        event.add("uid", f"pwr-{match_id}@mbligh.github.io")
        event.add("summary", f"{home} vs {away}" + (" (time TBC)" if match.get("tbc") else ""))
        if match.get("tbc"):
            # Provisional API times are not confirmed. Use an all-day placeholder
            # and a conservative midnight cutoff on the fixture's UK date.
            from zoneinfo import ZoneInfo
            event.add("dtstart", kickoff.astimezone(ZoneInfo("Europe/London")).date())
            event.add("dtend", kickoff.astimezone(ZoneInfo("Europe/London")).date() + dt.timedelta(days=1))
        else:
            event.add("dtstart", kickoff)
            event.add("dtend", kickoff + dt.timedelta(hours=2))
        venue = (match.get("venue") or {}).get("name")
        if venue and venue.upper() not in {"TBD", "TBC"}:
            event.add("location", venue)
        event.add("description", "Premiership Women's Rugby" + (f" — Round {match['round']}" if match.get("round") is not None else ""))
        # The PWR API has no reliable last-modified field in the supplied
        # fixture records. The shared merge filter uses saved kickoff cutoffs.
        calendar.add_component(event)
    return calendar
