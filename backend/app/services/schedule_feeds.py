"""THE SCHEDULE FROM THE FEEDS, WITH THE PDF AS THE LAST RESORT (owner, 2026-09-18).

The order of play used to be a PDF the tours overwrite at a fixed path,
parsed by pdfplumber — and nearly every self-heal wake this month was that
parse. The structured sources we had been running beside it for three weeks
agree with it (schedule_shadow: 909 of 977 matches, every miss the half of a
combined sheet a single feed cannot hold), so they are the schedule now:

    women's draw   -> the WTA's own JSON (wta_feed): order on court, time,
                      fixed-or-estimated, round, seeds, nations, ids; the
                      court's NAME only through the mapping the shadow learned
    men's draw     -> Sofascore (sofa_schedule): named courts, estimated
                      starts staggered per court, singles and doubles
    a Slam         -> its own feed (uso_feed), handled before this module
    nothing at all -> the PDF, fetched and parsed only then, and logged

One DOCUMENT per tournament-day holds every part — the women from the WTA,
the men from Sofascore — so a combined venue is one schedule again, as its
sheet was. The bytes are normalized (volatile score fields dropped) so a
point is never a revision, and `parse_day_document` is the single parser
`ingest_document` needs.

Courts are made to agree across the parts: a Sofascore name is passed
through the learned mapping ("Grandstand" -> "GRANDSTAND") so the two halves
of a day fall under one heading, and a WTA row the feed left unnamed takes
its court from the women's Sofascore row for the same match — those rows
ride in the document for their courts only and are never emitted twice.

Sofascore is asked ONCE per tournament per tick — the first page of coming
and of recent events, singles and doubles — and the answer is sliced per
day, so the budget is a handful of requests a quarter-hour whatever the day
window. NEVER bulk-collect from Sofascore: a 403 bans the egress address the
live scores depend on.
"""
import asyncio
import json
import logging
import os
from datetime import date
from functools import partial
from typing import Optional

logger = logging.getLogger(__name__)

# The PDF as the fallback of last resort. "0" retires it entirely: a day no
# feed can supply is then simply absent, and says so in the log.
PDF_FALLBACK = os.environ.get("SCHEDULE_PDF_FALLBACK", "1").strip() != "0"

# Feed answers, keyed per source, for the length of one tick.
_events: dict[tuple, list] = {}


def reset_tick_cache() -> None:
    _events.clear()


def plan(draws, wta_event_id: Optional[int]) -> list[tuple[object, str]]:
    """Which feed serves each draw: ('wta' | 'sofa' | 'none') per draw.

    A women's draw goes to the WTA feed when the tournament has a WTA event
    id, else to Sofascore where it has ids. A men's draw goes to Sofascore.
    A draw with no id anywhere gets nothing — and the caller may then fall
    back to the PDF for the whole tournament.
    """
    out = []
    for d in draws:
        gender = (getattr(d, "gender", "") or "").upper()
        has_sofa = bool(getattr(d, "sofa_tournament_id", None) and getattr(d, "sofa_season_id", None))
        if gender == "F" and wta_event_id:
            out.append((d, "wta"))
        elif has_sofa:
            out.append((d, "sofa"))
        else:
            out.append((d, "none"))
    return out


def _surname(name: str) -> str:
    """The surname alone, folded — the one token every source agrees on.
    Sofascore writes a doubles player "Gleason Q." (surname_last makes it
    "Q Gleason"), the WTA "Quinn GLEASON USA": a whole-name token set never
    matched a pair across the two (2026-09-18)."""
    import re
    from app.services.schedule import _fold
    s = re.sub(r"^(?:\[[^\]]*\]\s*)+", "", (name or "").strip())
    s = re.sub(r"\s+[A-Z]{3}$", "", s)
    toks = s.split()
    if not toks:
        return ""
    folded = _fold(toks[-1])
    return next(iter(folded)) if folded else toks[-1].lower()


def _sig(m) -> Optional[frozenset]:
    """One match's identity across sources: the surnames of everyone in it."""
    names = list(m.side_a or []) + list(m.side_b or [])
    out = frozenset(_surname(n) for n in names if _surname(n))
    return out or None


def _map_court(name: str, court_names: dict) -> str:
    """A Sofascore court through the learned mapping, else as Sofascore says it."""
    n = (name or "").strip()
    return court_names.get(n) or n


def parse_day_document(doc: bytes, court_names: Optional[dict] = None,
                       venue_tz: Optional[str] = None):
    """(matches, meta) from bytes written by build_day_document."""
    from app.services import sofa_schedule, wta_feed

    court_names = court_names or {}
    parts = json.loads(doc.decode("utf-8"))
    meta = {"source": "feeds", "wta": 0, "sofa": 0}

    sofa_rows, court_rows = [], []
    for part in parts.get("sofa") or []:
        ms, _m = sofa_schedule.parse_sofa_day(part["doc"].encode("utf-8"),
                                              venue_tz=venue_tz, discipline=part["disc"])
        for m in ms:
            m.court = _map_court(m.court, court_names)
            if part.get("tour"):
                m.tour = part["tour"]
        (court_rows if part.get("courts_only") else sofa_rows).extend(ms)
    meta["sofa"] = len(sofa_rows)

    wta_rows = []
    if parts.get("wta"):
        wta_rows, _m = wta_feed.parse_wta_day(parts["wta"].encode("utf-8"),
                                              court_names=court_names, venue_tz=venue_tz)
        # A WTA row the feed left without a court takes the court of the
        # Sofascore row for the same match — Guadalajara's semi-final day
        # arrived with no CourtID at all (2026-09-18).
        by_sig = {}
        for m in court_rows + sofa_rows:
            s = _sig(m)
            if s and (m.court or "").strip():
                by_sig.setdefault(s, m.court)
        for m in wta_rows:
            if not (m.court or "").strip():
                s = _sig(m)
                if s and s in by_sig:
                    m.court = _map_court(by_sig[s], court_names)
    meta["wta"] = len(wta_rows)

    # The women's rows from the WTA, the men's from Sofascore; a match offered
    # twice (a women's draw served by Sofascore as well) is kept once.
    matches, seen = [], set()
    for m in wta_rows + sofa_rows:
        key = (m.tour, m.discipline, _sig(m) or id(m))
        if key in seen:
            continue
        seen.add(key)
        matches.append(m)
    matches.sort(key=lambda m: (m.court or "", m.time or ""))
    meta["count"] = len(matches)
    return matches, meta


async def _sofa_parts(draw, day: date, venue_tz: Optional[str], tour: str,
                      courts_only: bool = False) -> list[dict]:
    """The day's Sofascore rows for one draw, singles and doubles, as document parts."""
    from app.services import sofa_schedule
    parts = []
    for tid, sid, disc in ((draw.sofa_tournament_id, draw.sofa_season_id, "singles"),
                           (getattr(draw, "sofa_doubles_tournament_id", None),
                            getattr(draw, "sofa_doubles_season_id", None), "doubles")):
        if not tid or not sid:
            continue
        key = ("sofa", tid, sid)
        if key not in _events:
            evs = await sofa_schedule.fetch_events(tid, sid, "next", pages=1)
            evs += await sofa_schedule.fetch_events(tid, sid, "last", pages=1)
            _events[key] = evs
        sdoc = sofa_schedule.normalize_day(_events[key], day, venue_tz)
        if json.loads(sdoc):
            part = {"disc": disc, "tour": tour, "doc": sdoc.decode("utf-8")}
            if courts_only:
                part["courts_only"] = True
            parts.append(part)
    return parts


async def build_day_document(db, tournament, draws, day: date, season_year: int,
                             venue_tz: Optional[str]) -> Optional[dict]:
    """One day's schedule from the feeds: {url, bytes, parser, count, atp, wta,
    sources} ready for ingest_document, or None when no feed has a row."""
    from app.services import schedule_shadow, wta_feed

    event_id = await schedule_shadow.wta_event_id(db, tournament.id, draws)
    parts = {"day": day.isoformat(), "wta": None, "sofa": []}
    sources = []
    for draw, src in plan(draws, event_id):
        try:
            if src == "wta":
                key = ("wta", event_id)
                if key not in _events:
                    _events[key] = await asyncio.to_thread(wta_feed.fetch_matches, event_id, season_year)
                wdoc = wta_feed.normalize_day(_events[key], day, venue_tz)
                has_sofa = bool(draw.sofa_tournament_id and draw.sofa_season_id)
                if json.loads(wdoc):
                    parts["wta"] = wdoc.decode("utf-8")
                    sources.append(f"wta:{event_id}")
                    # The women's Sofascore rows ride along for their courts only.
                    if has_sofa:
                        parts["sofa"] += await _sofa_parts(draw, day, venue_tz, "WTA", courts_only=True)
                elif has_sofa:
                    # THE WTA FEED HAS NOTHING FOR THE DAY (SP Open's Thursday,
                    # 2026-09-18) — Sofascore is then the women's schedule,
                    # not the PDF.
                    got = await _sofa_parts(draw, day, venue_tz, "WTA")
                    if got:
                        parts["sofa"] += got
                        sources.append(f"sofa:{draw.sofa_tournament_id}")
            elif src == "sofa":
                tour = "WTA" if (draw.gender or "").upper() == "F" else "ATP"
                got = await _sofa_parts(draw, day, venue_tz, tour)
                if got:
                    parts["sofa"] += got
                    sources.append(f"sofa:{draw.sofa_tournament_id}")
        except Exception as exc:          # noqa: BLE001 — one feed failing must not lose the others
            logger.info("feed %s unavailable for %s %s: %s", src, tournament.name, day, exc)

    if parts["wta"] is None and not [p for p in parts["sofa"] if not p.get("courts_only")]:
        return None
    names = await schedule_shadow.court_names(db, tournament.id, min_votes=3)
    parser = partial(parse_day_document, court_names=names, venue_tz=venue_tz)
    doc = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    matches, meta = parser(doc)
    if not matches:
        return None
    return {"url": f"feeds://{'+'.join(sources)}/{day.isoformat()}", "bytes": doc, "parser": parser,
            "count": len(matches), "atp": sum(1 for m in matches if m.tour == "ATP"),
            "wta": sum(1 for m in matches if m.tour == "WTA"), "sources": sources}
