"""
Order of Play (OOP) links.

Both tours publish the day's schedule as a PDF at a URL that never changes —
they overwrite the same path each time it is revised — so there is nothing to
"discover" per day. The whole job is deciding whether the file currently sitting
at that path is TODAY's, and which of our draws it actually covers.

    WTA:  https://wtafiles.wtatennis.com/pdf/draws/{year}/{liveScoringId}/OP.pdf
    ATP:  https://www.protennislive.com/posting/{year}/{atpId}/op.pdf   (phase 2)

Phase 1 is WTA-sourced only, because the WTA hands us tournament ids through a
public JSON API while the ATP has no equivalent — an ATP-only event needs a
hand-maintained id map, which is deliberately left to phase 2. That costs less
coverage than it sounds: at a combined event held on ONE site the WTA file is
the venue's order of play and lists the men's matches too (Cincinnati 2026:
17 ATP labels alongside 14 WTA), so both our draws can point at it.

Three traps, each verified against the live files on 2026-08-18:

1. **HTTP 200 does not mean current.** A finished tournament keeps serving its
   final day's PDF indefinitely — 2026 ATP id 424 still returns 200 with a
   Last-Modified of 15 February. Freshness has to be asserted, never assumed.
2. **The filename is case-sensitive on the WTA side.** `OP.pdf` is 200 and
   `op.pdf` is 404. The ATP path is lowercase. They do not match each other.
3. **Coverage follows the venue, not the tour.** Canada 2026 ran the women in
   Toronto and the men in Montreal, and its WTA file contains zero ATP matches,
   whereas Cincinnati's covers both. Guessing from "is this a combined event"
   gets Canada wrong every year, so we read the PDF and let it tell us.

Freshness is decided by the date printed INSIDE the PDF, not by Last-Modified.
A revision published at 23:50 local for the following day would look stale by
header alone, and a file frozen since February looks fresh to anything that
only checks "did this change recently".
"""

import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, or_, select

from app.database import AsyncSessionLocal
from app.models.schedule import ScheduleEntry
from app.models.tournament import Draw, Tournament
from app.services.http_errors import is_transient_http_error, describe_exception
from app.services import schedule_feeds
from app.services.rankings import _norm
from app.services.system_log import app_log

logger = logging.getLogger(__name__)

_ATP_PDF = "https://www.protennislive.com/posting/{year}/{atp_id}/op.pdf"

# How early to start looking for an order of play, per tier. Deliberately
# generous: a miss costs one request against a static file host, while being a
# day short means missing a whole qualifying round.
#
# The existing default_qual_days columns are NOT this — they say when the
# qualifying DRAW is released (3 for a Slam), which has nothing to do with when
# qualifying play begins. US Open qualifying starts six days before the main
# draw, so a three-day window would have missed half of it.
_OOP_LEAD_DAYS = {
    "Grand Slam": 12,
    "ATP 1000": 8, "WTA 1000": 8,
    "ATP 500": 6, "WTA 500": 6,
    "ATP 250": 6, "WTA 250": 6,
}
_DEFAULT_OOP_LEAD_DAYS = 6

_WIKI_API = "https://en.wikipedia.org/w/api.php"
_WTA_API = "https://api.wtatennis.com/tennis/tournaments/"
_WTA_PDF = "https://wtafiles.wtatennis.com/pdf/draws/{year}/{lsid}/OP.pdf"

_UA = "TennisFantasyLeague/1.0 (https://upsetalert.ca; pdwiens@gmail.com)"
# Seconds between consecutive PDF fetches. See the pacing note in the fetch
# loop — the tours' file hosts rate-limit a burst, and a paced pass costs
# seconds on a quarter-hourly job.
_FETCH_GAP_SECONDS = 1.5

_HEADERS = {"User-Agent": _UA}

# The API ignores a `year` filter and returns all ~18.7k tournaments back to
# 1960 in ascending date order, so the only way to reach the current season is
# to ask for the last page. pageSize caps at 100.
_PAGE_SIZE = 100

# "ORDER OF PLAY - TUESDAY, 18 AUGUST 2026"  (WTA)
# "ORDER OF PLAY - TUESDAY, AUGUST 18, 2026" (ATP)
_OOP_DATE_RE = re.compile(
    r"ORDER\s+OF\s+PLAY\s*[-–]\s*[A-Z]+,\s*"
    r"(?:(?P<d1>\d{1,2})\s+(?P<m1>[A-Z]+)|(?P<m2>[A-Z]+)\s+(?P<d2>\d{1,2}),?)"
    r"\s*(?P<y>\d{4})",
    re.I,
)

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}

# A tour label appears next to every match only when the file has to
# disambiguate, i.e. when both tours play the same site. A WTA-only order of
# play carries at most an incidental mention in a header, so requiring two
# keeps a stray word from claiming coverage we do not have.
_MIN_TOUR_LABELS = 2

def _lead_days(draw) -> int:
    """Days before start_date to begin polling, from the draw's tier."""
    variant = getattr(draw, "variant", None)
    name = getattr(variant, "category_name", None) if variant else None
    return _OOP_LEAD_DAYS.get(name, _DEFAULT_OOP_LEAD_DAYS)


async def _fetch_wta_events() -> list[dict]:
    """
    Current-season WTA events that have a liveScoringId (ITF rows do not).

    Reads the last TWO pages, not one. The archive is append-ish and numEntries
    genuinely moves while you are reading it — it went 18761 -> 18776 between
    two calls a few minutes apart during development, which shifted the page
    boundary and pushed that week's Washington and Memphis events off the last
    page onto the previous one. A single-page read silently loses whichever
    current events happen to be sitting near the boundary, and "silently loses
    some tournaments" is the worst possible failure here because everything
    downstream just looks like a tournament with no order of play.
    """
    events: dict[int, dict] = {}
    async with httpx.AsyncClient(timeout=20, headers=_HEADERS) as client:
        head = await client.get(_WTA_API, params={"page": 0, "pageSize": 1})
        head.raise_for_status()
        total = (head.json().get("pageInfo") or {}).get("numEntries") or 0
        if not total:
            return []

        last_page = max((total - 1) // _PAGE_SIZE, 0)
        for page in {max(last_page - 1, 0), last_page}:
            resp = await client.get(_WTA_API, params={"page": page, "pageSize": _PAGE_SIZE})
            resp.raise_for_status()
            for t in (resp.json().get("content") or []):
                if t.get("liveScoringId"):
                    events[int(t["liveScoringId"])] = t

    return list(events.values())


def _match_wta_event(
    name: str, city: Optional[str], start: date, events: list[dict]
) -> Optional[dict]:
    """
    Best WTA event for one of our tournaments, or None.

    Neither name nor city works alone, which is the whole reason this is scored
    rather than looked up. Sponsor titles break the name ("Canadian Open" vs
    "National Bank Open presented by Rogers", "Washington Open" vs "Mubadala DC
    Open") and venue suburbs break the city (we hold Cincinnati as Mason, they
    hold it as CINCINNATI). Either signal alone is enough when the dates line
    up; both is better. Start dates disagree by a day often enough — their
    Monterrey is the 23rd and ours the 24th — that an exact match would drop
    real events on the floor.
    """
    ours_name = set(_norm(name).split())
    ours_city = set(_norm(city).split()) if city else set()

    best, best_score = None, 0.0
    for ev in events:
        try:
            ev_start = date.fromisoformat((ev.get("startDate") or "")[:10])
        except ValueError:
            continue
        day_gap = abs((ev_start - start).days)
        if day_gap > 3:
            continue

        title = (ev.get("title") or "").split(" - ")[0]
        their_name = set(_norm(title).split())
        their_city = set(_norm(ev.get("city") or "").split())

        name_hit = bool(ours_name & their_name)
        city_hit = bool(ours_city & their_city)
        if not (name_hit or city_hit):
            continue

        # City is the stronger signal: a sponsor can rename an event but the
        # town it is played in is the same fact on both sides.
        score = (1.5 if city_hit else 0) + (1.0 if name_hit else 0) - (day_gap * 0.1)
        if score > best_score:
            best, best_score = ev, score

    return best


def _parse_oop(pdf: bytes) -> tuple[Optional[date], int, int]:
    """(date the OOP is for, ATP label count, WTA label count) from page 1."""
    try:
        import pdfplumber
        with pdfplumber.open(BytesIO(pdf)) as doc:
            text = doc.pages[0].extract_text() or ""
    except Exception:
        return None, 0, 0

    when = None
    m = _OOP_DATE_RE.search(text)
    if m:
        month = _MONTHS.get((m.group("m1") or m.group("m2") or "").lower())
        day = m.group("d1") or m.group("d2")
        if month and day:
            try:
                when = date(int(m.group("y")), month, int(day))
            except ValueError:
                when = None

    return when, len(re.findall(r"\bATP\b", text)), len(re.findall(r"\bWTA\b", text))


def _as_date(value) -> Optional[date]:
    """SQLite hands these back as date or datetime depending on the column."""
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _running(draw, today: date) -> bool:
    """Is this draw close enough to be playing today?

    Qualifying runs before the main draw's start_date — a week or more at a
    Slam — so the lead-in comes from the tier rather than one constant."""
    start = _as_date(draw.start_date)
    if start is None or today < start - timedelta(days=_lead_days(draw)):
        return False
    end = _as_date(draw.end_date)
    return end is None or today <= end


_ATP_ID_RE = re.compile(r'atptour\.com/en/tournaments/[a-z0-9\-]+/(\d+)')


async def refresh_atp_ids() -> int:
    """Learn ATP tournament ids from Wikipedia, not from atptour.com.

    The id is the path segment of a tournament's order-of-play PDF on
    protennislive, and it is visible in its atptour.com URL — but atptour.com
    answers 403 to anything that is not a browser, bot protection we are not
    going to fight and would not want to depend on. Wikipedia carries the same
    URL in the article's external links, and it is a source we already use with
    a proper User-Agent and rate-limit handling.

    Coverage is partial: some articles carry the link, some do not. That is
    acceptable because a missing id is now ALERTED rather than silent — see
    _alert_missing_oop — so the gap is visible and can be filled by hand.
    """
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Tournament, Draw)
            .join(Draw, Draw.tournament_id == Tournament.id)
            .where(
                Tournament.atp_tournament_id.is_(None),
                Tournament.wta_live_scoring_id.is_(None),
                Draw.gender == "M",
                Draw.start_date.isnot(None),
            ))).all()

    # Only tournaments near enough to matter; the archive is not worth the calls.
    horizon = date.today() + timedelta(days=45)
    wanted, seen = [], set()
    for tournament, draw in rows:
        start = _as_date(draw.start_date)
        if not start or start > horizon or start < date.today() - timedelta(days=7):
            continue
        if tournament.id in seen:
            continue
        seen.add(tournament.id)
        wanted.append(tournament)
    if not wanted:
        return 0

    stamped = 0
    async with httpx.AsyncClient(timeout=20, headers=_HEADERS) as client:
        for tournament in wanted:
            try:
                resp = await client.get(_WIKI_API, params={
                    "action": "parse", "page": tournament.name,
                    "prop": "externallinks", "format": "json", "redirects": 1,
                })
                resp.raise_for_status()
                links = ((resp.json().get("parse") or {}).get("externallinks") or [])
            except Exception as exc:
                if not is_transient_http_error(exc):
                    await app_log("warning", "order_of_play",
                                  f"ATP id lookup failed for '{tournament.name}': "
                                  f"{describe_exception(exc)}",
                                  dedup_key=f"atp_id_{tournament.id}", dedup_hours=24)
                continue

            found = _ATP_ID_RE.search(" ".join(links))
            if not found:
                continue
            async with AsyncSessionLocal() as db:
                t = await db.get(Tournament, tournament.id)
                if t and t.atp_tournament_id is None:
                    t.atp_tournament_id = int(found.group(1))
                    await db.commit()
                    stamped += 1
    return stamped


def _venue_today(venue_tz: str | None) -> date:
    """The date it is AT THE VENUE — the only date a schedule question is about.

    `date.today()` is the SERVER's date, and the server is UTC while venues are
    not. Every question below is about a tennis day: has play started, is the
    tournament over, is there a sheet for the day being played. All three are
    answered by the venue's calendar, never by ours.

    Monterrey, 2026-08-26 00:12 and 01:13 UTC: it was 6pm Tuesday at the court
    and Tuesday's night session was on Grandstand, with nine slots stored for
    2026-08-25 and the WTA quite reasonably not having published Wednesday's
    sheet yet. `_alert_missing_schedule` asked for a sheet dated "today", read
    its own UTC clock, got Wednesday, found nothing and warned that a fetch or
    a parse was failing quietly. Nothing was failing. Every UTC-negative venue
    does this for the last six hours of every playing day.

    `refresh_order_of_play` already knew — its freshness window accepts
    yesterday's sheet for exactly this reason — but the two alert gates were
    written against the server clock and never got the same treatment.

    Falls back to the server's date when a draw has no timezone: an alert that
    is a few hours out beats an alert that never fires.
    """
    if venue_tz:
        try:
            return datetime.now(ZoneInfo(venue_tz)).date()
        except Exception:
            pass                          # unknown zone name; server date it is
    return date.today()


async def _confirmed_start(draw, stored: date) -> date:
    """The start date an alarm below may JUDGE on — asked of the event page.

    ASK THE PAGE BEFORE ACCUSING IT. While `wiki_page_id is None` nothing has
    ever read the singles infobox, so start_date is still exactly what
    discovery seeded: the Monday of the tournament's week, snapped from a
    rowspan cell that covers the whole week. For an extended-format event that
    Monday is days early — 2026 Chengdu and Hangzhou both really start on the
    Wednesday, moved around the Laver Cup — and "play started today" read off
    it is simply false.

    Both alarms below did exactly that at 00:12 on 21 September and reported
    two tournaments as under way with no sheet, two days before either had put
    a ball in play. _check_draw_health and sofa_resolver already ask the event
    page for precisely this reason (commit 2df1fa3d); these two were the rest
    of the same class, and the class is not "a date that has not been corrected
    yet" but "a date nobody has confirmed, being used as evidence".

    Same source, same cache, no write — and only ever called on the branch that
    is about to accuse, so an ordinary pass over an ordinary draw costs nothing.
    Falls back to the stored date whenever the page cannot be read or has no
    page to read: an unreachable event page is not a reason to go quiet.
    """
    if draw.wiki_page_id is not None:
        return stored                     # the infobox has been read; this IS the date
    from app.services.scraper import confirm_start_date
    try:
        return await confirm_start_date(
            draw.wiki_page_title, draw.year, draw.gender, stored) or stored
    except Exception as exc:
        logger.debug("Event-page start check failed for draw %s: %s", draw.id, exc)
        return stored


async def _stand_down(dedup_key: str, detail: dict, name: str, gender: str,
                      stored: date, confirmed: date, what: str) -> None:
    """Record an alarm declining to fire because the date it rested on was a guess.

    Info, not silence. The check standing down is the interesting part, and the
    reason it stood down is the only thing that would explain, months later, why
    a tournament that "started" on Monday was never asked for a sheet.
    """
    await app_log(
        "info", "order_of_play",
        f"No {what} for '{name}' ({gender}) yet, and that is on schedule: the "
        f"event page starts it {confirmed}, not the stored {stored}.",
        {**detail, "stored_start_date": str(stored),
         "event_page_start_date": str(confirmed)},
        dedup_key=dedup_key, dedup_hours=24,
    )


async def _alert_missing_oop() -> None:
    """Say so when a tournament is under way and we still have no order of play.

    Silence is the failure mode worth guarding against here: an unknown ATP id,
    a renamed file, a changed URL scheme all present identically — as a
    tournament that simply never shows a schedule. Once play has started, that
    is unambiguous enough to be worth an email.

    Dated at the VENUE, per draw — see `_venue_today`. "Play started" is a fact
    about the court, and reading it off a UTC clock made it true up to a day
    early in Asia and up to a day late in the Americas.
    """
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Tournament, Draw)
            .join(Draw, Draw.tournament_id == Tournament.id)
            .where(
                Draw.oop_first_seen_at.is_(None),
                Draw.status != "completed",
                Draw.start_date.isnot(None),
            ))).all()

    for tournament, draw in rows:
        today = _venue_today(draw.venue_timezone)
        start = _as_date(draw.start_date)
        end = _as_date(draw.end_date)
        if not start or start > today:
            continue                      # not started; nothing is wrong yet
        if end and today > end:
            continue                      # over, and it never had one — too late to matter
        confirmed = await _confirmed_start(draw, start)
        if confirmed > today:
            await _stand_down(
                f"oop_missing_not_due_{draw.id}", {"draw_id": draw.id},
                tournament.name, draw.gender, start, confirmed, "order of play")
            continue
        start = confirmed
        why = ("no ATP tournament id on record"
               if not tournament.wta_live_scoring_id and not tournament.atp_tournament_id
               else "the published file never appeared")
        await app_log(
            "error", "order_of_play",
            f"No order of play for '{tournament.name}' ({draw.gender}) — "
            f"play started {start} and {why}.",
            {"tournament_id": tournament.id, "draw_id": draw.id,
             "wta_id": tournament.wta_live_scoring_id,
             "atp_id": tournament.atp_tournament_id},
            dedup_key=f"oop_missing_{draw.id}", dedup_hours=24,
        )


async def refresh_wta_ids() -> int:
    """Stamp tournaments.wta_live_scoring_id for anything running soon."""
    try:
        events = await _fetch_wta_events()
    except Exception as exc:
        if not is_transient_http_error(exc):
            await app_log("error", "order_of_play",
                          f"WTA tournament list failed: {describe_exception(exc)}",
                          dedup_key="oop_wta_list", dedup_hours=6)
        return 0
    if not events:
        return 0

    stamped = 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Tournament, Draw)
            .join(Draw, Draw.tournament_id == Tournament.id)
            .where(
                Tournament.wta_live_scoring_id.is_(None),
                Draw.gender == "F",
                Draw.start_date.isnot(None),
            )
        )).all()

        for tournament, draw in rows:
            start = draw.start_date
            if isinstance(start, datetime):
                start = start.date()
            # A WTA id is only useful while the event is close enough to have a
            # published order of play; back-filling the whole archive would
            # match thousands of rows against one page of current events.
            if abs((start - date.today()).days) > 30:
                continue

            ev = _match_wta_event(tournament.name, draw.city or tournament.city, start, events)
            if not ev:
                continue
            tournament.wta_live_scoring_id = int(ev["liveScoringId"])
            stamped += 1

        if stamped:
            await db.commit()
    return stamped


# Slams the tours' file hosts do not cover. wtafiles 404s the US Open and
# protennislive serves a permanent "-Tournament Information Not Yet
# Available-" placeholder (2025's STILL says that), so the tournament's own
# IBM feed is the only order of play there is — see uso_feed.
_SLAM_FEEDS = {"US Open"}


async def _refresh_slam_feed(tournament, draws, season_year: int, today: date):
    """Ingest the US Open's own schedule feed; returns the chip payload.

    Fetches the day index, ingests every released day from yesterday on
    (capped at three — today, tomorrow, and a venue-midnight straggler), and
    returns {date, url, atp, wta} for the day the OOP chip should carry:
    today's sheet when there is one, else the next released day.
    """
    from app.services import uso_feed
    from app.services import schedule as schedule_svc
    from app.services.db_retry import with_write_retry

    async with httpx.AsyncClient(timeout=30,
                                 headers=uso_feed.BROWSER_HEADERS) as client:
        r = await client.get(uso_feed.FEED_DAYS.format(year=season_year))
        r.raise_for_status()
        days = []
        for e in r.json().get("eventDays") or []:
            pd = uso_feed.play_date_of(e, season_year)
            if (e.get("released") and e.get("feedUrl") and pd is not None
                    and pd >= today - timedelta(days=1)):
                days.append((pd, e))
        days.sort(key=lambda t: t[0])

        ingested = []
        for pd, e in days[:3]:
            await asyncio.sleep(_FETCH_GAP_SECONDS)
            fr = await client.get(e["feedUrl"])
            if fr.status_code != 200:
                continue
            # Normalized bytes are what gets stored and hashed — the raw feed
            # re-serializes its live scores on every publish, and hashing that
            # would call every score change a schedule revision.
            norm = uso_feed.normalize(fr.content)
            matches, _meta = uso_feed.parse_uso_day(norm)
            if not matches:
                continue
            day_url = uso_feed.WEBVIEW_DAY.format(day=e.get("tournDay") or "")

            async def _ingest(sdb, _pd=pd, _doc=norm, _u=day_url):
                t = await sdb.get(type(tournament), tournament.id)
                return await schedule_svc.ingest_document(
                    sdb, t, _pd, _u, _doc,
                    parser=uso_feed.parse_uso_day, queue_verify=False)

            async def _estimates(sdb, _pd=pd):
                return await schedule_svc.recompute_expected_starts(
                    sdb, tournament.id, _pd,
                    venue_tz=next((d.venue_timezone for d in draws
                                   if d.venue_timezone), None))

            async with schedule_svc.day_write_lock:   # see schedule.day_write_lock
                await with_write_retry(_ingest, what=f"uso feed ingest {tournament.id}")
                await with_write_retry(_estimates, what=f"uso feed estimates {tournament.id}")
            ingested.append((pd, day_url, matches))

    if not ingested:
        return None
    pd, day_url, matches = next((x for x in ingested if x[0] >= today),
                                ingested[-1])
    return {"date": pd, "url": day_url,
            "atp": sum(1 for m in matches if m.tour == "ATP"),
            "wta": sum(1 for m in matches if m.tour == "WTA")}


async def _ingest_feed_days(tournament, draws, feed_days: dict, venue_tz) -> None:
    """Write each feed-built day through the same ingest the sheet used —
    same locks, same retries, same revision fingerprint — and say so once
    per new document. queue_verify=False: the verifier's toolchain reads PDFs."""
    from app.services import schedule as schedule_svc
    from app.services.db_retry import with_write_retry

    for day_, doc in sorted(feed_days.items()):
        tour = ("ATP" if doc["atp"] and not doc["wta"]
                else "WTA" if doc["wta"] and not doc["atp"] else None)

        async def _ingest(sdb, _day=day_, _doc=doc, _tour=tour):
            t = await sdb.get(type(tournament), tournament.id)
            return await schedule_svc.ingest_document(
                sdb, t, _day, _doc["url"], _doc["bytes"], tour=_tour,
                parser=_doc["parser"], queue_verify=False)

        async def _estimates(sdb, _day=day_):
            return await schedule_svc.recompute_expected_starts(
                sdb, tournament.id, _day, venue_tz=venue_tz)

        try:
            async with schedule_svc.day_write_lock:   # see schedule.day_write_lock
                ingested = await with_write_retry(_ingest, what=f"feed ingest {tournament.id}")
                await with_write_retry(_estimates, what=f"feed estimates {tournament.id}")
            if not (ingested or {}).get("skipped"):
                await app_log("info", "order_of_play",
                              f"{tournament.name} {day_}: schedule from the feeds "
                              f"({doc['count']} matches: {doc['wta']} WTA, {doc['atp']} ATP; {'+'.join(doc['sources'])})")
        except Exception as exc:
            await app_log("warning", "order_of_play",
                          f"Feed schedule ingest failed for '{tournament.name}' {day_}: "
                          f"{describe_exception(exc)}",
                          dedup_key=f"feed_ingest_{tournament.id}", dedup_hours=6)


def _pdf_fallback_note(tournament, pdf_date, declined_days: dict,
                       unfed_days: dict) -> tuple[str, str, str]:
    """(level, message, dedup key) for a day the PDF filled in, by why."""
    if pdf_date in declined_days:
        # INFO, not a warning: the WTA publishes every sheet's "Followed By"
        # matches unordered until they are played, so this is the ordinary
        # state of a next day rather than a gap anyone can act on.
        return ("info",
                f"{tournament.name} {pdf_date}: the feeds could not state "
                f"the day ({declined_days[pdf_date]}); the PDF filled in",
                f"pdf_declined_{tournament.id}")
    if pdf_date in unfed_days:
        # INFO too: no feed could be ASKED, because an id is not resolved yet
        # — which every new tournament's first sheet beats (see
        # schedule_feeds.build_day_document). The missing id has its own
        # alarm, timed to the draw being due: sofa_resolver._coverage_check.
        return ("info",
                f"{tournament.name} {pdf_date}: no feed to ask yet "
                f"({unfed_days[pdf_date]}); the PDF filled in",
                f"pdf_unfed_{tournament.id}")
    # A warning, deliberately: every draw had a feed and none of them had the
    # day — a feed down, or one that has dropped the tournament — and the
    # watcher should look at it.
    return ("warning",
            f"{tournament.name} {pdf_date}: no feed had a schedule; the PDF filled in",
            f"pdf_fallback_{tournament.id}")


async def refresh_order_of_play() -> int:
    """
    Point every eligible draw at today's OOP, or at nothing.

    Clearing matters as much as setting: a draw that had a link yesterday must
    lose it the moment the file stops being current, or the tournament ends and
    the page keeps offering a PDF that is frozen on the final day's play.
    """
    today = date.today()
    updated = 0
    schedule_feeds.reset_tick_cache()

    pending: dict[int, dict] = {}
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Tournament, Draw)
            .join(Draw, Draw.tournament_id == Tournament.id)
            .where(
                or_(Tournament.wta_live_scoring_id.isnot(None),
                    Tournament.atp_tournament_id.isnot(None)),
                Draw.status != "completed",
                Draw.start_date.isnot(None),
            )
        )).all()

        by_tournament: dict[int, list] = {}
        for tournament, draw in rows:
            by_tournament.setdefault(tournament.id, []).append((tournament, draw))

        for gi, group in enumerate(by_tournament.values()):
            # Pace the burst. Every tournament's PDF was requested back to back
            # against the same two file hosts, and protennislive.com answers a
            # run like that with 429s — which cost whichever tournaments came
            # later in the loop their refresh entirely.
            #
            # A second and a half between fetches adds about ten seconds to a
            # job that runs every fifteen minutes. Nothing waits on it, and the
            # alternative is a burst that reliably loses its own tail.
            if gi:
                await asyncio.sleep(_FETCH_GAP_SECONDS)
            tournament = group[0][0]
            draws = [d for _, d in group]
            # WTA file where there is one — at a shared venue it covers both
            # draws. Otherwise the ATP's own, which is the only source for an
            # event with no WTA counterpart.
            # The SEASON's year, not today's. A season opener straddles New
            # Year — Brisbane 2027 begins in December 2026 — and the tours file
            # its sheets under the season, so on 30 December today.year would
            # ask for the wrong directory entirely. For every tournament that
            # does not straddle, the two are the same.
            season_year = getattr(draws[0], "year", None) or today.year
            if tournament.wta_live_scoring_id:
                url = _WTA_PDF.format(year=season_year, lsid=tournament.wta_live_scoring_id)
                src_tour = "WTA"
            else:
                url = _ATP_PDF.format(year=season_year, atp_id=tournament.atp_tournament_id)
                src_tour = "ATP"

            tz = next((d.venue_timezone for d in draws if d.venue_timezone), None)
            # THE FEEDS FIRST (owner, 2026-09-18): every day in the window the
            # WTA's JSON or Sofascore can supply is written from them — see
            # schedule_feeds. A Slam keeps its own feed below. The PDF is
            # fetched only when no feed has a row for any day, or when a feed
            # had a day it could not state (`declined`: no court, or no order
            # on a court), and then the log says so.
            feed_days: dict = {}
            declined_days: dict = {}
            declined_rounds: dict = {}
            unfed_days: dict = {}
            if tournament.name not in _SLAM_FEEDS:
                for day_ in (today - timedelta(days=1), today,
                             today + timedelta(days=1), today + timedelta(days=2)):
                    try:
                        fd = await schedule_feeds.build_day_document(
                            db, tournament, draws, day_, season_year, tz)
                    except Exception as exc:           # noqa: BLE001
                        fd = None
                        logger.info("feeds failed for %s %s: %s", tournament.name, day_,
                                    describe_exception(exc))
                    if fd and fd.get("declined"):
                        declined_days[day_] = fd["declined"]
                        # The rounds it knew anyway, kept apart so the
                        # note's contract does not change (its own test
                        # passes a bare reason string).
                        declined_rounds[day_] = fd.get("rounds") or {}
                    elif fd and fd.get("unfed"):
                        unfed_days[day_] = fd["unfed"]
                    elif fd:
                        feed_days[day_] = fd
            if feed_days:
                await _ingest_feed_days(tournament, draws, feed_days, tz)

            oop_date, atp_labels, wta_labels = None, 0, 0
            resp = None
            # The day the PDF is FOR, when it is to be ingested — never one the
            # feeds already hold, or the two would take turns writing it.
            pdf_date, pdf_atp, pdf_wta = None, 0, 0
            want_pdf = ((not feed_days or bool(declined_days))
                        and (tournament.name in _SLAM_FEEDS or schedule_feeds.PDF_FALLBACK))
            try:
                if want_pdf:
                    async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
                        resp = await client.get(url)
                if resp is not None and resp.status_code == 200:
                    pdf_date, pdf_atp, pdf_wta = _parse_oop(resp.content)
                    if pdf_date is not None and pdf_date in feed_days:
                        pdf_date = None
                elif resp is not None and resp.status_code != 404:
                    resp.raise_for_status()
            except Exception as exc:
                if not is_transient_http_error(exc):
                    await app_log("warning", "order_of_play",
                                  f"OOP fetch failed for '{tournament.name}': "
                                  f"{describe_exception(exc)}",
                                  dedup_key=f"oop_fetch_{tournament.id}", dedup_hours=6)
                # The feeds' days still stand; only a tournament with nothing
                # else keeps yesterday's value for the next tick to re-check.
                if not feed_days:
                    continue
                resp, pdf_date = None, None

            # The chip's day: today when a source has it, else the next.
            have = {d: (f["atp"], f["wta"]) for d, f in feed_days.items()}
            if pdf_date is not None:
                have[pdf_date] = (pdf_atp, pdf_wta)
            if have:
                oop_date = (today if today in have
                            else min((d for d in have if d > today), default=max(have)))
                atp_labels, wta_labels = have[oop_date]

            # THE SLAMS HOST THEIR OWN SHEET. When neither tour file yielded a
            # dated order of play and this tournament is one the tours never
            # cover, ingest its own feed instead. Everything downstream is the
            # normal path: the chip URL is the day's human-readable schedule
            # page, and the label counts drive the same gender coverage rule.
            if oop_date is None and tournament.name in _SLAM_FEEDS:
                try:
                    fed = await _refresh_slam_feed(
                        tournament, draws, season_year, today)
                except Exception as exc:
                    if not is_transient_http_error(exc):
                        await app_log(
                            "warning", "order_of_play",
                            f"Slam schedule feed failed for "
                            f"'{tournament.name}': {describe_exception(exc)}",
                            dedup_key=f"oop_feed_{tournament.id}", dedup_hours=6)
                    fed = None
                if fed:
                    oop_date, url, src_tour = fed["date"], fed["url"], "ATP"
                    atp_labels, wta_labels = fed["atp"], fed["wta"]

            # WHAT COUNTS AS A SHEET WORTH STORING.
            #
            # This was `oop_date == today`, and that one `==` meant the site
            # could never show tomorrow's order of play. Tournaments publish the
            # next day's sheet the evening before — that is the whole point of
            # an order of play — and every one of them was fetched, parsed and
            # thrown away for being dated tomorrow. Winston-Salem's first main
            # draw day was sitting on protennislive for hours while the site
            # showed nothing.
            #
            # It also broke the other way. `today` is UTC and venues are not:
            # from 8pm in Cincinnati the server has already rolled over, so the
            # sheet for the day still being PLAYED is dated "yesterday" and was
            # dropped for the rest of the evening — exactly when scores matter.
            #
            # The guard was only ever meant to stop a FINISHED tournament's last
            # sheet being rewritten on every tick, so that is all it does now:
            # reject the genuinely stale, accept today, tomorrow, and yesterday
            # for the venues still living in it.
            fresh = oop_date is not None and oop_date >= today - timedelta(days=1)
            covers_atp = atp_labels >= _MIN_TOUR_LABELS

            # Store the schedule itself, not just the link. Only when the file
            # is current: an out-of-date PDF would otherwise write a finished
            # tournament's last day over and over on every tick.
            if (pdf_date is not None and pdf_date >= today - timedelta(days=1)
                    and resp is not None and resp.status_code == 200):
                try:
                    from app.services import schedule as schedule_svc
                    from app.services.db_retry import with_write_retry

                    # RETRIED, AND SEPARATELY. Both halves write, so both can
                    # lose their snapshot to a competing writer — see
                    # db_retry for why waiting cannot fix that and a fresh
                    # session can. Losing this to a lock is not the small
                    # miss it looks like: the sheet's rows go unwritten AND
                    # the PDF never reaches the verifier, so a parse bug in
                    # that revision goes unexamined too.
                    #
                    # Two calls, two retries, because they fail independently
                    # and re-running the pair would re-enter an ingest that
                    # already succeeded — which the sha256 guard would then
                    # skip, silently costing the estimate pass its input.
                    # THE WTA'S OWN JSON IN PLACE OF ITS PDF (owner, 2026-09-18)
                    # on the days the sheet carries no men. The PDF is still
                    # fetched above — it decides the day, the chip and the
                    # coverage — but the rows come from the feed, which needs
                    # no parsing and no verifier. A feed that fails or is
                    # empty leaves the sheet in charge, as before.
                    #
                    # A feed that DECLINES the day (nothing for it, or a court
                    # it cannot name) hands it to the sheet, and the sheet
                    # takes it back even over rows the feed wrote. A feed that
                    # FAILS says nothing about the day, so the sheet then only
                    # moves the page if the sheet itself moved (reclaim=False)
                    # — or one timeout would flip every row and back again.
                    # THE LAST RESORT: no feed had this tournament's day.
                    feed_doc, feed_failed = None, False

                    async def _ingest(sdb):
                        t = await sdb.get(type(tournament), tournament.id)
                        if feed_doc:
                            return await schedule_svc.ingest_document(
                                sdb, t, pdf_date, feed_doc["url"], feed_doc["bytes"],
                                tour="WTA", parser=feed_doc["parser"], queue_verify=False)
                        return await schedule_svc.ingest_document(
                            sdb, t, pdf_date, url, resp.content, tour=src_tour,
                            reclaim=not feed_failed,
                            last_modified=resp.headers.get("last-modified"))

                    async def _estimates(sdb):
                        return await schedule_svc.recompute_expected_starts(
                            sdb, tournament.id, pdf_date,
                            venue_tz=next((d.venue_timezone for d in draws
                                           if d.venue_timezone), None))

                    # THE ROUND THE SHEET DOES NOT PRINT, from the feed that
                    # declined the day. The ATP's order of play often carries
                    # no round column at all — Chengdu's 22 September
                    # qualifying had none, so every row showed a blank where
                    # Q1 belongs while Hangzhou, whose feed was not declined,
                    # showed Q1 (owner, 2026-09-21). The feed was declined for
                    # want of COURTS, which is the half the sheet is better at;
                    # it still knew every round. Fills NULLs only, so anything
                    # the sheet did state keeps standing.
                    feed_rounds = declined_rounds.get(pdf_date) or {}

                    async def _rounds(sdb):
                        return await schedule_svc.fill_rounds_from_feed(
                            sdb, tournament.id, pdf_date, feed_rounds)

                    async with schedule_svc.day_write_lock:   # see schedule.day_write_lock
                        ingested = await with_write_retry(_ingest, what=f"oop ingest {tournament.id}")
                        await with_write_retry(_estimates, what=f"oop estimates {tournament.id}")
                        if feed_rounds:
                            named = await with_write_retry(
                                _rounds, what=f"oop rounds {tournament.id}")
                            if named:
                                logger.info("%s %s: named %d round(s) from the "
                                            "feed the sheet did not print",
                                            tournament.name, pdf_date, named)
                    if not (ingested or {}).get("skipped"):
                        level, msg, key = _pdf_fallback_note(
                            tournament, pdf_date, declined_days, unfed_days)
                        await app_log(level, "order_of_play", msg,
                                      dedup_key=key, dedup_hours=24)
                except Exception as exc:
                    await app_log("warning", "order_of_play",
                                  f"Schedule ingest failed for '{tournament.name}': "
                                  f"{describe_exception(exc)}",
                                  dedup_key=f"sched_ingest_{tournament.id}", dedup_hours=6)

            for draw in draws:
                # The men's draw only gets the WTA file when that file actually
                # lists ATP matches — true at a shared site, false when the
                # tours are in different cities the same week.
                #
                # ...and the draw has to be running today in its own right. One
                # tournament row can hold draws that are not the same event at
                # all: Hamburg 2026 carries the men from 18 May and the women
                # from 20 July, so "this tournament's PDF" is meaningless
                # without asking which draw. Without this, the only thing
                # standing between the May men's draw and a July women's
                # schedule is the ATP-label count happening to come back zero.
                # Which draws this file actually covers.
                #
                # From the ATP's own file, the men's draw is covered outright —
                # a single-tour sheet has no reason to label anything "ATP", so
                # the label count is zero and testing it would exclude the very
                # draw the file is for.
                #
                # From a WTA file, the women's draw is covered outright, and the
                # men's only when the sheet really does list ATP matches: true
                # at a shared venue, false when the tours are in different
                # cities the same week.
                if src_tour == "ATP":
                    gender_ok = draw.gender == "M" or wta_labels >= _MIN_TOUR_LABELS
                else:
                    gender_ok = draw.gender == "F" or covers_atp
                covered = fresh and gender_ok and _running(draw, today)
                new_url = url if covered else None
                # BUFFERED, NOT ASSIGNED. These draws are attached to the
                # session that lives across this whole loop, and the loop
                # fetches protennislive between iterations — the alert that
                # broke this open showed 19 oop_checked_at stamps spaced 1.6s
                # apart flushed as one batch. The first mid-loop autoflush
                # took SQLite's only write lock and the job then held it for
                # minutes of network time: the 2026-08-25 storm, whole and
                # entire. The writer never waits on the network — stamps
                # accumulate here and land in one short transaction below.
                stamp = pending.setdefault(draw.id, {})
                if covered and draw.oop_first_seen_at is None:
                    stamp["oop_first_seen_at"] = datetime.now(timezone.utc)
                if draw.oop_url != new_url or draw.oop_date != (oop_date if covered else None):
                    stamp["oop_url"] = new_url
                    stamp["oop_date"] = oop_date if covered else None
                    updated += 1
                stamp["oop_checked_at"] = datetime.now(timezone.utc)

    # The write pass: everything the fetches learned, in one brief holder of
    # the lock, on a session that has never touched the network.
    if pending:
        async with AsyncSessionLocal() as wdb:
            # LOAD EVERY ROW BEFORE DIRTYING ANY OF THEM. `wdb.get` is a query,
            # and a query on a session holding a dirty row autoflushes it — so
            # fetching the second draw took SQLite's write slot to write the
            # first, once per draw, in the middle of the loop. The transaction
            # was still short, but it grabbed the lock N times instead of once
            # and each grab could sit out the full 30s busy_timeout: that is
            # the shape of the 19:48/20:41/23:27 failures on 2026-08-30, whose
            # SQL was a single-row `UPDATE draws SET oop_checked_at`.
            # Read first, mutate second, flush once at commit.
            rows = {d.id: d for d in (await wdb.execute(
                select(Draw).where(Draw.id.in_(list(pending))))).scalars()}
            for did, fields in pending.items():
                d = rows.get(did)
                if d is None:
                    continue
                for k, v in fields.items():
                    setattr(d, k, v)
            await wdb.commit()

    await _alert_missing_schedule()
    return updated


async def _alert_missing_schedule() -> None:
    """Say so when a tournament being played has no order of play stored.

    THE POINT. Everything above is a mechanism, and the mechanism failed
    silently for weeks: a single `==` meant a sheet dated tomorrow was fetched,
    parsed and discarded, so the site could never show the next day's play and
    nothing anywhere said so. The fetch succeeded. The parse succeeded. There
    was simply no schedule, and no reason for anyone to look until a person
    noticed the page was empty.

    So this asks the only question that matters — is there a schedule for a
    tournament that is being played — and asks it of the STORED RESULT rather
    than of any step that produces it. It stays true if the fetching, the
    parsing or the freshness rule are rewritten, and it catches causes nobody
    has thought of yet.

    Asked of the VENUE's day, not the server's — see `_venue_today`. A sheet is
    about a tennis day, and at a UTC-negative venue the server rolls into
    tomorrow while tonight's matches are still on court, so "nothing on or
    after today" was true of a day nobody had played yet.
    """
    async with AsyncSessionLocal() as db:
        # The draws themselves, aggregated here rather than in SQL: the question
        # is asked per tournament but answered per draw, because whether a start
        # date may be believed is a fact about the individual draw's wiki page
        # (see _confirmed_start). A tournament can hold one draw whose infobox
        # has been read and one still carrying discovery's placeholder, and
        # func.min() over the two cannot tell them apart.
        by_tournament: dict[int, tuple[str, list]] = {}
        for tournament, draw in (await db.execute(
                select(Tournament, Draw)
                .join(Draw, Draw.tournament_id == Tournament.id)
                .where(Draw.status != "completed",
                       Draw.start_date.isnot(None)))).all():
            by_tournament.setdefault(tournament.id, (tournament.name, []))[1].append(draw)

        accused = []
        for tid, (name, draws) in by_tournament.items():
            venue_tz = max((d.venue_timezone for d in draws if d.venue_timezone),
                           default=None)
            today = _venue_today(venue_tz)
            starts = [s for s in (_as_date(d.start_date) for d in draws) if s]
            ends = [e for e in (_as_date(d.end_date) for d in draws) if e]
            start = min(starts) if starts else None
            end = max(ends) if ends else None
            # Under way, or starting tomorrow — the point by which a sheet
            # exists in the real world, so its absence here is ours.
            if start is None or start > today + timedelta(days=1):
                continue
            if end is not None and end < today:
                continue
            have = (await db.execute(
                select(func.count()).select_from(ScheduleEntry).where(
                    ScheduleEntry.tournament_id == tid,
                    ScheduleEntry.play_date >= today))).scalar_one()
            if have:
                continue
            accused.append((tid, name, draws, today, start, end))

    # Out of the session before anything touches the network — confirming a
    # start date is an HTTP round trip, and a read transaction left open across
    # one is how a cheap check becomes a long one.
    for tid, name, draws, today, start, end in accused:
        # About to accuse — so confirm the date being accused on. Last, because
        # by here every cheaper reason to stay quiet has been ruled out.
        refined = [await _confirmed_start(draw, stored)
                   for draw, stored in ((d, _as_date(d.start_date)) for d in draws)
                   if stored]
        confirmed = min(refined) if refined else start
        if confirmed > today + timedelta(days=1):
            await _stand_down(
                f"oop_no_schedule_not_due_{tid}", {"tournament_id": tid},
                name, draws[0].gender, start, confirmed, "order of play stored")
            continue
        start = confirmed
        await app_log(
            "warning", "order_of_play",
            f"No order of play stored for '{name}' — it runs {start} to {end} "
            f"and there is nothing on or after {today}. The sheet is "
            f"published by now, so this is a fetch or a parse failing "
            f"quietly, not a tournament that has not posted one.",
            {"tournament_id": tid, "start_date": str(start),
             "end_date": str(end)},
            dedup_key=f"oop_missing_{tid}", dedup_hours=12)
