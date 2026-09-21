"""THE WTA'S OWN SEASON LIST — discovery and dates for the women's tour,
without Wikipedia.

    https://api.wtatennis.com/tennis/tournaments/?from=YYYY-01-01&to=YYYY-12-31
                                                 &page=N&pageSize=100

Public, unauthenticated, and it states everything discovery used to read off
Wikipedia's "{year} WTA Tour" page — and more:

    tournamentGroup.name   "SEOUL"                        (the tour's key)
    title                  "Korea Open - Seoul, KOR"      (the name we use)
    level                  Grand Slam / WTA 1000 / 500 / 250 / 125 / ITF
    startDate, endDate     MAIN-DRAW dates — measured equal to ours on
                           Guadalajara, Seoul, Singapore and Beijing
    city, country, surface, inOutdoor, singlesDrawSize (entrants), prizeMoney
    liveScoringId          Tournament.wta_live_scoring_id — the id the order
                           of play and the draw sheet are already keyed by
    status                 past / live / future

TWO QUIRKS. pageInfo.numPages always reads 0 (numEntries is right: 549 for
2026, most of it ITF), so paging runs until a short page. And a title carries
the sponsor on some events ("Kinoshita Group Japan Open - Osaka, JPN"), so a
draw we already hold KEEPS ITS NAME; the title names only a draw we create.

WHAT THIS OWNS. For a women's draw whose tournament carries a WTA id, this is
the DATE AUTHORITY: every Wikipedia date path defers
(tournament_sync.official_dates). Two rules keep that safe:

  * a released draw's start never moves EARLIER to a day already reached —
    that is the one date change that locks picks — same rule as the writer's;
  * an end date never moves backwards past play we have observed: the API
    said SP Open ended 20 September while the rain-delayed final was on court
    on the 21st. extend_end_dates saw the sheet; the list had not caught up.
"""
import hashlib
import json
import logging
import os
import re
import time
from datetime import date
from typing import Optional
from urllib.request import Request, urlopen

from sqlalchemy import select

from app.models.tournament import Draw, Tournament
from app.services.discovery import DiscoveredTournament
from app.services.tournament_sync import fold
from app.services.wta_feed import HEADERS, TIMEOUT

logger = logging.getLogger(__name__)

BASE = "https://api.wtatennis.com/tennis/tournaments/"
TOUR_LEVELS = ("Grand Slam", "WTA 1000", "WTA 500", "WTA 250")
CACHE_DIR = os.environ.get("WTA_CACHE_DIR", "/data/wta-cache")
CACHE_TTL = 6 * 3600.0
PAGE = 100

_SPONSOR = re.compile(r"\s+(presented by|presentado por|by)\s+.+$", re.I)


def clean_name(title: str, group: str) -> str:
    """The tournament's name, as this project names it.

    "Korea Open - Seoul, KOR" -> "Korea Open". The location suffix goes, and
    so does a trailing sponsor clause. A leading sponsor ("Kinoshita Group
    Japan Open") is left alone: cutting words off the front is guessing, and
    the owner has display_name / short_name for exactly that.
    """
    name = (title or "").split(" - ")[0].strip()
    name = _SPONSOR.sub("", name).strip()
    if not name:
        name = " ".join(w.capitalize() for w in (group or "").split())
    return name


_TEAM_WORDS = ("united cup", "billie jean king cup", "hopman cup", "team event")


def is_team_event(item: dict) -> bool:
    """A tour-level entry that is a competition between nations, not a draw."""
    text = " ".join(((item.get("title") or ""), ((item.get("tournamentGroup") or {}).get("name") or ""))).lower()
    return any(w in text for w in _TEAM_WORDS)


def _cached_json(url: str) -> dict:
    f = f"{CACHE_DIR}/{hashlib.sha1(url.encode()).hexdigest()}.json"
    try:
        if time.time() - os.path.getmtime(f) < CACHE_TTL:
            with open(f, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except (OSError, ValueError):
        pass
    with urlopen(Request(url, headers=HEADERS), timeout=TIMEOUT) as r:
        payload = json.loads(r.read())
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except OSError:
        pass
    return payload


def fetch_season(year: int, *, fetch=_cached_json) -> list[dict]:
    """Every tour-level event the WTA lists for the year."""
    items: list = []
    for page in range(0, 12):
        url = (f"{BASE}?from={year}-01-01&to={year}-12-31&page={page}&pageSize={PAGE}")
        content = (fetch(url) or {}).get("content") or []
        items += content
        if len(content) < PAGE:
            break
    return [i for i in items if i.get("level") in TOUR_LEVELS and int(i.get("year") or 0) == year]


def _date(s) -> Optional[date]:
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def to_discovered(item: dict) -> Optional[DiscoveredTournament]:
    """One list entry as a DiscoveredTournament, or None if it is not a
    singles draw we can key: no liveScoringId, or no singles draw at all —
    the list carries team events (United Cup, singlesDrawSize 0) at tour level."""
    try:
        lsid = int(item.get("liveScoringId"))
    except (TypeError, ValueError):
        return None
    # A TEAM EVENT IS NOT A DRAW; A MISSING SIZE IS NOT A TEAM EVENT. The list
    # carries United Cup at WTA 500 with singlesDrawSize 0 — and, the same
    # year, Eastbourne with 0 as a plain data gap. Excluding on size alone
    # threw a real tournament away (the one women's draw left unkeyed after
    # the first production run). Team events are named; sizes are advisory.
    if is_team_event(item):
        return None
    group = (item.get("tournamentGroup") or {}).get("name") or ""
    name = clean_name(item.get("title") or "", group)
    year = int(item.get("year") or 0)
    if not name or not year:
        return None
    city = " ".join(w.capitalize() for w in (item.get("city") or "").split()) or None
    return DiscoveredTournament(
        name=name, year=year, gender="F",
        surface=(item.get("surface") or "").strip() or "Hard",
        category=item.get("level") or "",
        draw_size=int(item.get("singlesDrawSize") or 0),
        wiki_page_title=f"{year} {name} – Singles",
        start_date=_date(item.get("startDate")),
        end_date=_date(item.get("endDate")),
        city=city, country=(item.get("country") or None),
        title_is_guess=True, wta_id=lsid,
    )


async def _draw_by_city(db, d: DiscoveredTournament, year: int) -> Optional[Draw]:
    """The one women's draw in this city that week, whatever its level.

    find_existing_match only looks inside the level the list states, and folds
    diacritics itself — "UniCredit Iasi Open" in "IASI" now finds our "Iași
    Open" there. This is what is left: the tour and we disagreeing on the
    level, where the right draw is not among the candidates at all. Passed
    as find_existing_match's fallback, so a tie this breaks is never reported
    as ambiguous. Exactly one, or nothing.
    """
    if not d.city or not d.start_date:
        return None
    rows = (await db.execute(select(Draw).where(
        Draw.gender == "F", Draw.year == year, Draw.start_date.isnot(None)))).scalars().all()
    hits = [r for r in rows if r.city and fold(r.city) == fold(d.city)
            and abs((r.start_date - d.start_date).days) <= 7]
    return hits[0] if len(hits) == 1 else None


async def _draw_for(db, lsid: int, year: int) -> Optional[Draw]:
    """The women's draw already keyed to this WTA id, if any."""
    rows = (await db.execute(
        select(Draw).join(Tournament, Tournament.id == Draw.tournament_id).where(
            Tournament.wta_live_scoring_id == lsid,
            Draw.gender == "F", Draw.year == year))).scalars().all()
    return rows[0] if rows else None


def _apply_official_dates(existing: Draw, d: DiscoveredTournament, today: date) -> list[str]:
    """Official start/end onto a draw we hold, under the two safety rules."""
    changed: list = []
    frozen = existing.status in ("active", "completed") or existing.first_match_at is not None
    if d.start_date and not frozen and d.start_date != existing.start_date:
        released = existing.draw_released_direct_at is not None
        if (released and existing.start_date and d.start_date < existing.start_date
                and d.start_date <= today):
            logger.warning("Refused to move %s %s start_date back from %s to %s "
                           "on a released draw", existing.year, existing.name,
                           existing.start_date, d.start_date)
        else:
            existing.start_date = d.start_date
            changed.append("start_date")
    if d.end_date and d.end_date != existing.end_date:
        # Never backwards past play we have seen (the rain-delayed final).
        if existing.end_date is None or d.end_date > existing.end_date:
            existing.end_date = d.end_date
            changed.append("end_date")
    return changed


async def sync_wta_season(db, year: int, *, today: Optional[date] = None,
                          events: Optional[list] = None, scrape_new: bool = False) -> dict:
    """Discover and date every women's tour event of the year from the WTA.

    A draw already keyed by WTA id is updated; one we only know by name is
    keyed now (so the next pass finds it by id) and updated; one we do not
    hold at all is created through the same create_discovered the Wikipedia
    sync uses. Names and Wikipedia titles of draws we hold are never touched.
    The caller commits.
    """
    from app.services.events import attach
    from app.services.tournament_sync import (_apply_update, create_discovered,
                                              find_existing_match)

    today = today or date.today()
    report = {"year": year, "seen": 0, "keyed": 0, "updated": 0, "created": 0,
              "unkeyable": 0, "date_changes": []}
    items = events if events is not None else fetch_season(year)
    for item in items:
        d = to_discovered(item)
        if d is None:
            report["unkeyable"] += 1
            continue
        report["seen"] += 1
        existing = await _draw_for(db, d.wta_id, year)
        if existing is None:
            existing = await find_existing_match(db, d, year, fallback=_draw_by_city)
            if existing is not None and existing.tournament_id:
                row = await db.get(Tournament, existing.tournament_id)
                if row is not None and not row.wta_live_scoring_id:
                    row.wta_live_scoring_id = d.wta_id
                    report["keyed"] += 1
        if existing is not None:
            if d.draw_size < 8:
                d.draw_size = existing.draw_size      # the list's 0 is a gap, not a size
            moved = _apply_official_dates(existing, d, today)
            if moved:
                report["date_changes"].append((existing.id, existing.name, moved))
            # A draw we hold keeps its name and its Wikipedia title; the tour
            # may still correct its category, surface, city and draw size.
            d.name, d.wiki_page_title, d.country = existing.name, existing.wiki_page_title, None
            if existing.city:
                d.city = None
            if await _apply_update(existing, d, db) or moved:
                report["updated"] += 1
            continue
        if d.draw_size < 8:
            report["unsized"] = report.get("unsized", 0) + 1
            logger.info("Not creating %d %s from the WTA list: no draw size stated", year, d.name)
            continue
        try:
            async with db.begin_nested():
                t = await create_discovered(db, d, year, scrape_new=scrape_new)
                await attach(db, t)
                if t.tournament_id:
                    row = await db.get(Tournament, t.tournament_id)
                    if row is not None and not row.wta_live_scoring_id:
                        row.wta_live_scoring_id = d.wta_id
            report["created"] += 1
            logger.info("Added %d %s (F) from the WTA season list, id %s", year, d.name, d.wta_id)
        except Exception as exc:                                   # noqa: BLE001
            logger.warning("Could not create %d %s from the WTA list: %s", year, d.name, exc)
    return report
