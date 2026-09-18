"""The WTA's own schedule, as JSON, instead of parsing their order-of-play PDF.

    https://api.wtatennis.com/tennis/tournaments/{event_id}/{year}/matches

Public, unauthenticated, and keyed by the SAME id that appears in the PDF URL
we already fetch — wtafiles.wtatennis.com/pdf/draws/2026/1039/OP.pdf is event
1039 — so nothing has to be mapped or looked up.

Per match it states the things a sheet only implies through layout: DateSeq is
the order on court, MatchTimeStamp the time, isEstimatedStartTime whether that
time is a promise or a guess (the "Followed by" case), and RoundID the round.
It also carries seeds, entry types, nationalities and tour player ids, which a
PDF makes us recover from printed text.

WHAT IT DOES NOT GIVE is the court's NAME. Tour events carry CourtID only — 1,
2, 3 — while the Slams carry Venue.name as well. `court_names` lets a caller
supply the mapping it has (learned from a sheet we already ingested, or from
Sofascore, which names courts at every level); without one the court is emitted
as "Court {id}", which is right often enough to be legible and wrong quietly
enough that it must not be trusted for matching.
"""

import logging
from datetime import date, datetime
from typing import Optional
from urllib.request import Request, urlopen

from app.services.oop_parser import COUNTRY_CODES, Match

logger = logging.getLogger(__name__)

BASE = "https://api.wtatennis.com/tennis/tournaments"
# The API answers plain urllib, but a site that fronts Cloudflare can start
# refusing the default python-urllib agent without warning; this is the same
# browser string the rest of the codebase sends.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json",
}
TIMEOUT = 20

# RoundID as the feed states it, in the vocabulary the rest of the site uses.
_ROUNDS = {"F": "F", "S": "SF", "Q": "QF", "1": "R1", "2": "R2", "3": "R3",
           "4": "R4", "5": "R5", "6": "R6", "7": "R7"}


def fetch_matches(event_id: int, year: int) -> list[dict]:
    """Every match the WTA holds for this event — all days, all draws."""
    url = f"{BASE}/{event_id}/{year}/matches"
    with urlopen(Request(url, headers=HEADERS), timeout=TIMEOUT) as r:
        import json
        payload = json.loads(r.read().decode("utf-8"))
    return payload.get("matches") or []


def event_id_from_pdf_url(url: Optional[str]) -> Optional[int]:
    """1039 out of .../pdf/draws/2026/1039/OP.pdf — the id we already hold."""
    import re
    m = re.search(r"/draws/\d{4}/(\d+)/", url or "")
    return int(m.group(1)) if m else None


def _name(first: str, last: str, country: str = "", mark: str = "") -> str:
    """One player in SHEET FORM — "[WC] Gaeul JANG KOR" — because the
    stored name IS the page's rendering, and every reader of it was written
    against the sheet.

    This returned the plain "Alexandra Shubladze", on the reasoning that the
    ingest normalises before matching. Matching is not the only reader. The
    first feed days (2026-09-18, 10:13 UTC) re-stamped forty rows out of sheet
    form and `name_not_sheet_form` convicted every one — rightly: the serve
    path reads a qualifying or doubles row's seed and entry type off the
    name's bracket (`_printed_mark`), so every [2] and [WC] left the page, and
    the readers that find a surname by its capitals (the frontend's
    parseSheetName, `_sheet_surnames`) fell back to the LAST word, which makes
    Beatriz Haddad Maia a Ms Maia. The feed names the surname outright, so
    capitalising it guesses nothing. uso_feed._person builds the same form.

    The COUNTRY goes on the end as the sheet prints it, and only a code we
    know (anything else would be `name_trailing_noncountry`). Without it a
    three-letter surname is the name's last token, and the readers that strip
    a trailing code take it for one: `_fold` would read "Eunhye LEE" as plain
    "eunhye", `_clean_name` "Priscilla HON" as a Honduran called Priscilla.

    A row without both names is a role, not a person, and stays as written.
    """
    first, last = (first or "").strip(), (last or "").strip()
    if not (first and last):
        return first or last
    code = (country or "").strip().upper()
    return " ".join(p for p in (mark, first, last.upper(),
                                code if code in COUNTRY_CODES else "") if p)


def _mark(m: dict, side: str) -> str:
    """The bracket a sheet prints before a side: the seed, else the entry type.

    Once per SIDE, on its first player — a doubles seed belongs to the team,
    and SP Open prints "[2] Valeriya STRAKHOVA UKR" over a bare "Anastasia
    TIKHONOVA"."""
    seed = str(m.get(f"Seed{side}") or "").strip()
    entry = str(m.get(f"EntryType{side}") or "").strip()
    return f"[{seed or entry}]" if (seed or entry) else ""


def _side(m: dict, side: str) -> tuple[list, list]:
    """One side's players and their nations, doubles included (the A2/B2 pair)."""
    names, nations = [], []
    mark = _mark(m, side)
    for suffix in ("", "2"):
        country = (m.get(f"PlayerCountry{side}{suffix}") or "").strip()
        nm = _name(m.get(f"PlayerNameFirst{side}{suffix}"),
                   m.get(f"PlayerNameLast{side}{suffix}"),
                   country, "" if names else mark)
        if nm:
            names.append(nm)
            nations.append(country)
    return names, nations


def _local_hhmm(ts: Optional[str], venue_tz: Optional[str]) -> Optional[str]:
    if not ts or len(ts) < 16:
        return None
    if not venue_tz:
        return ts[11:16]
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo(venue_tz)).strftime("%H:%M")
    except Exception:
        return ts[11:16]


def play_date_of(m: dict, venue_tz: Optional[str] = None) -> Optional[date]:
    """The day the SHEET would file this match under, which is the venue's day.

    The feed stamps UTC, so a Monterrey night match at 01:16 UTC is 19:16 the
    previous evening on site. Taking the UTC date moved every night match onto
    the next day's sheet — the staging run showed it immediately: 4 matches on
    2026-08-29 against the 2 the tournament actually played.
    """
    ts = m.get("MatchTimeStamp")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if venue_tz:
        try:
            from zoneinfo import ZoneInfo
            return dt.astimezone(ZoneInfo(venue_tz)).date()
        except Exception:
            pass
    return dt.date()


def matches_for_day(rows: list[dict], day: date,
                    court_names: Optional[dict] = None,
                    venue_tz: Optional[str] = None) -> list[Match]:
    """The feed's rows for one day, in the shape the schedule ingest takes.

    Ordered by court then DateSeq, so the ingest sees a sheet's reading order
    without having to reconstruct it from positions on a page.
    """
    court_names = court_names or {}
    out = []
    for m in rows:
        if play_date_of(m, venue_tz) != day:
            continue
        cid = str(m.get("CourtID") or "").strip()
        venue = (m.get("Venue") or {}).get("name")
        # The learned mapping (schedule_shadow.learn_courts) is keyed by the
        # court string THIS function emitted when it had no name — "Court 1" —
        # not by the bare id; a lookup by "1" alone found nothing and every
        # promoted day would have read "Court 1" (2026-09-18).
        court = (venue or court_names.get(cid) or court_names.get(f"Court {cid}")
                 or (f"Court {cid}" if cid else ""))
        # VENUE-LOCAL, like the sheet prints. The feed stamps UTC, so a
        # Monterrey night match reads 01:36 raw — tomorrow's date, and an hour
        # nobody played at. Without the zone the raw value is kept rather than
        # guessed at, and the caller can see it is unconverted.
        hhmm = _local_hhmm(m.get("MatchTimeStamp"), venue_tz)
        estimated = bool(m.get("isEstimatedStartTime"))
        names_a, nats_a = _side(m, "A")
        names_b, nats_b = _side(m, "B")
        out.append(Match(
            court=court,
            time=hhmm,
            tour="WTA",
            round=_ROUNDS.get(str(m.get("RoundID") or "").strip()),
            discipline=("doubles" if (m.get("DrawMatchType") or "").upper() == "D"
                        else "singles"),
            # The feed states the time's standing outright, where a sheet makes
            # us read it off wording like "Followed by".
            start_raw=(f"Est. {hhmm}" if estimated and hhmm else hhmm),
            printed_score=(m.get("ScoreString") or None),
            printed_status=(m.get("MatchState") or None),
            side_a=names_a, side_b=names_b,
            nations_a=nats_a, nations_b=nats_b,
        ))
    out.sort(key=lambda x: (x.court, x.time or ""))
    return out


def days_available(rows: list[dict],
                   venue_tz: Optional[str] = None) -> list[date]:
    return sorted({d for d in (play_date_of(m, venue_tz) for m in rows) if d})


# Fields that change while a match is played. They are stripped before the
# day's bytes are stored, for the reason the US Open feed taught us: hashing a
# payload that re-serialises its live score on every publish calls every point
# a schedule revision.
_VOLATILE = ("ScoreString", "ScoreSys", "ResultString", "Winner", "MatchState",
             "LastUpdated", "MatchTimeTotal", "PointA", "PointB", "Serve",
             "NumSets", "Message")


def normalize_day(rows: list[dict], day: date,
                  venue_tz: Optional[str] = None) -> bytes:
    """One day's rows as stable bytes: volatile fields dropped, keys sorted.

    A document per DAY, not per tournament, so a revision to Tuesday does not
    look like a revision to Monday — the same shape the PDF ingest already
    stores and the same one revision counting depends on.
    """
    import json
    keep = []
    for m in rows:
        if play_date_of(m, venue_tz) != day:
            continue
        keep.append({k: v for k, v in sorted(m.items())
                     if k not in _VOLATILE and not str(k).startswith("ScoreSet")
                     and not str(k).startswith("ScoreTb")})
    keep.sort(key=lambda m: (str(m.get("CourtID") or ""),
                             str(m.get("DateSeq") or ""), str(m.get("MatchID") or "")))
    return json.dumps(keep, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_wta_day(doc: bytes, court_names: Optional[dict] = None,
                  venue_tz: Optional[str] = None):
    """(matches, meta) from bytes written by normalize_day — the signature
    ingest_document expects of a parser."""
    import json
    rows = json.loads(doc.decode("utf-8"))
    day = next((d for d in (play_date_of(m, venue_tz) for m in rows) if d), None)
    matches = (matches_for_day(rows, day, court_names=court_names,
                               venue_tz=venue_tz) if day else [])
    return matches, {"source": "wta-api", "day": day.isoformat() if day else None,
                     "count": len(matches)}
