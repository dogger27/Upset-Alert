"""The ATP's order of play, from Sofascore, because the ATP publishes none.

The WTA hands out its schedule as JSON and the Slams have their own feeds; the
ATP has neither. atptour.com is behind Cloudflare, api.protennislive.com answers
401, and there is no structured sibling beside the op.pdf we currently parse —
so for ATP events the choice is the PDF or a third party.

Sofascore is that third party, and we already run it for live scores. What it
gives that the WTA feed does not is the COURT NAME at every level: 30/30 named
at Winston-Salem, 29/30 at Monterrey, matching the sheets' own wording
("Stadium", "Court 2", "Grandstand"). What it lacks is the sheet's ordering
vocabulary — there is no "third match" field and no "followed by" flag. Instead
every match carries an estimated start, staggered per court, which encodes the
same order less explicitly. That is enough to place a match on a court in
sequence, which is what the page renders.
"""

import logging
from datetime import date, datetime
from typing import Optional

from app.services.oop_parser import Match

logger = logging.getLogger(__name__)

# "Round of 128" is how Sofascore says R128; the rest of the site says R128.
_ROUND_NAMES = {
    "final": "F", "semifinal": "SF", "quarterfinal": "QF",
    "round of 16": "R16", "round of 32": "R32", "round of 64": "R64",
    "round of 128": "R128", "qualification round 1": "Q1",
    "qualification round 2": "Q2", "qualification round 3": "Q3",
    "qualification": "Q",
}

# Live-score fields are stripped before the day's bytes are hashed: the feed
# re-serialises them constantly and every point would read as a revision.
_KEEP = ("id", "startTimestamp", "roundInfo", "venue", "homeTeam", "awayTeam",
         "homeTeamSeed", "awayTeamSeed", "slug")


async def fetch_events(tournament_id: int, season_id: int,
                       direction: str = "next", pages: int = 3) -> list[dict]:
    """Scheduled (or recent) events for one Sofascore tournament season."""
    from app.services.sofascore import _get, SofascoreNotFound
    out = []
    for page in range(pages):
        try:
            payload = await _get(
                f"/unique-tournament/{tournament_id}/season/{season_id}"
                f"/events/{direction}/{page}")
        except SofascoreNotFound:
            # RUNNING OUT OF PAGES IS A 404 HERE, not an error — the module's
            # own rule: "a 404 is an ANSWER, not a refusal". Sofascore has no
            # empty last page, it simply stops having one, so this is the
            # normal end of the walk rather than something to report.
            break
        events = (payload or {}).get("events") or []
        if not events:
            break
        out.extend(events)
    return out


def play_date_of(e: dict, venue_tz: Optional[str] = None) -> Optional[date]:
    ts = e.get("startTimestamp")
    if not ts:
        return None
    dt = datetime.fromtimestamp(ts, tz=_tz(venue_tz))
    return dt.date()


def _tz(venue_tz: Optional[str]):
    from datetime import timezone
    if not venue_tz:
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(venue_tz)
    except Exception:
        return timezone.utc


def _surname_last(part: str) -> str:
    """"Bhambri Y" -> "Y Bhambri", so the surname ends the string.

    Sofascore writes a SINGLES player as "Daniel Altmaier" but a DOUBLES team
    as "Bhambri Y / Venus M" — surname first, initial after. Everything
    downstream takes the last token for the surname, so the doubles form
    silently matched on the initial: the staging run found 55 of Winston-Salem's
    75 matches and every miss was a pair. Flipping the two puts both forms in
    the same shape.
    """
    toks = part.split()
    # The INITIAL is what identifies this form, wherever the surname ends —
    # "Van de Zandschulp B" is the same shape as "Bhambri Y" and was missed by
    # a rule that only looked at two-token names.
    if len(toks) > 1 and len(toks[-1].rstrip(".")) == 1 and toks[-1].rstrip(".").isalpha():
        return " ".join([toks[-1]] + toks[:-1])
    return part


def _names(team: dict) -> tuple[list, list]:
    """A doubles team is one string — "Krajicek A. / Mektic N." — so the pair
    is split back apart, and a singles player is simply a list of one."""
    name = (team or {}).get("name") or ""
    parts = [_surname_last(p.strip()) for p in name.split("/") if p.strip()]
    country = (((team or {}).get("country") or {}).get("alpha3") or "").strip()
    # Sofascore states one country per TEAM, so a mixed-nationality pair would
    # be mislabelled; better to leave both blank than to assert the wrong flag.
    nations = [country] * len(parts) if len(parts) == 1 else [""] * len(parts)
    return parts, nations


def normalize_day(events: list[dict], day: date,
                  venue_tz: Optional[str] = None) -> bytes:
    import json
    keep = []
    for e in events:
        if play_date_of(e, venue_tz) != day:
            continue
        keep.append({k: e.get(k) for k in _KEEP if e.get(k) is not None})
    keep.sort(key=lambda x: (str(((x.get("venue") or {}).get("name")) or ""),
                             x.get("startTimestamp") or 0, x.get("id") or 0))
    return json.dumps(keep, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_sofa_day(doc: bytes, venue_tz: Optional[str] = None,
                   discipline: str = "singles"):
    """(matches, meta) — the signature ingest_document expects of a parser."""
    import json
    events = json.loads(doc.decode("utf-8"))
    day = next((d for d in (play_date_of(e, venue_tz) for e in events) if d), None)
    out = []
    for e in events:
        court = ((e.get("venue") or {}).get("name") or "").strip()
        ts = e.get("startTimestamp")
        hhmm = datetime.fromtimestamp(ts, tz=_tz(venue_tz)).strftime("%H:%M") if ts else None
        rname = ((e.get("roundInfo") or {}).get("name") or "").strip().lower()
        a, na = _names(e.get("homeTeam") or {})
        b, nb = _names(e.get("awayTeam") or {})
        out.append(Match(
            court=court,
            time=hhmm,
            tour="ATP",
            round=_ROUND_NAMES.get(rname),
            discipline=discipline,
            # Sofascore's times are ALL estimates once a court is under way, and
            # it never says which are fixed. Marking them all estimated is the
            # honest reading and keeps a reader from trusting a minute value.
            start_raw=(f"Est. {hhmm}" if hhmm else None),
            side_a=a, side_b=b, nations_a=na, nations_b=nb,
        ))
    out.sort(key=lambda m: (m.court, m.time or ""))
    return out, {"source": "sofascore", "day": day.isoformat() if day else None,
                 "count": len(out)}


def days_available(events: list[dict], venue_tz: Optional[str] = None) -> list[date]:
    return sorted({d for d in (play_date_of(e, venue_tz) for e in events) if d})
