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
import re
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Optional

import httpx
from sqlalchemy import func, or_, select

from app.database import AsyncSessionLocal
from app.models.schedule import ScheduleEntry
from app.models.tournament import Draw, Tournament
from app.services.http_errors import is_transient_http_error, describe_exception
from app.services.rankings import _norm
from app.services.system_log import app_log

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


async def _alert_missing_oop() -> None:
    """Say so when a tournament is under way and we still have no order of play.

    Silence is the failure mode worth guarding against here: an unknown ATP id,
    a renamed file, a changed URL scheme all present identically — as a
    tournament that simply never shows a schedule. Once play has started, that
    is unambiguous enough to be worth an email.
    """
    today = date.today()
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
        start = _as_date(draw.start_date)
        end = _as_date(draw.end_date)
        if not start or start > today:
            continue                      # not started; nothing is wrong yet
        if end and today > end:
            continue                      # over, and it never had one — too late to matter
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


async def refresh_order_of_play() -> int:
    """
    Point every eligible draw at today's OOP, or at nothing.

    Clearing matters as much as setting: a draw that had a link yesterday must
    lose it the moment the file stops being current, or the tournament ends and
    the page keeps offering a PDF that is frozen on the final day's play.
    """
    today = date.today()
    updated = 0

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

            oop_date, atp_labels, wta_labels = None, 0, 0
            try:
                async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
                    resp = await client.get(url)
                if resp.status_code == 200:
                    oop_date, atp_labels, wta_labels = _parse_oop(resp.content)
                elif resp.status_code != 404:
                    resp.raise_for_status()
            except Exception as exc:
                if not is_transient_http_error(exc):
                    await app_log("warning", "order_of_play",
                                  f"OOP fetch failed for '{tournament.name}': "
                                  f"{describe_exception(exc)}",
                                  dedup_key=f"oop_fetch_{tournament.id}", dedup_hours=6)
                continue  # leave yesterday's value; the next tick re-checks

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
            if fresh and resp.status_code == 200:
                try:
                    from app.services import schedule as schedule_svc
                    async with AsyncSessionLocal() as sdb:
                        t = await sdb.get(type(tournament), tournament.id)
                        await schedule_svc.ingest_document(
                            sdb, t, oop_date, url, resp.content, tour=src_tour)
                        await schedule_svc.recompute_expected_starts(
                            sdb, tournament.id, oop_date,
                            venue_tz=next((d.venue_timezone for d in draws
                                           if d.venue_timezone), None))
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
                if covered and draw.oop_first_seen_at is None:
                    draw.oop_first_seen_at = datetime.now(timezone.utc)
                if draw.oop_url != new_url or draw.oop_date != (oop_date if covered else None):
                    draw.oop_url = new_url
                    draw.oop_date = oop_date if covered else None
                    updated += 1
                draw.oop_checked_at = datetime.now(timezone.utc)

        await db.commit()

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
    """
    today = date.today()
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Tournament.id, Tournament.name,
                   func.min(Draw.start_date), func.max(Draw.end_date))
            .join(Draw, Draw.tournament_id == Tournament.id)
            .where(Draw.status != "completed",
                   Draw.start_date.isnot(None))
            .group_by(Tournament.id))).all()

        for tid, name, start, end in rows:
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
            await app_log(
                "warning", "order_of_play",
                f"No order of play stored for '{name}' — it runs {start} to {end} "
                f"and there is nothing on or after {today}. The sheet is "
                f"published by now, so this is a fetch or a parse failing "
                f"quietly, not a tournament that has not posted one.",
                {"tournament_id": tid, "start_date": str(start),
                 "end_date": str(end)},
                dedup_key=f"oop_missing_{tid}", dedup_hours=12)
