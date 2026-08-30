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

from app.services.oop_parser import Match

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


def _name(first: str, last: str) -> str:
    """'Nikola Bartunkova' — the sheet's own rendering is SURNAME in caps, but
    the ingest normalises before matching, so the plain form is enough."""
    return " ".join(p for p in ((first or "").strip(), (last or "").strip()) if p)


def _side(m: dict, side: str) -> tuple[list, list]:
    """One side's players and their nations, doubles included (the A2/B2 pair)."""
    names, nations = [], []
    for suffix in ("", "2"):
        nm = _name(m.get(f"PlayerNameFirst{side}{suffix}"),
                   m.get(f"PlayerNameLast{side}{suffix}"))
        if nm:
            names.append(nm)
            nations.append((m.get(f"PlayerCountry{side}{suffix}") or "").strip())
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


def play_date_of(m: dict) -> Optional[date]:
    ts = m.get("MatchTimeStamp")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    except ValueError:
        return None


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
        if play_date_of(m) != day:
            continue
        cid = str(m.get("CourtID") or "").strip()
        venue = (m.get("Venue") or {}).get("name")
        court = venue or court_names.get(cid) or (f"Court {cid}" if cid else "")
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


def days_available(rows: list[dict]) -> list[date]:
    return sorted({d for d in (play_date_of(m) for m in rows) if d})


# Fields that change while a match is played. They are stripped before the
# day's bytes are stored, for the reason the US Open feed taught us: hashing a
# payload that re-serialises its live score on every publish calls every point
# a schedule revision.
_VOLATILE = ("ScoreString", "ScoreSys", "ResultString", "Winner", "MatchState",
             "LastUpdated", "MatchTimeTotal", "PointA", "PointB", "Serve",
             "NumSets", "Message")


def normalize_day(rows: list[dict], day: date) -> bytes:
    """One day's rows as stable bytes: volatile fields dropped, keys sorted.

    A document per DAY, not per tournament, so a revision to Tuesday does not
    look like a revision to Monday — the same shape the PDF ingest already
    stores and the same one revision counting depends on.
    """
    import json
    keep = []
    for m in rows:
        if play_date_of(m) != day:
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
    day = next((d for d in (play_date_of(m) for m in rows) if d), None)
    matches = (matches_for_day(rows, day, court_names=court_names,
                               venue_tz=venue_tz) if day else [])
    return matches, {"source": "wta-api", "day": day.isoformat() if day else None,
                     "count": len(matches)}
