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
    "XD": (None, "mixed"),
}

# Volatile per-match fields: results and clocks, not schedule. A revision is
# a change to what is PLANNED — court, order, slot, pairing, round.
_VOLATILE = {"scores", "shortScore", "duration", "status", "statusCode"}

# Entrants per event, for translating the feed's positional rounds ("R2",
# roundCode 2) into the app's size-based vocabulary (R64, QF...). The feed
# numbers rounds from 1 however big the draw is, so its R2 means different
# things in different events — in the 16-team mixed doubles it is a
# quarterfinal. Slam draw sizes are fixed by format: 128 singles main,
# 128 qualifying (3 rounds to qualify), 64 doubles, 16 mixed (2026 format).
_DRAW_SIZE = {"MS": 128, "WS": 128, "MD": 64, "WD": 64, "XD": 16}


def _round_label(event_code: str, m: dict) -> str | None:
    """The feed's round, translated into the app's own vocabulary."""
    if event_code in ("MQ", "WQ"):
        code = str(m.get("roundCode") or "").strip()
        if code.isdigit():
            return f"Q{code}"
    name = (m.get("roundName") or "").lower()
    if "final" in name and "semi" not in name and "quarter" not in name:
        return "F"
    if "semi" in name:
        return "SF"
    if "quarter" in name:
        return "QF"
    code = str(m.get("roundCode") or "").strip()
    size = _DRAW_SIZE.get(event_code)
    if size and code.isdigit():
        players = size >> (int(code) - 1)
        if players >= 16:
            return f"R{players}"
        return {8: "QF", 4: "SF", 2: "F"}.get(players)
    return m.get("roundNameShort") or m.get("roundName")


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


async def fetch_main_draw_window(year: int):
    """(day 1, last day) of the MAIN DRAW, from the tournament's day index.

    The index labels qualifying days "Fan Week Day N" and main-draw days
    plainly "Day N", so the first plain day is day one of the event proper.
    This is the authority on when the tournament starts: the 2026 main draw
    opens Sunday 30 August, a day earlier than the Monday every week-based
    guess assumes, and the pick deadline is derived from that date.
    """
    import httpx
    async with httpx.AsyncClient(timeout=30, headers=BROWSER_HEADERS) as client:
        r = await client.get(FEED_DAYS.format(year=year))
        r.raise_for_status()
        days = r.json().get("eventDays") or []
    main = []
    for e in days:
        label = (e.get("messageShort") or e.get("message") or "")
        if "fan week" in label.lower():
            continue
        pd = play_date_of(e, year)
        if pd is not None and re.match(r"^Day\s+\d+", label.strip()):
            main.append(pd)
    if not main:
        return None, None
    return min(main), max(main)


def normalize(raw: bytes) -> bytes:
    """Canonical bytes for revision hashing: volatile fields out, keys sorted."""
    d = json.loads(raw)
    d.pop("lastUpdated", None)
    for court in d.get("courts") or []:
        for m in court.get("matches") or []:
            for k in _VOLATILE:
                m.pop(k, None)
            # `won` flips as matches finish — a result, not a schedule. Left
            # in, every completed match minted a phantom "revision" of the
            # day (three identical Aug 25 docs in an afternoon).
            for side in ("team1", "team2"):
                for t in m.get(side) or []:
                    t.pop("won", None)
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


def _person(team: dict, suffix: str) -> str | None:
    """One player in SHEET FORM — full given name, capitalised surname
    ("Aryna SABALENKA"), because that is the shape every downstream consumer
    expects: the invariants check for it (name_not_sheet_form,
    name_abbreviated_given), and _sheet_form/_match_tokens resolve against
    it. The feed hands the parts over separately, so build the form rather
    than passing its abbreviated displayName through."""
    fn = team.get(f"firstName{suffix}")
    ln = team.get(f"lastName{suffix}")
    if fn and ln:
        return f"{fn} {ln.upper()}"
    d = team.get(f"displayName{suffix}")
    if not d:
        return None
    given, _, rest = d.partition(" ")
    return f"{given} {rest.upper()}" if rest else d


def _side_names(teams: list, doubles: bool) -> tuple[list[str], list, bool]:
    """A side as the sheet prints it, with each player's IOC code and whether
    the side is still a CHOICE.

    One team dict is a settled side: one name in singles, two rows in doubles
    (never one 'A/B' string — doubles_side_not_two exists precisely because a
    pair collapsed into one row breaks every per-player join).

    SEVERAL team dicts are the feed's "winner of X / Y": tomorrow's Q2 slot
    lists both candidates before today's match decides it. That is the PDF's
    own "BOUZKOVA or JOVIC" case, so it maps to the parser's alternatives
    convention — one entry per candidate, tbd set, and a doubles candidate
    named as its slash-joined pair (how _side_size tells a pair from a
    choice). resolve_settled_alternatives collapses it once the bracket
    knows. A null IOC code is the feed's own statement and stays null."""
    teams = teams or []
    if doubles and len(teams) == 1:
        names, nations = [], []
        for suffix in ("A", "B"):
            n = _person(teams[0], suffix)
            if n:
                names.append(n)
                nations.append(teams[0].get(f"nation{suffix}") or None)
        return names, nations, False
    names, nations = [], []
    for t in teams:
        if doubles:
            a, b = _person(t, "A"), _person(t, "B")
            n = f"{a}/{b}" if a and b else (a or b)
            nat = None
        else:
            n = _person(t, "A")
            nat = t.get("nationA") or None
        if n:
            names.append(n)
            nations.append(nat)
    return names, nations, len(names) > 1


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
            doubles = discipline in ("doubles", "mixed")
            side_a, nations_a, tbd_a = _side_names(m.get("team1"), doubles)
            side_b, nations_b, tbd_b = _side_names(m.get("team2"), doubles)
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
                tbd=tbd_a or tbd_b,
                tbd_side=("ab" if tbd_a and tbd_b
                          else "a" if tbd_a else "b" if tbd_b else None),
                round=_round_label(m.get("eventCode"), m),
                discipline=discipline,
                start_raw=start_raw,
                printed_score=m.get("shortScore"),
                printed_status=m.get("status"),
                side_a=side_a,
                side_b=side_b,
                nations_a=nations_a,
                nations_b=nations_b,
            ))
    meta = {"date_line": d.get("displayDate") or d.get("shortDate"), "kind": "ok"}
    return matches, meta
