"""US Open schedule feed — the Slam's own JSON, shaped like a sheet.

The tours' file hosts have never carried the US Open's order of play:
wtafiles 404s and protennislive serves a one-page "-Tournament Information
Not Yet Available-" placeholder (2025's STILL says that, so it is not a
matter of waiting). The tournament publishes its schedule itself, as IBM
slam-site JSON:

    /en_US/scores/feeds/{year}/schedule/scheduleDays.json   — the day index
    /en_US/scores/feeds/{year}/schedule/schedule{N}.json    — one day's sheet

This module turns one day's feed into exactly what oop_parser.parse_pdf
returns — a list of its Match objects plus a meta dict — so ingest_document
can reconcile it into schedule_entries with the machinery it already has:
pairing keys, revision detection, change records, expected-start estimates.

NORMALIZE BEFORE HASHING. ingest_document's revision detection is a sha256
of the document bytes, which for a PDF changes only when the sheet does. The
feed embeds live scores, statuses and durations that move every few minutes;
hashed raw, every refresh would mint a new "revision". normalize() strips
the volatile fields and serializes canonically, so the digest changes only
when the SCHEDULE changes — same semantics as a PDF revision.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.oop_parser import Match

FEED_DAYS = "https://www.usopen.org/en_US/scores/feeds/{year}/schedule/scheduleDays.json"
WEBVIEW_DAY = "https://www.usopen.org/en_US/scores/schedule/schedule{day}.html"

# Akamai in front of usopen.org refuses non-browser agents (the app's own
# UA string got connection resets), so this source is fetched as a browser.
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}

_TZ = ZoneInfo("America/New_York")

# eventCode -> (tour, discipline). Qualifying is what this exists for; the
# main-draw and doubles codes are here so the same path keeps working when
# those days release. Anything not listed (exhibitions, legends, juniors)
# is not on our draws and is skipped.
_EVENTS = {
    "MQ": ("ATP", "singles"), "WQ": ("WTA", "singles"),
    "MS": ("ATP", "singles"), "WS": ("WTA", "singles"),
    "MD": ("ATP", "doubles"), "WD": ("WTA", "doubles"),
    "XD": (None, "doubles"),
}

# Volatile per-match fields: results and clocks, not schedule. A revision is
# a change to what is PLANNED — court, order, slot, pairing, round.
_VOLATILE = {"scores", "shortScore", "duration", "status", "statusCode"}


# "Fan Week Day 3: Tue, Aug 25" / "Day 3: Tue, Sept 1" — the printed label is
# the one field that states the sheet's own day. It has to be, because `epoch`
# does NOT: day 3's epoch decoded to Aug 24 while its label said Tue, Aug 25,
# and trusting it filed today's sheet under yesterday's date — where the
# dedupe machinery then treated it as a REVISION of yesterday's sheet.
_DAY_RE = re.compile(r"\b([A-Z][a-z]{2,3})\.?\s+(\d{1,2})\b")
_MONTHS = {m[:3].lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}


def play_date_of(event_day: dict, year: int):
    """The sheet's own day, from its printed label; epoch only as fallback."""
    for text in (event_day.get("messageShort"), event_day.get("message")):
        for mon, dd in _DAY_RE.findall(text or ""):
            m = _MONTHS.get(mon[:3].lower())
            if m:
                return date(year, m, int(dd))
    epoch = event_day.get("epoch")
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=_TZ).date()


def normalize(raw: bytes) -> bytes:
    """Canonical bytes for revision hashing: volatile fields out, keys sorted."""
    d = json.loads(raw)
    d.pop("lastUpdated", None)
    for court in d.get("courts") or []:
        for m in court.get("matches") or []:
            for k in _VOLATILE:
                m.pop(k, None)
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


def _team_name(team: dict) -> str | None:
    """One side entry in the sheet's own vocabulary: 'A. Sabalenka' for a
    singles slot, 'K. Siniakova/H. Patten' for a pair."""
    a = team.get("displayNameA")
    b = team.get("displayNameB")
    if a and b:
        return f"{a}/{b}"
    return a or b


def parse_uso_day(raw: bytes):
    """parse_pdf's contract, from one schedule{N}.json: (matches, meta)."""
    d = json.loads(raw)
    matches: list[Match] = []
    for court in d.get("courts") or []:
        court_name = court.get("courtName") or ""
        court_time = court.get("time")
        for order, m in enumerate(court.get("matches") or [], start=1):
            ev = _EVENTS.get(m.get("eventCode"))
            if ev is None:
                continue
            tour, discipline = ev
            side_a = [n for n in (_team_name(t) for t in m.get("team1") or []) if n]
            side_b = [n for n in (_team_name(t) for t in m.get("team2") or []) if n]
            # A slot the feed has not filled in yet (tomorrow's R2 before
            # today's winners are known) settles on a later refresh; until
            # then there is nothing to pair it to.
            if not side_a or not side_b:
                continue
            not_before = m.get("notBefore")
            if not_before:
                start_raw, slot_time = f"Not Before {not_before}", not_before
            elif m.get("order", order) == 1 or order == 1:
                start_raw, slot_time = f"Starts At {court_time}", court_time
            else:
                start_raw, slot_time = m.get("conjunction") or "Followed By", None
            matches.append(Match(
                court=court_name,
                time=slot_time,
                tour=tour,
                round=m.get("roundNameShort") or m.get("roundName"),
                discipline=discipline,
                start_raw=start_raw,
                printed_score=m.get("shortScore"),
                printed_status=m.get("status"),
                side_a=side_a,
                side_b=side_b,
            ))
    meta = {"date_line": d.get("displayDate") or d.get("shortDate"), "kind": "ok"}
    return matches, meta
