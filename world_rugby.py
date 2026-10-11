"""World Rugby fixture API adapter: allowlisted, spoiler-free internationals."""
import calendar as monthcal
import datetime as dt
import json
import re
import urllib.parse
import urllib.request

from icalendar import Calendar, Event

API = "https://api.wr-rims-prod.pulselive.com/rugby/v3/match"
COMPETITIONS = {
    "nations": ("MRU", {"Nations Championship"}),
    "mens-intl": ("MRU", {"Men's Internationals"}),
    "womens-intl": ("WRU", {"Women's Internationals", "WXV"}),
}
YEAR_SUFFIX = re.compile(r"\\s+20\\d{2}$")


def competition_base(label):
    return YEAR_SUFFIX.sub("", label or "")


def months(now, count=18):
    # Include last month for updates, and enough future months for next season.
    start = now.year * 12 + now.month - 2
    for i in range(count):
        index = start + i
        year, month = divmod(index, 12)
        month += 1
        yield dt.date(year, month, 1), dt.date(year, month, monthcal.monthrange(year, month)[1])


def request_page(start, end, page):
    query = urllib.parse.urlencode({
        "states": "U,UP,L,CC,C",
        "pageSize": 100,
        "page": page,
        "sort": "asc",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
    })
    req = urllib.request.Request(API + "?" + query, headers={
        "User-Agent": "calendar-spoiler-filter/1.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


def convert_match(match):
    teams = match.get("teams") or []
    if len(teams) != 2 or not all(t.get("name") for t in teams):
        return None
    millis = (match.get("time") or {}).get("millis")
    if millis is None:
        return None
    kickoff = dt.datetime.fromtimestamp(millis / 1000, tz=dt.timezone.utc)
    event = Event()
    event.add("uid", f"world-rugby-{match['matchId']}@mbligh.github.io")
    event.add("summary", f"{teams[0]['name']} vs {teams[1]['name']}")
    event.add("dtstart", kickoff)
    event.add("dtend", kickoff + dt.timedelta(hours=2))
    venue = (match.get("venue") or {}).get("name")
    if venue:
        event.add("location", venue)
    event.add("description", match["competition"])
    return event


def fetch_world_rugby(group, now=None):
    if group not in COMPETITIONS:
        raise ValueError(f"Unknown World Rugby group: {group}")
    sport, allowed = COMPETITIONS[group]
    today = (now or dt.datetime.now(dt.timezone.utc)).date()
    matches = {}
    for start, end in months(today):
        page = 0
        while True:
            payload = request_page(start, end, page)
            info = payload["pageInfo"]
            for match in payload["content"]:
                if match.get("sport") != sport:
                    continue
                if competition_base(match.get("competition")) not in allowed:
                    continue
                match_id = match.get("matchId")
                if match_id:
                    matches[match_id] = match
            page += 1
            if page >= info["numPages"]:
                break
    if not matches:
        raise ValueError(f"No {group} fixtures returned; preserving previous calendar")
    result = Calendar()
    result.add("prodid", "-//mbligh/calendar//World Rugby fixtures//EN")
    result.add("version", "2.0")
    for match in sorted(matches.values(), key=lambda m: (m["time"]["millis"], m["matchId"])):
        event = convert_match(match)
        if event is not None:
            result.add_component(event)
    return result
