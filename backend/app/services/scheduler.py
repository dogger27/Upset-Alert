"""
Background scheduler:
- Auto-discovers and adds tournaments daily for current + next 2 years
- Real-time EventStreams listener for tournament draw page updates
- Dynamic subscriptions: subscribes on tournament add, unsubscribes on completion
"""

import asyncio
import functools
import logging
import traceback
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import case, func, select
from sqlalchemy.exc import OperationalError

from app.database import AsyncSessionLocal
from app.models.tournament import Draw, DrawEntry, Match
from app.services.espn_monitor import ESPNMonitor
from app.services.eventstream import EventStreamListener
from app.services.http_errors import describe_exception, is_transient_http_error
from app.services.push_content import tour_label
from app.services.scraper import WikiPageNotFound

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()
eventstream = EventStreamListener()
espn_monitor = ESPNMonitor()


async def _auto_discover_tournaments() -> None:
    logger.info("=== Starting tournament auto-discovery ===")
    from app.services.tournament_sync import sync_season

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        current_year = now.year

        for year in [current_year, current_year + 1]:
            logger.info("Discovering tournaments for %d...", year)
            try:
                summary = await sync_season(db, year, scrape_new=True)
                logger.info("✓ Sync complete for %d: %s", year, summary)
            except Exception as exc:
                await db.rollback()
                logger.warning("Failed to sync tournaments for %d: %s", year, exc)
                # A missing season page for a future year is expected — Wikipedia
                # won't have one until the season is underway. Skip app_log
                # entirely. Matched on the exception type rather than on the text
                # of its message, which was one reworded f-string away from
                # silently becoming an error again.
                is_future_not_found = year > current_year and isinstance(exc, WikiPageNotFound)
                if not is_future_not_found:
                    from app.services.system_log import app_log
                    # Not suppressed for transient errors like the polling jobs
                    # are: discovery runs once a day and is deduped, so a row
                    # here is at most one a day and does mean Wikipedia was
                    # unreachable at the moment it mattered.
                    err = describe_exception(exc)
                    await app_log("error", "scheduler", f"Tournament discovery failed for {year}: {err}",
                                  {"year": year, "error": err})

    # Sync EventStream subscriptions after DB is updated
    await _sync_subscriptions()


# How far ahead of a draw's expected release date to start polling for it.
# Kept modest because this job runs every 30 minutes and the Wikipedia response
# cache expires just under that (25 min), so each extra day of lead is real
# request volume, not cache hits. EventStreams handles real-time detection; this
# is the backstop, and 3 days is enough headroom for the estimate to be wrong in
# the safe direction without widening the sweep much.
POLL_LEAD_DAYS = 3


async def _refresh_active_tournaments(force_refresh: bool = False) -> None:
    """
    Catch-up scrape (every 30 min — see start_scheduler) covering two groups:

    1. Active tournaments — start_date within the last 14 days, not yet completed.
       Catches match results / tournament completion that EventStreams may have missed.

    2. Upcoming tournaments awaiting draw release — expected DA or Qual date is
       within POLL_LEAD_DAYS but the draw hasn't been confirmed yet (no
       draw_released_*_at). This is what sets the checkmarks when players are
       placed in the draw.

    The lead time on group 2/3 matters more than it looks. Polling exactly from
    the expected date made the estimate self-confirming: a draw predicted for
    start-minus-one was not looked at until the day before play, so a draw that
    had been up for three days was recorded as "released one day before start",
    which fed the median that produced the next late prediction. Starting early
    lets the observation disagree with the estimate.
    """
    from sqlalchemy import or_
    from app.routers.tournaments import _do_scrape

    today = date.today()
    poll_from = today + timedelta(days=POLL_LEAD_DAYS)

    # Identify the work as plain tuples, not ORM instances. A scrape that fails
    # rolls its session back, and rollback expires every instance still attached
    # to it — so a Draw read before the loop would need a lazy reload afterwards,
    # which is sync IO inside the event loop (MissingGreenlet) and killed the rest
    # of the cycle. Tuples can't expire; the Draw is re-fetched below per draw.
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Draw.id, Draw.name, Draw.wiki_page_title, Draw.wiki_page_id).where(
                Draw.status != "completed",
                or_(
                    # Group 1: active window (started within last 14 days)
                    (
                        Draw.start_date.isnot(None) &
                        (Draw.start_date <= today) &
                        (Draw.start_date >= today - timedelta(days=14))
                    ),
                    # Group 2: upcoming — DA draw date is near, not yet confirmed
                    (
                        Draw.draw_release_direct.isnot(None) &
                        (Draw.draw_release_direct <= poll_from) &
                        Draw.draw_released_direct_at.is_(None)
                    ),
                    # Group 3: upcoming — Qual date is near, not yet confirmed
                    (
                        Draw.draw_release_qualifiers.isnot(None) &
                        (Draw.draw_release_qualifiers <= poll_from) &
                        Draw.draw_released_qualifiers_at.is_(None)
                    ),
                )
            )
        )
        tournaments = result.all()

    logger.info("Daily refresh: %d tournaments to check", len(tournaments))
    for t_id, t_name, t_wiki, t_page_id in tournaments:
        await asyncio.sleep(5)  # throttle Wikipedia requests to avoid 429s
        # One session per draw, so a failed scrape's rollback is contained to the
        # draw that caused it instead of poisoning every draw still to come.
        async with AsyncSessionLocal() as db:
            try:
                t = await db.get(Draw, t_id)
                if t is None:
                    continue  # deleted between the sweep and now
                prev_status = t.status

                await _do_scrape(t, db, force_refresh=force_refresh)
                await db.commit()
                logger.info("Refreshed %s %s (%s)", t.year, t_name, t.gender)

                # Prefetch H2H and DOB for any new matchups/players (uses own sessions)
                from app.services.h2h import prefetch_h2h_for_draw
                from app.services.rankings import prefetch_dob_for_draw
                await prefetch_h2h_for_draw(t_id)
                await prefetch_dob_for_draw(t_id)

                # "Draw released" email dispatch is centralized in
                # _notify_pending_draw_releases (runs on its own interval) so every
                # scrape path — this one, season-page edits, EventStreams, manual
                # admin refresh — is covered uniformly. Only tournament-complete is
                # fired directly here (it has its own completion_notified_at guard).
                from app.services.notifications import notify_tournament_complete
                just_completed = prev_status != "completed" and t.status == "completed"
                if just_completed:
                    asyncio.create_task(notify_tournament_complete(t_id))
            except WikiPageNotFound as exc:
                # Not a failure while the draw has never resolved a page: the
                # singles page is created on Wikipedia around publication day,
                # so every upcoming draw returns this on every poll for the
                # whole POLL_LEAD_DAYS window — one row per draw per 30 min,
                # for days, describing the normal state of waiting. There is
                # nothing for a human to do with it, and _check_draw_health
                # already escalates the same condition once it is genuinely
                # overdue (see its Check 2), which is the point at which
                # someone can act.
                #
                # A page_id that resolved before and now 404s is the opposite
                # case — the page was deleted, merged or the id went stale, and
                # nothing else watches for it — so that still gets logged.
                await db.rollback()
                if t_page_id is None:
                    logger.debug("Draw page not up yet for %s: %s", t_wiki, exc)
                    # The singles page is missing, but the EVENT page is up and
                    # states when the tournament runs. Take the dates from it
                    # now rather than waiting for the draw: discovery seeded
                    # start_date with the Monday of the tournament's week, and
                    # for an extended-format 1000 or Slam that Monday is days
                    # early. A start_date already in the past makes the draw read
                    # as "active" the moment it is released, which LOCKS picks —
                    # the release that should open a Masters 1000 would close it.
                    # See fetch_event_dates; 2026 Cincinnati was the live case.
                    await _refresh_dates_from_event_page(t_id)
                else:
                    logger.warning("Resolved wiki page %s vanished for %s: %s",
                                   t_page_id, t_wiki, exc)
                    from app.services.system_log import app_log
                    await app_log("error", "scheduler",
                                  f"Wiki page for '{t_name}' no longer exists: {exc}",
                                  {"tournament_id": t_id, "tournament_name": t_name,
                                   "wiki_title": t_wiki, "wiki_page_id": t_page_id,
                                   "error": str(exc)},
                                  dedup_key=f"page_vanished_{t_id}", dedup_hours=24.0)
            except Exception as exc:
                await db.rollback()
                # Transient first, and via the shared test rather than a
                # hand-written tuple — the tuple that used to live here listed
                # three httpx classes and the other call sites listed two
                # different ones, which is how ReadTimeout ended up silenced in
                # one place and alerted from another.
                if is_transient_http_error(exc):
                    logger.debug("Network blip refreshing %s: %s",
                                 t_wiki, describe_exception(exc))
                    continue
                tb = traceback.format_exc()
                err = describe_exception(exc)
                logger.warning("Failed to refresh %s: %s\n%s", t_wiki, err, tb)
                from app.services.system_log import app_log
                await app_log("error", "scheduler", f"Failed to refresh '{t_name}': {err}",
                              {"tournament_id": t_id, "tournament_name": t_name,
                               "wiki_title": t_wiki, "error": err,
                               "traceback": tb},
                              dedup_key=f"refresh_fail_{t_id}_{type(exc).__name__}", dedup_hours=1.0)


async def _refresh_dates_from_event_page(draw_id: int) -> None:
    """
    Correct an upcoming draw's dates from its general event page.

    Runs only on the WikiPageNotFound path — i.e. exactly while a draw is
    upcoming and carrying discovery's week-Monday placeholder. Once the singles
    page exists, _do_scrape reads the same infobox and this stops being reached.

    Deliberately narrow about what it will overwrite:
      * never touches an active or completed draw — past start, Wikipedia lags
        real play and the scraper's own date logic already owns this;
      * never touches a draw whose release has been stamped, so a date cannot
        move under picks that are already open;
      * writes only on an actual change, so an unchanged date is not a write on
        every poll of every upcoming draw.

    Own session, and never raises: this is a best-effort side errand hanging off
    an exception handler, and it must not turn a handled "page isn't up yet" into
    an unhandled failure that skips the rest of the sweep.
    """
    from app.services.scraper import fetch_event_dates

    try:
        async with AsyncSessionLocal() as db:
            d = await db.get(Draw, draw_id)
            if d is None or d.status in ("active", "completed"):
                return

            start, end = await fetch_event_dates(d.wiki_page_title, d.year, d.gender)
            if not start:
                return

            # A released draw's DATES are left alone — people are picking from it
            # and the schedule is settled. Its DEADLINE is not: that is derived
            # from the start date, and a draw released after a date correction
            # can be carrying one computed from the date that was replaced. 2026
            # Cincinnati was released the day after its dates were fixed and sat
            # advertising a deadline three days in the past, which this guard,
            # applied to both, would have made permanent.
            allow_date_change = d.draw_released_direct_at is None

            # The deadline is day 1's first ball, so it is a function of
            # start_date and moves with it. Correcting one without the other is
            # what left 2026 Cincinnati open for picks while advertising a
            # deadline three days in the past.
            #
            # Deliberately NOT behind the "did the dates change" test: a
            # deadline can be stale while the dates are already right — which is
            # exactly the state that bug left behind, and returning early on
            # matching dates would have made it permanent. Re-derived every
            # pass, and sync_closing_time is a no-op when it already agrees.
            from app.services.tournament_schedule import apply_schedule, sync_closing_time

            old_start, old_end = d.start_date, d.end_date
            dates_moved = allow_date_change and (
                start != old_start or (end and end != old_end)
            )
            if dates_moved:
                d.start_date = start
                if end:
                    d.end_date = end

            apply_schedule(d)
            closing_moved = sync_closing_time(d)
            if not dates_moved and not closing_moved:
                return
            await db.commit()

            if not dates_moved:
                from app.services.system_log import app_log
                await app_log(
                    "info", "scraper",
                    f"Corrected the pick deadline for {d.year} {d.name} "
                    f"({tour_label(d.gender)}): now {d.closing_time} UTC, from a "
                    f"start date of {d.start_date}",
                    {"draw_id": d.id, "closing_time": str(d.closing_time),
                     "start_date": str(d.start_date)},
                )
                return

            from app.services.system_log import app_log
            await app_log(
                "info", "scraper",
                f"Corrected dates for {d.year} {d.name} ({tour_label(d.gender)}) from the event page: "
                f"{old_start} → {start}, {old_end} → {d.end_date}"
                + (f"; pick deadline moved to {d.closing_time} UTC" if closing_moved else ""),
                {"draw_id": d.id, "old_start": str(old_start), "new_start": str(start),
                 "old_end": str(old_end), "new_end": str(d.end_date),
                 "closing_time": str(d.closing_time), "closing_moved": closing_moved,
                 "wiki_page_title": d.wiki_page_title},
            )
            logger.info("Corrected dates for draw %d (%s): %s → %s",
                        d.id, d.name, old_start, start)
    except Exception as exc:
        logger.debug("Event-page date refresh failed for draw %d: %s", draw_id, exc)


def _season_pages() -> set[str]:
    year = datetime.now(timezone.utc).year
    return {f"{year} ATP Tour", f"{year} WTA Tour"}


async def _on_season_page_edit(season_title: str) -> None:
    """
    Called whenever a season overview page (e.g. "2026 ATP Tour") is edited.

    The season page is authoritative for draw links: when a tournament's Singles
    page appears (or changes), it shows up as a new/corrected wiki_page_title here.
    We therefore:
      1. Correct any wiki_page_title that changed, clearing the stale wiki_page_id
         so the next scrape resolves it fresh.
      2. Immediately re-scrape every non-completed tournament that either had its
         title corrected OR hasn't had its draw confirmed yet and its expected draw
         date has already arrived — because the season-page edit is the signal that
         draw links are being added/updated.
    """
    import re
    from app.services.scraper import fetch_wikitext
    from app.services.discovery import parse_season_schedule
    from app.routers.tournaments import _do_scrape

    m = re.match(r'^(\d{4}) (ATP|WTA) Tour$', season_title)
    if not m:
        return
    year = int(m.group(1))
    gender = 'M' if m.group(2) == 'ATP' else 'F'

    try:
        wikitext, _ = await fetch_wikitext(season_title, force_refresh=True)
        discovered = parse_season_schedule(wikitext, year, gender)

        today = date.today()
        to_scrape: list[int] = []  # tournament IDs to scrape

        async with AsyncSessionLocal() as db:
            # Guessed titles need the same combined-event suffix adjustment
            # that discover_tournaments applies, or this handler would flap
            # titles back to the raw gendered guess on every season edit.
            # The other tour's base pages come from the DB here.
            from app.services.discovery import adjust_guessed_titles, title_bases
            other = await db.execute(
                select(Draw.wiki_page_title).where(
                    Draw.year == year,
                    Draw.gender == ("F" if gender == "M" else "M"),
                )
            )
            adjust_guessed_titles(discovered, title_bases(other.scalars().all()))
            disc_by_name = {d.name: d for d in discovered if d.wiki_page_title}

            result = await db.execute(
                select(Draw).where(
                    Draw.year == year,
                    Draw.gender == gender,
                    Draw.status != "completed",
                )
            )
            tournaments = result.scalars().all()

            title_updated = 0
            for t in tournaments:
                d = disc_by_name.get(t.name)
                # A guessed title may only correct an unresolved record;
                # explicit season-page links correct unconditionally.
                if (
                    d and d.wiki_page_title != t.wiki_page_title
                    and (not d.title_is_guess or t.wiki_page_id is None)
                ):
                    logger.info(
                        "Season page edit: correcting %s title %r → %r",
                        t.name, t.wiki_page_title, d.wiki_page_title,
                    )
                    t.wiki_page_title = d.wiki_page_title
                    t.wiki_page_id = None  # clear stale ID — scraper will resolve fresh
                    title_updated += 1
                    to_scrape.append(t.id)

                # Also immediately re-scrape any upcoming tournament whose expected
                # draw date has arrived but draw isn't confirmed yet — the season edit
                # is the signal that draw links are live on the season page.
                if (
                    t.id not in to_scrape
                    and t.draw_released_direct_at is None
                    and t.draw_release_direct is not None
                    and t.draw_release_direct <= today
                ):
                    to_scrape.append(t.id)

            if title_updated:
                await db.commit()
                logger.info(
                    "Season edit %s: corrected %d title(s), queued %d scrape(s)",
                    season_title, title_updated, len(to_scrape),
                )
            else:
                logger.info(
                    "Season edit %s: no title changes; queued %d pending-draw scrape(s)",
                    season_title, len(to_scrape),
                )

        # Scrape outside the session that did the title updates
        if to_scrape:
            async with AsyncSessionLocal() as db:
                for tid in to_scrape:
                    t = await db.get(Draw, tid)
                    if not t:
                        continue
                    try:
                        await asyncio.sleep(2)  # throttle Wikipedia requests
                        await _do_scrape(t, db, force_refresh=True)
                        await db.commit()
                        logger.info(
                            "Season-edit scrape: %s %s (draw now: %s)",
                            t.year, t.name, t.draw_released_direct_at,
                        )
                        # "Draw released" email dispatch is centralized in
                        # _notify_pending_draw_releases — see comment there.
                    except Exception as exc:
                        logger.warning(
                            "Season-edit scrape failed for %s: %s", t.wiki_page_title, exc,
                        )
                        await db.rollback()

        await _sync_subscriptions()
    except Exception as exc:
        logger.warning("Failed to handle season page edit %s: %s", season_title, exc)


async def _refresh_weekly_rankings() -> None:
    """
    Weekly rankings refresh (Sunday 6pm PDT).
    Scrapes TE for both genders if this week's data is missing.
    Errors are logged to system_logs; rankings may occasionally not be published
    this week (grand slam weeks, ATP/WTA schedule gaps).
    """
    from app.services.rankings import ensure_te_week
    from app.services.system_log import app_log

    today = date.today()
    week_date = today - timedelta(days=today.weekday())  # Monday anchor

    logger.info("Weekly rankings check: week %s", week_date)
    try:
        scraped_any = False
        async with AsyncSessionLocal() as db:
            for gender in ("M", "F"):
                scraped = await ensure_te_week(gender, week_date, db, log_errors=True)
                if scraped:
                    scraped_any = True
            if scraped_any:
                await db.commit()

        if scraped_any:
            logger.info("Weekly rankings: stored new data for week %s", week_date)
        else:
            logger.info("Weekly rankings: week %s already populated or not yet published", week_date)
    except Exception as exc:
        err = describe_exception(exc)
        if is_transient_http_error(exc):
            # _check_rankings_health notices if the week never lands.
            logger.debug("Weekly rankings source unreachable: %s", err)
            return
        logger.error("Weekly rankings job failed: %s", err)
        await app_log("error", "rankings", f"Weekly rankings job failed: {err}",
                      {"week_date": str(week_date), "error": err},
                      dedup_key="weekly_rankings_job_fail", dedup_hours=12)


async def _refresh_elo() -> None:
    from app.services.rankings import refresh_elo_ratings
    await refresh_elo_ratings()


# How long a substantially-complete draw must stay stable (not reverted by a
# later scrape) before the "draw released" email fires. Wikipedia editors often
# place seeded players into their bracket slots as soon as the entry list is
# announced, well before Round-1 pairings are final — that state can briefly
# cross the "substantially complete" threshold and then get corrected within
# minutes. Waiting this long out lets any such flicker settle before emailing.
DRAW_RELEASE_NOTIFY_COOLDOWN = timedelta(minutes=10)

# A week's draws are announced together, so exactly one email covers the week.
# It waits for every draw in that week to be released — see the hold below.


async def _notify_pending_draw_releases() -> None:
    """
    Centralized, idempotent "draw released" email dispatch.

    Every code path that can set draw_released_direct_at (this scheduler's
    daily refresh, season-page-edit re-scrapes, the real-time EventStreams
    listener, and the manual admin "refresh draw" endpoint) funnels through
    _do_scrape, which stamps draw_release_detected_at the first time a draw is
    observed substantially complete. Rather than each of those call sites
    separately trying to detect "was this just released" (which is how a
    tournament like Swedish Open could be released via EventStreams and never
    get an email, since only two of the four paths had that check), this job
    periodically scans for draws that have been stable for the cooldown and
    haven't been notified yet — covering all paths uniformly, and only firing
    once the release has proven stable (fixing the Athens Open early-fire case).
    """
    now = datetime.now(timezone.utc)
    cutoff = now - DRAW_RELEASE_NOTIFY_COOLDOWN
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Draw).where(
                Draw.draw_released_direct_at.isnot(None),
                Draw.draw_release_notified_at.is_(None),
                Draw.draw_release_detected_at.isnot(None),
                Draw.draw_release_detected_at <= cutoff,
            )
        )
        ready = result.scalars().all()
        if not ready:
            return

        # Group by the tennis week the draws belong to. A draw with no week
        # (unparsed start date) can't be batched with anything, so it goes out
        # on its own rather than being held for a group it isn't part of.
        groups: dict[tuple, list[Draw]] = {}
        for t in ready:
            key = (t.year, t.week) if t.week is not None else ("solo", t.id)
            groups.setdefault(key, []).append(t)

        batches: list[tuple[list[int], bool]] = []
        # Draws that arrived after their week's digest already went out. Stamped
        # as notified but never emailed — see the suppression branch below.
        suppressed: list[int] = []
        for key, members in groups.items():
            if key[0] == "solo":
                batches.append(([members[0].id], False))
                continue

            year, week = key
            siblings = (await db.execute(
                select(Draw).where(Draw.year == year, Draw.week == week)
            )).scalars().all()

            ready_ids = {t.id for t in members}
            # Already-notified siblings mean this week's digest has gone out, so
            # Any sibling in the week that hasn't been emailed yet holds the
            # batch. A draw that is released but still inside its stability
            # cooldown counts as outstanding, not as absent — Canadian Open's
            # two draws were detected 93 minutes apart and the second was still
            # cooling down when the first was dispatched.
            outstanding = [
                s for s in siblings
                if s.id not in ready_ids and s.draw_release_notified_at is None
            ]

            # No escape hatches. There is exactly one draw-release email per
            # week and it waits for every draw in that week, however long that
            # takes — the lag cap and the pick-deadline guard that used to be
            # here could each release a partial batch, and a partial batch is
            # by definition a second email.
            if outstanding:
                logger.info(
                    "Draw-release digest for %s week %s held: %d ready, waiting on %s",
                    year, week, len(members), [s.name for s in outstanding],
                )
                continue

            # One email per week, full stop. If a sibling in this week was
            # already announced, that week has had its digest and these draws
            # arrived after it — a draw added late, or one whose release was
            # detected after the batch went out. There is no follow-up: a second
            # message for the same week is exactly what a digest exists to
            # prevent. They are still stamped, or the sweep reconsiders them
            # every ten minutes forever.
            if any(s.draw_release_notified_at is not None
                   for s in siblings if s.id not in ready_ids):
                suppressed.extend(t.id for t in members)
                logger.info(
                    "Draw-release digest for %s week %s suppressed: week already "
                    "announced, %d late draw(s) not emailed (%s)",
                    year, week, len(members), ", ".join(t.name for t in members),
                )
                continue

            batches.append(([t.id for t in members], False))

        if not batches and not suppressed:
            return

        announced = {i for ids, _ in batches for i in ids} | set(suppressed)
        for t in ready:
            if t.id in announced:
                t.draw_release_notified_at = now
        await db.commit()

    from app.services.notifications import notify_draw_release_batch
    for ids, is_followup in batches:
        asyncio.create_task(notify_draw_release_batch(ids, is_followup=is_followup))
    logger.info("Draw-release notification: dispatched %d batch(es) covering %d draw(s)",
                len(batches), sum(len(ids) for ids, _ in batches))


# A withdrawal rarely arrives alone: an editor updating a draw page replaces a
# player, then places the qualifier who takes the slot, then fixes the seed —
# several scrapes' worth of separate changes describing one piece of news. This
# holds a draw's pending changes until it has been quiet for a spell, so the
# reader gets one message about the draw rather than one per edit.
#
# Longer than the draw-release cooldown because the failure modes differ. There
# the cost of waiting is a late "you can pick now"; here it is a late "your pick
# moved", and the batching is worth more than the minutes.
DRAW_CHANGE_NOTIFY_COOLDOWN = timedelta(minutes=20)

# Qualifiers get a longer wait than replacements, because their notification is
# once-per-draw and therefore unfixable: a qualifying draw finishes and its
# sixteen winners are transcribed in one sitting, but an editor can break off
# halfway and come back. Twenty minutes of quiet would call that done and
# announce half a field. Ninety is long enough to cover a break and still lands
# well inside the day between the qualifying final and the first main-draw match.
QUALIFIERS_SETTLE_COOLDOWN = timedelta(minutes=90)


async def _notify_pending_draw_changes() -> None:
    """
    Dispatch player swaps in draws people are already competing in.

    _do_scrape records the swaps (it is the only place the old name still
    exists); this decides when they have settled enough to send, on the same
    detect-here/dispatch-there split as the draw-release job, and for the same
    reason: every scrape path funnels through _do_scrape, so no path can record
    a change that nothing then sends.

    The cooldown is measured per draw on the NEWEST pending change, so a run of
    edits keeps resetting the clock and goes out as one message once the page
    stops moving. Comparison happens in SQL rather than Python: detected_at
    comes back from SQLite naive, and comparing it to an aware `cutoff` here
    would raise instead of batching.
    """
    from app.models.notification import DrawChangeEvent

    now = datetime.now(timezone.utc)
    ready_by_kind: dict[str, list] = {}
    async with AsyncSessionLocal() as db:
        # Settled independently per kind. A draw whose qualifiers went in an hour
        # ago and whose withdrawal landed a minute ago should send the qualifier
        # message now and hold the other — one kind still moving must not pin the
        # other behind it.
        for kind, cooldown in (("replaced", DRAW_CHANGE_NOTIFY_COOLDOWN),
                               ("filled", QUALIFIERS_SETTLE_COOLDOWN)):
            ready_by_kind[kind] = list((await db.execute(
                select(DrawChangeEvent.draw_id)
                .where(DrawChangeEvent.notified_at.is_(None),
                       DrawChangeEvent.kind == kind)
                .group_by(DrawChangeEvent.draw_id)
                .having(func.max(DrawChangeEvent.detected_at) <= now - cooldown)
            )).scalars().all())

        # A qualifying field is announced once, complete. A draw still carrying
        # an un-named slot is mid-transcription, so it waits however long that
        # takes rather than announcing a partial field it can never correct —
        # the once-per-draw claim means there is no second message to fix it
        # with. This is the "when ALL qualifiers are in" half; the settle
        # cooldown above only establishes that the page has stopped moving.
        from app.services.notifications import draw_is_fully_transcribed
        held_incomplete = []
        complete = []
        for draw_id in ready_by_kind["filled"]:
            if await draw_is_fully_transcribed(db, draw_id):
                complete.append(draw_id)
            else:
                held_incomplete.append(draw_id)
        if held_incomplete:
            logger.info("Qualifier announcement held for %d draw(s) still being "
                        "transcribed: %s", len(held_incomplete), held_incomplete)

        # A TOURNAMENT ANNOUNCES ITS QUALIFIERS ONCE, FOR BOTH DRAWS AT ONCE.
        #
        # A combined event runs an ATP and a WTA draw under one tournament, and
        # their qualifying finishes at different times. Released per draw, that
        # is two messages hours apart about the same event, the first of which
        # is only half the news. So a tournament is held until every one of its
        # draws that still owes a qualifying field is ready, then they go
        # together.
        #
        # "Still owes" is deliberately wider than "has events pending": a draw
        # whose qualifying is played later today has no events YET, and is
        # exactly the sibling worth waiting for. It is recognised by having
        # un-named entries still to fill.
        from app.models.tournament import Draw, DrawEntry
        if complete:
            ready = set(complete)
            tourn_of = dict((await db.execute(
                select(Draw.id, Draw.tournament_id)
                .where(Draw.id.in_(ready)))).all())
            siblings = (await db.execute(
                select(Draw.id, Draw.tournament_id).where(
                    Draw.tournament_id.in_({t for t in tourn_of.values() if t}),
                    Draw.status != "completed",
                ))).all()

            pending_ids = set((await db.execute(
                select(DrawChangeEvent.draw_id).where(
                    DrawChangeEvent.notified_at.is_(None),
                    DrawChangeEvent.kind == "filled",
                ).distinct())).scalars().all())
            unfinished_ids = set((await db.execute(
                select(DrawEntry.draw_id).where(
                    func.trim(func.coalesce(DrawEntry.name, "")) == "",
                ).distinct())).scalars().all())

            waiting_on = {}
            for draw_id, t_id in siblings:
                if draw_id in ready or t_id is None:
                    continue
                # A sibling only holds the tournament if it has something to say
                # and has not said it yet.
                if draw_id in pending_ids or draw_id in unfinished_ids:
                    waiting_on.setdefault(t_id, []).append(draw_id)

            held_for_sibling = [d for d in complete
                                if waiting_on.get(tourn_of.get(d))]
            if held_for_sibling:
                logger.info("Qualifier announcement held for %d draw(s) whose "
                            "sibling draw is not ready: %s",
                            len(held_for_sibling), held_for_sibling)
            complete = [d for d in complete if not waiting_on.get(tourn_of.get(d))]

        ready_by_kind["filled"] = complete

        if not any(ready_by_kind.values()):
            held = (await db.execute(
                select(func.count()).select_from(DrawChangeEvent)
                .where(DrawChangeEvent.notified_at.is_(None))
            )).scalar() or 0
            if held:
                logger.info("Draw-change dispatch: %d change(s) still settling", held)
            return

    from app.services.notifications import notify_draw_change_batch
    for kind, ready in ready_by_kind.items():
        if not ready:
            continue
        logger.info("Draw-change dispatch (%s): %d draw(s) ready", kind, len(ready))
        await notify_draw_change_batch(ready, kind)


# Matches finish in waves — a full round can land inside an hour — so a user who
# called three of them right should hear about three in one message, not three
# times. Shorter than the draw-change cooldown: nothing here needs re-checking,
# and the pleasure of "you called it" fades with the delay.
STANDOUT_NOTIFY_COOLDOWN = timedelta(minutes=15)

# How far back the sweep will look for a finished match it has never measured.
# Everything already completed when this feature shipped is pre-stamped as
# notified by a migration, so this is not what prevents a historical blast — it
# is the second line of defence, bounding the damage if a draw's participant
# pool ever changes late enough to make a batch of old matches newly measurable.
STANDOUT_MEASURE_WINDOW = timedelta(days=2)


async def _notify_pending_standout_picks() -> None:
    """
    Measure finished matches against the field, then tell the minority who
    called them right.

    Measuring is a sweep over draw state rather than a hook on the code path
    that writes a result, for the reason spelled out on _record_completed_rounds:
    a winner can arrive from ESPN, a Wikipedia scrape, an admin refresh or a
    backfill, and a hook on one of those misses the other three permanently.
    """
    from app.models.notification import StandoutPickNotification
    from app.services.notifications import record_standout_picks

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        # Same scope as the round-completion sweep: draws in play, plus ones that
        # ended recently enough that their final rounds still deserve a message.
        draw_ids = list((await db.execute(
            select(Draw.id).where(Draw.status.in_(["active", "open"]))
        )).scalars().all())
        draw_ids += list((await db.execute(
            select(Draw.id).where(
                Draw.status == "completed",
                Draw.completion_notified_at.isnot(None),
                Draw.completion_notified_at >= now - timedelta(days=3),
            )
        )).scalars().all())

    # One session per draw. A failed measurement rolls its session back, and a
    # rollback expires every instance still attached to it — sharing one session
    # across the loop meant one bad draw took the rest of the sweep down with it,
    # the same trap documented on _refresh_active_tournaments.
    measured = 0
    for draw_id in draw_ids:
        async with AsyncSessionLocal() as db:
            try:
                d = await db.get(Draw, draw_id)
                if d is None:
                    continue
                n = await record_standout_picks(db, d, since=now - STANDOUT_MEASURE_WINDOW)
                if n:
                    await db.commit()
                    measured += n
            except Exception as exc:
                await db.rollback()
                logger.warning("Standout measurement failed for draw %d: %s", draw_id, exc)
    if measured:
        logger.info("Standout picks: measured %d newly-finished match(es)", measured)

    async with AsyncSessionLocal() as db:
        cutoff = now - STANDOUT_NOTIFY_COOLDOWN
        ready_draws = (await db.execute(
            select(StandoutPickNotification.draw_id)
            .where(StandoutPickNotification.notified_at.is_(None))
            .group_by(StandoutPickNotification.draw_id)
            .having(func.max(StandoutPickNotification.detected_at) <= cutoff)
        )).scalars().all()
        if not ready_draws:
            return

        # One call covering every ready draw, so a user competing in two of them
        # gets one message listing both rather than a message per tournament.
        match_ids = (await db.execute(
            select(StandoutPickNotification.match_id).where(
                StandoutPickNotification.notified_at.is_(None),
                StandoutPickNotification.draw_id.in_(list(ready_draws)),
            )
        )).scalars().all()

    if match_ids:
        from app.services.notifications import notify_standout_picks
        logger.info("Standout picks: dispatching %d measured match(es)", len(match_ids))
        await notify_standout_picks(list(match_ids))


async def _record_missed_completions() -> None:
    """
    Fire draw-completion for draws that finished without anything noticing.

    notify_tournament_complete is what persists final standings to draw history,
    and it runs from exactly two places: the periodic refresh, on a status flip,
    and espn_monitor. A final written by any other path — a Wikipedia edit
    arriving through EventStreams, an admin refresh, a page-load scrape — flips
    the draw to 'completed' inside _do_scrape without either of them seeing it.
    2026 Washington (M) finished that way: five predictors lost their draw
    history, and because the same gap leaves completion_notified_at null, which
    is what _record_completed_rounds keys on, it also dropped out of its week's
    digest.

    Scoped by end_date rather than by the stamp this is about to write: a draw
    that ended long ago and was never recorded stays that way. Resurrecting one
    would queue a Final round for an event that finished months ago and mail its
    standings out as news.
    """
    from app.services.notifications import notify_tournament_complete

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=3)
    async with AsyncSessionLocal() as db:
        missed = (await db.execute(
            select(Draw.id, Draw.name, Draw.gender).where(
                Draw.status == "completed",
                Draw.completion_notified_at.is_(None),
                Draw.end_date.isnot(None),
                Draw.end_date >= cutoff,
            )
        )).all()

    # Outside the session above: notify_tournament_complete opens its own and
    # writes, and SQLite does not want a second writer under an open read.
    for draw_id, name, gender in missed:
        logger.info("Draw %d (%s %s) completed but was never recorded — firing completion",
                    draw_id, name, gender)
        # Idempotent: completion_notified_at plus a unique claim row, so a
        # redundant call here costs nothing.
        await notify_tournament_complete(draw_id)


async def _record_completed_rounds(db) -> None:
    """
    Find rounds that are finished but were never recorded, and record them.

    Detection used to live only in espn_monitor, firing in the same pass that
    wrote a result. That misses a round whose last winner arrives any other way
    — a Wikipedia scrape, an admin refresh, a backfill — and misses it
    permanently, because nothing ever looks again. Washington (M) and Memphis
    both finished R32 on 2026-07-29 and neither was ever queued.

    Sweeping here instead makes the digest depend on the state of the draw
    rather than on which code path happened to write the deciding result. The
    unique (draw, round) row still makes this idempotent.
    """
    from sqlalchemy.exc import IntegrityError
    from app.models.notification import RoundCompleteNotification

    draws = (await db.execute(
        select(Draw).where(Draw.status.in_(["active", "open"]))
    )).scalars().all()

    # A draw flips to 'completed' the moment its final ends, so the scan above
    # can never catch a round the event-driven path missed — the draw is already
    # out of scope by the time anything looks again. Recently-completed draws are
    # therefore swept too, and for EVERY round, not just the final: a digest
    # waits for every draw in its bucket without exception, so a single
    # unrecorded round on a finished draw would hold that bucket's email open
    # forever. Recording the round is the right way out of that wait — publishing
    # without the draw is not. The recency guard is what stops this queueing
    # rounds for events that finished weeks ago.
    draws += (await db.execute(
        select(Draw).where(
            Draw.status == "completed",
            Draw.completion_notified_at.isnot(None),
            Draw.completion_notified_at >= datetime.now(timezone.utc) - timedelta(days=3),
        )
    )).scalars().all()
    if not draws:
        return

    for d in draws:
        rows = (await db.execute(
            select(
                Match.round_number,
                func.count().label("total"),
                func.sum(case((Match.winner_id.is_(None), 1), else_=0)).label("open"),
            )
            .where(Match.draw_id == d.id, Match.is_bye == False)  # noqa: E712
            .group_by(Match.round_number)
        )).all()

        for round_number, total, still_open in rows:
            if total == 0 or still_open:
                continue
            already = await db.scalar(
                select(RoundCompleteNotification.id).where(
                    RoundCompleteNotification.draw_id == d.id,
                    RoundCompleteNotification.round_number == round_number,
                )
            )
            if already:
                continue
            try:
                async with db.begin_nested():
                    db.add(RoundCompleteNotification(
                        draw_id=d.id, round_number=round_number, recipient_count=0,
                    ))
                logger.info("Round %d of draw %d found complete — queued for digest",
                            round_number, d.id)
            except IntegrityError:
                pass  # recorded concurrently by espn_monitor
    await db.commit()


# Tiers that get their own digest instead of sharing the week's.
#
# A 1000 or a Slam runs 8-14 days, so bucketing it by start-week stalls every
# 250 and 500 that finished days earlier: the week-30 Final digest sat for days
# behind the Canadian Open, which merely *starts* in week 30 and doesn't finish
# until week 31. It also buried a Masters result among four 250s. A major's
# bucket is therefore the EVENT, which is equally what keeps the men's and
# women's draws of a combined event (Canadian Open, Indian Wells, every Slam) in
# one email instead of two.
MAJOR_DIGEST_TIERS = {"GS", "1000"}

# How far past a draw's own end date the digest will wait before treating the
# silence as a fault worth alerting on. It never shortens the wait — the batch
# still holds for the lagging draw — it only stops a stall being invisible.
DIGEST_STALL_DAYS = 3


def _digest_bucket(d: Draw) -> tuple:
    """Which digest a draw's completed rounds belong to.

    Draws sharing a bucket are batched into one email per round label, and each
    holds that batch open until the others have reached the same round.
    """
    if d.scoring_tier in MAJOR_DIGEST_TIERS:
        # tournament_id is what links the M and F draws of one event. Fall back
        # to the name so an unlinked draw still buckets with its sibling rather
        # than emailing on its own.
        return ("event", d.year, d.tournament_id or d.name)
    if d.week is not None:
        return ("week", d.year, d.week)
    return ("solo", d.id, None)


async def _notify_pending_round_digests() -> None:
    """
    Round-completion digest dispatch.

    espn_monitor records each round the moment it completes
    (notifications.record_round_complete); this decides when a batch is worth
    sending. Draws that run alongside each other finish the same round hours or
    days apart, so a per-draw email meant four messages for one afternoon of
    tennis.

    Batches are (bucket, round label). The bucket is the tennis week for 250s
    and 500s and the event itself for 1000s and Slams — see _digest_bucket.
    Grouping on the round *label* rather than the round number matters because
    the same name sits at different numbers in different draw sizes: R32 is
    round 1 of a 32-draw and round 3 of a 128-draw.
    """
    from app.models.notification import RoundCompleteNotification
    from app.services.notifications import notify_round_complete_digest

    # Before the round sweep, not after: it only considers a completed draw's
    # final round once completion_notified_at is set, so an unrecorded
    # completion would otherwise hide that draw's Final for another cycle.
    await _record_missed_completions()

    async with AsyncSessionLocal() as db:
        await _record_completed_rounds(db)
        pending = (await db.execute(
            select(RoundCompleteNotification)
            .where(RoundCompleteNotification.digest_sent_at.is_(None))
        )).scalars().all()
        if not pending:
            return

        draws = {
            d.id: d for d in (await db.execute(
                select(Draw).where(Draw.id.in_([p.draw_id for p in pending]))
            )).scalars().all()
        }

        groups: dict[tuple, list] = {}
        for p in pending:
            d = draws.get(p.draw_id)
            if not d:
                continue
            groups.setdefault((_digest_bucket(d), d.round_name(p.round_number)), []).append((p, d))

        batches = []
        # Late finishers whose bucket digest already went out: claimed so the
        # sweep stops re-reading them, but deliberately never emailed.
        late_stamped: list[tuple[int, int]] = []
        for (bucket, label), members in groups.items():
            kind = bucket[0]
            if kind == "solo":
                p, d = members[0]
                batches.append(([(d.id, p.round_number)], False, 1, None))
                continue

            if kind == "event":
                _, year, ident = bucket
                event_label = members[0][1].name
                bucket_desc = f"{year} {event_label}"
                q = select(Draw).where(Draw.year == year)
                q = (q.where(Draw.tournament_id == ident) if isinstance(ident, int)
                     else q.where(Draw.name == ident))
            else:
                _, year, week = bucket
                event_label = None
                bucket_desc = f"{year} week {week}"
                q = select(Draw).where(Draw.year == year, Draw.week == week)

            # Re-bucket the candidates rather than trusting the query: a week
            # query still returns the 1000s and Slams starting that week, and
            # those belong to their own digest, not this one.
            siblings = [s for s in (await db.execute(q)).scalars().all()
                        if _digest_bucket(s) == bucket]

            # Which of the bucket's draws will ever produce this round label,
            # and of those, which have not reported it yet. A draw whose bracket
            # never contains this label (a 32-draw has no R128) is not a
            # straggler and must not hold the batch.
            in_scope, outstanding = [], []
            for s in siblings:
                rn = next((r for r in range(1, s.num_rounds + 1) if s.round_name(r) == label), None)
                if rn is None:
                    continue
                in_scope.append(s)
                reported = await db.scalar(
                    select(RoundCompleteNotification.id).where(
                        RoundCompleteNotification.draw_id == s.id,
                        RoundCompleteNotification.round_number == rn,
                    )
                )
                # Unconditional: a draw in the bucket that has not reported this
                # round holds the batch, whatever its status. There used to be an
                # exemption for 'completed' draws, on the reasoning that a
                # finished tournament can no longer produce the round — but that
                # published the bucket without it, which is exactly what a digest
                # must never do. A finished draw that has not reported is a
                # recording failure, and _record_completed_rounds now sweeps every
                # round of a recently-completed draw so the report arrives instead
                # of the batch going out short.
                if not reported:
                    outstanding.append(s)

            # Already-sent siblings mean this bucket's digest for this round has
            # gone, so anything arriving now is a late finisher — and a late
            # finisher gets NO email. One message per bucket per round, full
            # stop; a follow-up is the same failure a digest exists to prevent,
            # just arriving second. This used to send one flagged
            # is_followup=True.
            already_sent = await db.scalar(
                select(RoundCompleteNotification.id).where(
                    RoundCompleteNotification.draw_id.in_([s.id for s in in_scope]),
                    RoundCompleteNotification.digest_sent_at.isnot(None),
                    RoundCompleteNotification.round_number.in_([p.round_number for p, _ in members]),
                )
            ) is not None

            # No deadline, and no exceptions: the batch waits until every draw
            # in the bucket that can reach this round has reported, however long
            # that takes. Publishing a bucket while one of its draws is still
            # lagging is the thing a digest exists to prevent — there is no
            # timeout, no partial send, no "send now and follow up later".
            # Bounded because a bucket is either one week of short events or one
            # event, never a week gated on a fortnight-long major.
            if outstanding:
                logger.info(
                    "Round digest %s for %s held: %d ready, waiting on %s",
                    label, bucket_desc, len(members),
                    [f"{s.name} ({s.gender})" for s in outstanding],
                )
                # Waiting is correct; waiting silently forever is not. A draw
                # whose own end date is well past should have reported this round
                # already, so the wait has stopped being normal lag and become a
                # recording failure. Raise it instead of shortening the wait.
                cutoff = date.today() - timedelta(days=DIGEST_STALL_DAYS)
                overdue = [s for s in outstanding if s.end_date and s.end_date < cutoff]

                # Past its end date is not the same as finished. end_date is a
                # scheduled date and it goes stale — 2026 Canadian Open carried
                # 2026-08-10 while its men's final was still to be played on the
                # 13th — so a draw with matches left to play is not stalled, it
                # is running, and holding the digest for it is exactly right.
                #
                # A genuine stall has nothing left to play AND no recorded round:
                # that is the recording failure this alert exists for. Anything
                # else is a wrong date, which is worth saying but is not an error
                # in the digest.
                stalled, still_playing = [], []
                for sd in overdue:
                    undecided = (await db.execute(
                        select(func.count()).select_from(Match).where(
                            Match.draw_id == sd.id,
                            Match.is_bye == False,  # noqa: E712
                            Match.winner_id.is_(None),
                        )
                    )).scalar() or 0
                    (still_playing if undecided else stalled).append((sd, undecided))

                if still_playing:
                    from app.services.system_log import app_log
                    names = ", ".join(f"{sd.name} ({tour_label(sd.gender)}), "
                                      f"{n} match(es) left" for sd, n in still_playing)
                    await app_log(
                        "warning", "scraper",
                        f"{bucket_desc} is still being played past its recorded end date "
                        f"({max(sd.end_date for sd, _ in still_playing)}): {names}. The "
                        f"{label} digest is correctly waiting; the end date is what is wrong",
                        {"bucket": bucket_desc, "round_name": label,
                         "draw_ids": [sd.id for sd, _ in still_playing]},
                        dedup_key=f"stale_end_date_{bucket_desc}",
                        dedup_hours=DRAW_HEALTH_REALERT_HOURS,
                    )

                if stalled:
                    stalled = [sd for sd, _ in stalled]
                    from app.services.system_log import app_log
                    await app_log(
                        "error", "notifications",
                        f"{label} digest for {bucket_desc} is held with {len(members)} "
                        f"draw(s) ready: "
                        f"{', '.join(f'{s.name} ({s.gender})' for s in stalled)} "
                        f"finished on or before {max(s.end_date for s in stalled)} but has "
                        f"never recorded this round, so the email cannot go out",
                        {"round_name": label, "bucket": bucket_desc,
                         "stalled_draw_ids": [s.id for s in stalled],
                         "ready_draw_ids": [d.id for _, d in members]},
                        dedup_key=f"digest_stalled_{bucket_desc}_{label}",
                        dedup_hours=DRAW_HEALTH_REALERT_HOURS,
                    )
                continue

            # Suppressed, not sent: mark the rows claimed so the sweep stops
            # reconsidering them, and say plainly in the log which draws never
            # made it into an email.
            if already_sent:
                late_stamped.extend((d.id, p.round_number) for p, d in members)
                logger.info(
                    "Round digest %s for %s suppressed: bucket already sent, "
                    "%d late draw(s) not emailed (%s)",
                    label, bucket_desc, len(members),
                    ", ".join(f"{d.name} ({tour_label(d.gender)})" for _, d in members),
                )
                continue

            batches.append((
                [(d.id, p.round_number) for p, d in members],
                False,
                len(in_scope),
                event_label,
            ))

    if late_stamped:
        # Same claim the digest itself would write, without the send.
        from app.models.notification import RoundCompleteNotification
        from sqlalchemy import update as sa_update
        async with AsyncSessionLocal() as db:
            for draw_id, rnd in late_stamped:
                await db.execute(
                    sa_update(RoundCompleteNotification)
                    .where(
                        RoundCompleteNotification.draw_id == draw_id,
                        RoundCompleteNotification.round_number == rnd,
                        RoundCompleteNotification.digest_sent_at.is_(None),
                    )
                    .values(digest_sent_at=datetime.now(timezone.utc), recipient_count=0)
                )
            await db.commit()

    if not batches:
        return
    for entries, is_followup, span, event_label in batches:
        asyncio.create_task(notify_round_complete_digest(
            entries, is_followup=is_followup, total_in_week=span,
            event_label=event_label,
        ))
    logger.info("Round-complete digest: dispatched %d batch(es) covering %d draw-round(s)",
                len(batches), sum(len(e) for e, _, _, _ in batches))


# Re-alert cadence for the two draw-health checks below — long enough to not
# spam on every run, short enough that a genuinely stuck tournament doesn't
# go unnoticed for days (as Iași Open's title did before anyone looked).
DRAW_HEALTH_REALERT_HOURS = 6.0


async def _check_draw_health() -> None:
    """
    Periodic sanity sweep for two classes of silent failure that were each hit
    in production and neither raises an exception on its own, so nothing else
    would ever flag them:

    1. "Released but not shown as open" (Athens Open) — draw_released_direct_at
       is set, the tournament genuinely hasn't started, and it's within the
       window where computed_status is supposed to report "open" — but it
       doesn't. This directly re-derives the "should be open" condition from
       raw fields (NOT by calling computed_status) so the check stays useful
       even if a future change reintroduces the same kind of ordering bug in
       computed_status itself — a check that just re-asked the buggy property
       what it thinks would never catch its own bug.

    2. "Wiki page never resolves" (Iași Open) — wiki_page_id has never been
       set (every scrape attempt has failed to even locate the page) for a
       tournament whose expected draw-release date has passed (or, when no
       release date is known, that starts within a day).
       Each individual attempt already logs+dedups hourly via
       _refresh_active_tournaments' exception handler; this escalates once
       it's clearly not a transient blip but a wrong/dead title that needs a
       human to fix (as with Iași Open's malformed season-page wikilink).
    """
    from app.services.system_log import app_log

    today = date.today()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Draw).where(Draw.status.notin_(["completed"]))
        )
        tournaments = result.scalars().all()

    for t in tournaments:
        # --- Check 1: released but not open -------------------------------
        should_be_open = (
            t.draw_released_direct_at is not None
            and t.start_date is not None
            and today < t.start_date
            and (t.start_date - today).days <= 30
            and t.status not in ("active", "completed")
        )
        if should_be_open and t.computed_status not in ("open", "active", "completed"):
            await app_log(
                "error", "scheduler",
                f"Draw released but not showing as open: {t.year} {t.name} ({t.gender}) — "
                f"computed_status={t.computed_status!r}, expected 'open'",
                {"tournament_id": t.id, "tournament_name": t.name, "gender": t.gender,
                 "draw_released_direct_at": str(t.draw_released_direct_at),
                 "start_date": str(t.start_date), "computed_status": t.computed_status},
                dedup_key=f"released_not_open_{t.id}", dedup_hours=DRAW_HEALTH_REALERT_HOURS,
            )

        # --- Check 2: wiki page never resolves -----------------------------
        # Only escalate once the draw is actually overdue. Draw pages are
        # normally created on Wikipedia around the release date, so an
        # unresolved page before then is expected, not an error.
        # draw_release_direct is deliberately a floor, not a best guess — it can
        # only land on or before the real release (see draw_dates.py). Escalating
        # the day after it passes would therefore fire on draws that are simply
        # arriving on their normal schedule. Use the LATER of that date and the
        # day before play, by which point a draw genuinely is always out.
        deadline = t.start_date - timedelta(days=1) if t.start_date else None
        if t.draw_release_direct is not None:
            predicted_deadline = t.draw_release_direct + timedelta(days=1)
            deadline = max(deadline, predicted_deadline) if deadline else predicted_deadline
        release_overdue = deadline is not None and today >= deadline
        if t.wiki_page_id is None and release_overdue:
            await app_log(
                "error", "scheduler",
                f"Wiki page never resolved for {t.year} {t.name} ({t.gender}) — "
                f"likely a wrong/dead wiki_page_title: {t.wiki_page_title!r}",
                {"tournament_id": t.id, "tournament_name": t.name, "gender": t.gender,
                 "wiki_page_title": t.wiki_page_title, "draw_release_direct": str(t.draw_release_direct),
                 "start_date": str(t.start_date)},
                dedup_key=f"wiki_never_resolved_{t.id}", dedup_hours=DRAW_HEALTH_REALERT_HOURS,
            )


# How stale rankings may get before it stops being the normal weekly rhythm.
# Weeks are Monday-anchored and refreshed weekly, so the honest maximum lag is
# 6 days (Sunday, looking at Monday's data). 10 leaves room for a week that TE
# publishes late or skips without crying wolf, while still catching a refresh
# that has genuinely stopped.
RANKINGS_STALE_DAYS = 10
# The ELO cron runs Monday 01:00 UTC, so a brand-new week legitimately has no
# ELO for a few hours. Only judge a week that has had a full day to fill in.
ELO_GRACE_DAYS = 2


async def _check_rankings_health() -> None:
    """
    Escalate rankings/ELO that have stopped updating.

    This is the other half of suppressing transient network errors at the TE
    scrape sites. Individual failures there are now debug-only — TE times out
    and 403s often enough that alerting per attempt was pure noise — but "the
    scrape failed once" and "rankings have not moved in two weeks" are different
    claims, and only the second one is worth an email. So instead of counting
    failed attempts (useless for a weekly job: the next data point is seven days
    away, and any in-process counter dies at the next deploy), this asks the data
    whether the outcome actually arrived.
    """
    from app.models.rankings import TeRankingsSnapshot
    from app.services.system_log import app_log

    today = date.today()
    async with AsyncSessionLocal() as db:
        latest_week = (
            await db.execute(select(func.max(TeRankingsSnapshot.week_date)))
        ).scalar()
        if latest_week is None:
            return  # Empty table — a fresh dev DB, not a stalled refresh.

        days_behind = (today - latest_week).days
        if days_behind > RANKINGS_STALE_DAYS:
            await app_log(
                "error", "rankings",
                f"Rankings have not updated in {days_behind} days — newest week is "
                f"{latest_week}, expected one no older than {RANKINGS_STALE_DAYS} days",
                {"latest_week": str(latest_week), "days_behind": days_behind,
                 "threshold_days": RANKINGS_STALE_DAYS},
                dedup_key="rankings_stale", dedup_hours=DRAW_HEALTH_REALERT_HOURS,
            )

        # ELO rides on the same snapshot rows, so a week can arrive complete on
        # ranking and empty on ELO — which is what a silently failing ELO
        # refresh looks like from the outside.
        if (today - latest_week).days >= ELO_GRACE_DAYS:
            elo_rows = (
                await db.execute(
                    select(func.count())
                    .select_from(TeRankingsSnapshot)
                    .where(
                        TeRankingsSnapshot.week_date == latest_week,
                        TeRankingsSnapshot.elo.isnot(None),
                    )
                )
            ).scalar() or 0
            if elo_rows == 0:
                await app_log(
                    "error", "rankings",
                    f"No ELO ratings for week {latest_week} — the ELO refresh has "
                    f"not landed for a week that is {(today - latest_week).days} days old",
                    {"latest_week": str(latest_week), "elo_rows": elo_rows},
                    dedup_key="elo_missing", dedup_hours=DRAW_HEALTH_REALERT_HOURS,
                )

        # Players the retry loop has given up on. Every scrape re-attempts the
        # entries with no te_player_id, so one that is still unresolved after
        # play has begun is not waiting on TE to publish — it is a name our
        # matcher cannot bridge, and it costs that player's ranking, ELO, H2H
        # and form on a draw people are actively picking.
        unresolved = (
            await db.execute(
                select(Draw.id, Draw.name, Draw.gender, Draw.year, DrawEntry.name)
                .join(DrawEntry, DrawEntry.draw_id == Draw.id)
                .where(
                    DrawEntry.te_player_id.is_(None),
                    DrawEntry.name.isnot(None),
                    DrawEntry.name != "",
                    Draw.status != "completed",
                    Draw.start_date.isnot(None),
                    Draw.start_date <= today,
                )
            )
        ).all()
        by_draw: dict[int, tuple[str, list[str]]] = {}
        for draw_id, name, gender, year, player in unresolved:
            label, names = by_draw.setdefault(draw_id, (f"{year} {name} ({gender})", []))
            names.append(player)
        for draw_id, (label, names) in by_draw.items():
            await app_log(
                "error", "rankings",
                f"{len(names)} player(s) in {label} have no Tennis Explorer match after "
                f"the draw started — no ranking, ELO, H2H or form for them: "
                f"{', '.join(sorted(names)[:10])}"
                + (f" (+{len(names) - 10} more)" if len(names) > 10 else ""),
                {"draw_id": draw_id, "draw": label, "player_names": sorted(names),
                 "unresolved_count": len(names)},
                dedup_key=f"unresolved_players_{draw_id}", dedup_hours=DRAW_HEALTH_REALERT_HOURS,
            )


async def _sync_subscriptions() -> None:
    """Sync EventStreams subscriptions with active/pending tournaments + season pages."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Draw).where(
                Draw.status.in_(["upcoming", "open", "active"])
            )
        )
        tournaments = result.scalars().all()

    # Tournament draw pages: use page_id when known. For unresolved pages,
    # subscribe every plausible title variant ('– Singles' vs gendered) —
    # editors' choice of suffix isn't reliably predictable, and watching all
    # variants means page creation is caught instantly whichever they pick.
    from app.services.scraper import singles_title_variants
    wanted: dict[str, int | None] = {}
    for t in tournaments:
        if t.wiki_page_id is None:
            for v in singles_title_variants(t.wiki_page_title, t.gender):
                wanted.setdefault(v, None)
    for t in tournaments:
        if t.wiki_page_id is not None:
            wanted[t.wiki_page_title] = t.wiki_page_id

    # Season pages: always subscribed by title (we don't store their page IDs)
    for title in _season_pages():
        wanted[title] = None

    current = eventstream.subscriptions
    added = removed = 0
    for title, page_id in wanted.items():
        if title not in current:
            await eventstream.subscribe(title, page_id=page_id)
            added += 1
        elif page_id is not None and eventstream.current_page_id_for(title) != page_id:
            # Title already subscribed but under a stale/wrong page_id — update it.
            await eventstream.subscribe(title, page_id=page_id)
            added += 1

    for title in current - set(wanted):
        await eventstream.unsubscribe(title)
        removed += 1

    # Log full subscription state so we can verify page_ids are correct
    with_id = {pid: t for t, pid in wanted.items() if pid is not None}
    without_id = [t for t, pid in wanted.items() if pid is None]
    logger.info(
        "_sync_subscriptions: added=%d removed=%d | "
        "id_subs=%d %s | title_only=%d %s",
        added, removed,
        len(with_id), with_id,
        len(without_id), without_id,
    )


async def _sync_highest_rank_bot() -> None:
    """Keep the "Highest_Rank" baseline user's picks current for every draw
    that hasn't locked yet. Idempotent full-bracket recompute — see
    highest_rank_bot.py docstring for why a one-shot-before-lock simulation
    (rather than re-simulating after each round) is the correct baseline."""
    from app.services import highest_rank_bot
    from app.services.system_log import app_log

    try:
        async with AsyncSessionLocal() as db:
            synced = await highest_rank_bot.sync_open_draws(db)
        if synced:
            logger.info("Highest_Rank bot: synced picks for %d draw(s)", synced)

    except Exception as exc:
        logger.error("Highest_Rank bot sync failed: %s", exc)
        err = describe_exception(exc)
        await app_log("error", "highest_rank_bot", f"Sync job failed: {err}",
                      {"error": err}, dedup_key="highest_rank_bot_fail", dedup_hours=6)


async def _refresh_order_of_play() -> None:
    """Keep each draw's order-of-play link pointing at today's PDF, or at
    nothing. Both halves run every tick: the id lookup is cheap and a newly
    discovered tournament should not wait a day for its first link, and the
    link refresh must run even when no new ids were stamped — clearing a link
    that has gone stale is the half that protects users from opening a PDF
    frozen on a finished tournament's last day. See order_of_play.py."""
    from app.services import order_of_play
    from app.services.system_log import app_log

    try:
        atp = await order_of_play.refresh_atp_ids()
        if atp:
            logger.info("Order of play: learned %d ATP tournament id(s) from Wikipedia", atp)
        stamped = await order_of_play.refresh_wta_ids()
        if stamped:
            logger.info("Order of play: matched %d tournament(s) to WTA ids", stamped)
        updated = await order_of_play.refresh_order_of_play()
        if updated:
            logger.info("Order of play: updated %d draw link(s)", updated)
        # Say so when a tournament is under way with no schedule at all. Silence
        # is the failure mode here — a wrong id, a moved file and a changed URL
        # scheme all look identical from the outside.
        await order_of_play._alert_missing_oop()
    except Exception as exc:
        logger.error("Order of play refresh failed: %s", exc, exc_info=True)
        err = describe_exception(exc)
        await app_log("error", "order_of_play", f"Refresh job failed: {err}",
                      {"error": err}, dedup_key="oop_refresh_fail", dedup_hours=6)


async def _refresh_atp_tournament_ids() -> None:
    """Learn ATP tournament ids from atptour.com. Weekly is generous — the ids
    are tournament-level rather than per-edition, so they barely change — but it
    costs one page load and means a newly added tournament is covered within a
    week rather than at the next season rollover."""
    from app.services import atp_ids
    from app.services.system_log import app_log

    try:
        result = await atp_ids.refresh_atp_tournament_ids()
        if result.get("stamped"):
            logger.info("ATP ids: stamped %d tournament(s) from %d found",
                        result["stamped"], result.get("found", 0))
    except Exception as exc:
        logger.error("ATP id refresh failed: %s", exc, exc_info=True)
        err = describe_exception(exc)
        await app_log("error", "order_of_play", f"ATP id refresh failed: {err}",
                      {"error": err}, dedup_key="atp_id_job_fail", dedup_hours=24)


async def _refresh_schedule_estimates() -> None:
    """Re-chain today's expected start times against live results.

    Separate from the order-of-play job on purpose. That one re-fetches the PDF
    every 15 minutes, and the PDF does not change when a match finishes — so
    running the chain on its cadence recomputed the same numbers all day. What
    moves an estimate is ESPN, which updates every 60 seconds, so this runs
    close to that instead. It reads only what is already in the database and
    writes nothing but the estimates.
    """
    from datetime import date as _date
    from sqlalchemy import select as _select
    from app.models.schedule import ScheduleEntry
    from app.models.tournament import Draw
    from app.services import schedule as schedule_svc
    from app.services.system_log import app_log

    try:
        # A window, not `today`. This clock is UTC and the venues are not, so a
        # single date stops covering the session that is actually being played:
        # from 8pm in Cincinnati it is already tomorrow here, and the evening
        # matches — the ones whose estimates are still moving — would be the
        # first to stop being re-chained. A day either side covers every venue
        # offset in both directions, and days with no rows cost one query.
        today = _date.today()
        days = [today - timedelta(days=1), today, today + timedelta(days=1)]
        async with AsyncSessionLocal() as db:
            pairs = (await db.execute(
                _select(ScheduleEntry.tournament_id, ScheduleEntry.play_date)
                .where(ScheduleEntry.play_date.in_(days)).distinct())).all()
        # RETRY EACH ONE, AND KEEP GOING PAST A FAILURE. The retry doctrine
        # — why a lock here is a lost snapshot rather than a timeout, and why
        # each attempt needs a fresh session — now lives in db_retry, which
        # the OOP ingest path shares. One tournament's conflict used to abort
        # the whole loop, so every tournament after it silently kept a stale
        # estimate; that is what the `continue` below is for.
        from app.services.db_retry import with_write_retry

        stuck = []
        for tid, day in pairs:
            async def _one(db, tid=tid, day=day):
                tz = (await db.execute(
                    _select(Draw.venue_timezone).where(
                        Draw.tournament_id == tid,
                        Draw.venue_timezone.isnot(None)))).scalars().first()
                await schedule_svc.recompute_expected_starts(
                    db, tid, day, venue_tz=tz)
            try:
                await with_write_retry(_one, what=f"estimates {tid}/{day}")
            except OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                logger.warning("Estimate refresh gave up on tournament %s %s: %s",
                               tid, day, exc)
                stuck.append(f"{tid}/{day}")
        if stuck:
            # Only what retrying could not fix is worth anyone's attention.
            await app_log(
                "error", "order_of_play",
                f"Estimate refresh still locked out after 4 attempts: "
                f"{', '.join(stuck)}",
                {"stuck": stuck}, dedup_key="sched_estimates_fail",
                dedup_hours=6)
    except Exception as exc:
        logger.error("Schedule estimate refresh failed: %s", exc, exc_info=True)
        err = describe_exception(exc)
        await app_log("error", "order_of_play", f"Estimate refresh failed: {err}",
                      {"error": err}, dedup_key="sched_estimates_fail", dedup_hours=6)


async def _scan_system_alerts() -> None:
    """Email digest of new errors/warnings in system_logs — see alerts.py for
    the recurrence gate and daily cap. Wrapped because a failure here must not
    take down the scheduler tick that reports every other failure."""
    from app.services import alerts

    try:
        await alerts.scan_and_alert()
    except Exception as exc:
        logger.error("System alert scan failed: %s", exc, exc_info=True)


async def run_order_of_play_only() -> None:
    """The order-of-play refresh, on its own loop, for a non-scraping instance.

    Staging keeps the scrapers off so it cannot double the load on Wikipedia or
    Tennis Explorer, but the order of play is exactly what it is there to test —
    and without this its schedule simply stopped at whatever day it was seeded
    with.

    SLOWER THAN THE SCHEDULER'S 15 MINUTES, on purpose. This was first written
    to match it exactly, on the reasoning that these are static PDFs and cheap.
    protennislive.com disagreed: with two instances on the same egress IP asking
    for the same files, a run of 429s appeared in both logs. The tours' file
    hosts are a shared budget, and production's claim on it is the one that
    matters.

    Hourly is ample here. Nobody is watching staging for a sheet revision within
    the quarter-hour, and an offset start keeps the two instances from arriving
    together even when the periods happen to align.
    """
    import asyncio
    import random

    # Offset so a restart of both containers does not line the two up.
    await asyncio.sleep(random.uniform(60, 300))

    while True:
        try:
            await _refresh_order_of_play()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("standalone order-of-play refresh failed: %s", exc)
        await asyncio.sleep(60 * 60)


async def run_schedule_estimates_only() -> None:
    """The chained start-time estimates, on their own loop, for the same instance.

    Split back out of the loop above, where it had been folded in because the
    two look like the same job. They are not. Fetching a sheet is a request to
    somebody else's file host, and the hour above is a concession to sharing it.
    Re-chaining the estimates touches nothing outside this process — it reads
    and writes our own rows — so the reason for the hour does not apply, and
    paying it anyway meant a court that freed at 1:05 went on announcing the
    next match for 3:15 until the hour came round.

    Two minutes, which is what the scheduler gives it on production. There is no
    argument for staging being slower at a job that costs nothing.
    """
    import asyncio
    import random

    await asyncio.sleep(random.uniform(20, 90))

    while True:
        try:
            await _refresh_schedule_estimates()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("standalone schedule-estimate refresh failed: %s", exc)
        await asyncio.sleep(120)


async def _sweep_oop_verifications() -> None:
    """Carry the host verifier's verdicts into the alert pipeline.

    The verifier (a headless Claude Code cron on the host) writes one JSON per
    checked document into /data/oop_pdfs/results. It cannot write to the DB
    itself — every "database is locked" incident this app has had came from a
    second writer — so this sweep, inside the app's own writer, is the only
    path a verdict takes into system_logs. Problems alert (the digest mails
    them); clean passes log quietly. Files then move to results/done, and
    PDFs or verdicts older than 14 days are pruned.
    """
    import json as _json
    import os
    import time as _time

    from app.services.system_log import app_log

    base = "/data/oop_pdfs"
    res_dir, done_dir = f"{base}/results", f"{base}/results/done"
    try:
        os.makedirs(done_dir, exist_ok=True)
        names = [n for n in os.listdir(res_dir) if n.endswith(".json")]
    except FileNotFoundError:
        return
    for name in sorted(names):
        path = f"{res_dir}/{name}"
        try:
            with open(path) as f:
                r = _json.load(f)
        except Exception as exc:
            logger.error("Unreadable verifier result %s: %s", name, exc)
            os.replace(path, f"{done_dir}/{name}")
            continue
        doc_id = r.get("doc_id")
        problems = r.get("problems") or []
        fixed = r.get("fixed") or []
        # One status email per processed PDF, every outcome — the owner's
        # request, so this category has its OWN channel and alerts.py exempts
        # it from the digest (whose caps and dedup would eat routine statuses,
        # and whose failure alert would double the needs-attention email). If
        # the send itself fails, send_async logs that under its own category,
        # which still digests — the safety net survives.
        meta = None
        try:
            from app.models.schedule import ScheduleDocument
            from app.models.tournament import Tournament
            async with AsyncSessionLocal() as db2:
                doc = await db2.get(ScheduleDocument, doc_id) if doc_id else None
                t = (await db2.get(Tournament, doc.tournament_id)) if doc else None
                meta = (t.name if t else "Unknown tournament",
                        str(doc.play_date) if doc else "?")
        except Exception as exc:
            logger.error("oop_verify: could not load doc %s meta: %s", doc_id, exc)
            meta = ("Unknown tournament", "?")

        if r.get("ok") and not problems:
            msg = (f"OOP PDF doc {doc_id}: verifier fixed "
                   f"{len(fixed)} problem(s) itself" if fixed else
                   f"OOP PDF verified clean: doc {doc_id}")
            await app_log("info", "oop_verify",
                          f"{msg} ({r.get('summary') or 'no notes'})",
                          {"doc_id": doc_id, "fixed": fixed[:20]})
            try:
                from app.services.email import send_oop_status
                await send_oop_status(doc_id=doc_id, tournament=meta[0],
                                      play_date=meta[1], ok=True, fixed=fixed,
                                      problems=[], summary=r.get("summary") or "")
            except Exception as exc:
                logger.error("oop_verify status email failed: %s", exc)
        else:
            # The one case a human still needs: the machine TRIED and could
            # not finish the repair. The email carries `handoff` — the text to
            # paste into an interactive Claude Code session to continue the
            # fix (rendered whole by _alert_handoff, not the truncating
            # key/value strip). The verifier writes its own; a verdict without
            # one (crashed run, old format) gets a synthesized version so the
            # email NEVER arrives without something paste-able.
            handoff = (r.get("handoff") or "").strip() or (
                f"The automated OOP verifier could not fully repair schedule "
                f"document {doc_id} (see /data/oop_pdfs/{doc_id}.pdf on "
                f"jupiter, results in data/oop_pdfs/results/done/). "
                f"Remaining problems: "
                + ("; ".join(str(pr) for pr in problems[:10]) or "unknown — "
                   "the verifier died without a verdict; read "
                   "~/upsetalert/logs/verify_oop.log")
                + ". Diagnose the root cause in backend/app/services/"
                "oop_parser.py or schedule.py, fix the bug class so it "
                "cannot recur, re-ingest the document, and verify the "
                "schedule page matches the PDF.")
            await app_log("error", "oop_verify",
                          f"OOP verifier could not fix doc {doc_id}: "
                          f"{len(problems) or 'unknown'} problem(s) remain",
                          {"doc_id": doc_id, "problems": problems[:20],
                           "fixed": fixed[:20], "summary": r.get("summary"),
                           "handoff": handoff},
                          dedup_key=f"oop_verify_{doc_id}", dedup_hours=24)
            try:
                from app.services.email import send_oop_status
                await send_oop_status(doc_id=doc_id, tournament=meta[0],
                                      play_date=meta[1], ok=False, fixed=fixed,
                                      problems=problems,
                                      summary=r.get("summary") or "",
                                      handoff=handoff)
            except Exception as exc:
                logger.error("oop_verify status email failed: %s", exc)
        os.replace(path, f"{done_dir}/{name}")

    # Retention: a verified sheet's PDF has served its purpose after two weeks.
    cutoff = _time.time() - 14 * 86400
    for d in (base, done_dir):
        try:
            for n in os.listdir(d):
                fp = f"{d}/{n}"
                if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
        except FileNotFoundError:
            pass


async def _prune_score_snapshots() -> None:
    """Clear score histories nobody can scrub any more — a draw's snapshots go
    one day after the draw completes. See services/score_history.py for the
    retention decision and the two backstops behind it."""
    from app.services import score_history
    from app.services.system_log import app_log

    try:
        async with AsyncSessionLocal() as db:
            removed = await score_history.prune(db)
        if removed:
            logger.info("Score history: pruned %d snapshot(s)", removed)
            await app_log("info", "score_history",
                          f"Pruned {removed} score snapshot(s) from completed draws",
                          {"removed": removed})
    except Exception as exc:
        logger.error("Score-history prune failed: %s", exc)
        err = describe_exception(exc)
        await app_log("error", "score_history", f"Prune failed: {err}",
                      {"error": err}, dedup_key="score_prune_fail", dedup_hours=24)



def _on_shutdown_quietly(fn):
    """Wrap a scheduled job so being cancelled at shutdown is not an ERROR.

    asyncio.CancelledError inherits from BaseException, not Exception, so every
    `except Exception` guard in these jobs steps aside for it. Stopping the
    container mid-tick therefore cancelled whatever HTTP call was in flight, the
    CancelledError travelled up to APScheduler, and APScheduler logged it as a
    job failure:

      Job "_refresh_order_of_play (trigger: interval[0:15:00] ...)" raised an
      exception ... asyncio.CancelledError

    Nothing was wrong. The process was asked to stop and it stopped. But it
    lands in the same error log the alert digest reads, and an error that means
    "a deploy happened" trains the reader to skim past errors that do not.

    Deliberately applied to EVERY job rather than to the one that happened to be
    caught: any of them can be mid-request when the signal arrives, and which
    one it is depends only on timing.

    Swallowed rather than re-raised, and only here at the outermost frame — the
    task is being torn down with the loop, so there is nothing left to co-
    operate with, and re-raising only puts the same line back in the log.
    """
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except asyncio.CancelledError:
            logger.info("%s cancelled — shutting down", fn.__name__)
            return None
    return wrapper


def start_scheduler() -> None:
    scheduler.add_job(
        _on_shutdown_quietly(_auto_discover_tournaments),
        "cron",
        hour=0,
        minute=0,
        id="auto_discover",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _on_shutdown_quietly(_prune_score_snapshots),
        "cron",
        hour=4,
        minute=30,
        id="prune_score_snapshots",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _on_shutdown_quietly(_sweep_oop_verifications),
        "interval",
        minutes=5,
        id="sweep_oop_verifications",
        misfire_grace_time=240,
    )
    # Scrape active tournaments every 30 minutes so live scores update promptly.
    scheduler.add_job(
        _on_shutdown_quietly(_refresh_active_tournaments),
        "interval",
        minutes=30,
        id="refresh_active",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _on_shutdown_quietly(_sync_subscriptions),
        "interval",
        minutes=5,
        id="sync_subscriptions",
        misfire_grace_time=120,
    )
    # Centralized "draw released" email dispatch — see _notify_pending_draw_releases
    # docstring. 10 min cadence matches the 10 min stability cooldown, so worst
    # case a stable release waits one extra tick (up to ~10 min) before emailing.
    scheduler.add_job(
        _on_shutdown_quietly(_notify_pending_draw_releases),
        "interval",
        minutes=10,
        id="notify_draw_releases",
        misfire_grace_time=300,
    )
    # Weekly round-completion digest. 10 min matches the draw-release job: a
    # round that completes the batch waits at most one tick before going out.
    scheduler.add_job(
        _on_shutdown_quietly(_notify_pending_round_digests),
        "interval",
        minutes=10,
        id="notify_round_digests",
        misfire_grace_time=300,
    )
    # Player swaps in draws people are already competing in. 5 min rather than
    # the 10 the other notify jobs use: the cooldown (20 min) is what decides
    # when a batch goes out, so a tighter tick only sharpens that boundary — it
    # cannot make anything send sooner than the draw settling allows.
    scheduler.add_job(
        _on_shutdown_quietly(_notify_pending_draw_changes),
        "interval",
        minutes=5,
        id="notify_draw_changes",
        misfire_grace_time=300,
    )
    # Measure finished matches against the field and tell the minority who
    # called them right. Also on 5 min: this job does the measuring as well as
    # the sending, and a match that is measured late is notified late.
    scheduler.add_job(
        _on_shutdown_quietly(_notify_pending_standout_picks),
        "interval",
        minutes=5,
        id="notify_standout_picks",
        misfire_grace_time=300,
    )
    # Sanity sweep for silent failures (released-but-not-open, wiki title
    # never resolving) — see _check_draw_health docstring.
    scheduler.add_job(
        _on_shutdown_quietly(_check_draw_health),
        "interval",
        minutes=60,
        id="check_draw_health",
        misfire_grace_time=600,
    )
    scheduler.add_job(
        _on_shutdown_quietly(_check_rankings_health),
        "interval",
        minutes=60,
        id="check_rankings_health",
        misfire_grace_time=600,
    )
    # Keep the "Highest_Rank" baseline user's picks current as entries/rankings
    # firm up. 10 min cadence matches the draw-release notify job.
    scheduler.add_job(
        _on_shutdown_quietly(_sync_highest_rank_bot),
        "interval",
        minutes=10,
        id="sync_highest_rank_bot",
        misfire_grace_time=300,
    )
    # Error/warning email digest. 15 min is the worst-case delay before a new
    # problem reaches the inbox; the daily cap and 24h recurrence gate live in
    # alerts.py, not here, so shortening this cadence can't increase volume.
    # Deliberately NOT also kicked off at startup like the jobs below: a deploy
    # restart is when transient connect/timeout noise is most likely, and the
    # first interval tick picks up anything real 15 minutes later anyway.
    scheduler.add_job(
        _on_shutdown_quietly(_scan_system_alerts),
        "interval",
        minutes=15,
        id="scan_system_alerts",
        misfire_grace_time=600,
    )
    # Order-of-play links. 15 min: the tours revise the schedule a handful of
    # times a day, so a tighter tick buys nothing, and this is the one job that
    # fetches a multi-megabyte file per active tournament. protennislive rate
    # limited a burst of ~12 requests in two minutes during development, which
    # is a useful reminder that these endpoints are not built for polling.
    scheduler.add_job(
        _on_shutdown_quietly(_refresh_order_of_play),
        "interval",
        minutes=15,
        id="refresh_order_of_play",
        misfire_grace_time=600,
    )
    # Expected start times, re-chained against live results. 2 min rather than
    # the 15 the PDF job uses: a finishing match is what moves an estimate, and
    # that arrives from ESPN every 60 seconds. Touches no network at all — it
    # only re-reads matches and rewrites the estimates.
    # Browser-driven, so deliberately infrequent: one page load a week, at a
    # quiet hour. New tournaments are picked up within a week; existing ids are
    # never overwritten, so a failed run changes nothing.
    scheduler.add_job(
        _on_shutdown_quietly(_refresh_atp_tournament_ids),
        "cron",
        day_of_week="mon",
        hour=4,
        minute=20,
        id="refresh_atp_tournament_ids",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _on_shutdown_quietly(_refresh_schedule_estimates),
        "interval",
        minutes=2,
        id="refresh_schedule_estimates",
        misfire_grace_time=120,
    )
    scheduler.add_job(
        _on_shutdown_quietly(_refresh_weekly_rankings),
        "cron",
        day_of_week="sun",
        hour=18,
        minute=0,
        timezone="America/Los_Angeles",  # PDT/PST — always fires at 6pm Pacific
        id="refresh_weekly_rankings",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _on_shutdown_quietly(_refresh_elo),
        "cron",
        day_of_week="mon",
        hour=1,
        minute=30,
        id="refresh_elo",
        misfire_grace_time=3600,
    )
    eventstream._on_season_page_edit = _on_season_page_edit
    scheduler.start()
    logger.info("Tournament discovery scheduled (daily at midnight UTC)")
    logger.info("Active tournament refresh scheduled (every 30 min)")
    logger.info("EventStreams listener started for real-time draw updates")
    logger.info("Subscription sync scheduled (every 5 min)")
    logger.info("Weekly rankings refresh scheduled (Sunday 6pm PDT)")
    logger.info("Draw-release notification check scheduled (every 10 min)")
    logger.info("Round-complete digest check scheduled (every 10 min)")
    logger.info("Draw-change notification check scheduled (every 5 min)")
    logger.info("Standout-pick notification check scheduled (every 5 min)")
    logger.info("Draw health check scheduled (every 60 min)")
    logger.info("Rankings/ELO freshness check scheduled (every 60 min)")
    logger.info("Highest_Rank bot sync scheduled (every 10 min)")
    logger.info("System alert scan scheduled (every 15 min)")
    asyncio.create_task(eventstream.start())
    asyncio.create_task(espn_monitor.start())
    # Subscribe immediately on startup so EventStreams catches edits from the
    # first second — don't wait up to 5 min for the interval job to fire.
    asyncio.create_task(_sync_subscriptions())
    # Force-refresh on startup to catch any results that arrived while the
    # server was down.
    asyncio.create_task(_refresh_active_tournaments(force_refresh=True))
    # Catch any draw releases that went stable while the server was down.
    asyncio.create_task(_notify_pending_draw_releases())
    # Same for draw changes and standout picks recorded before a restart — both
    # are cooldown-gated, so a batch mid-settle at shutdown would otherwise wait
    # for the first interval tick.
    asyncio.create_task(_notify_pending_draw_changes())
    asyncio.create_task(_notify_pending_standout_picks())
    # Catch any tournaments that were already stuck before this restart.
    asyncio.create_task(_check_draw_health())
    asyncio.create_task(_check_rankings_health())
    # Catch any draws whose entries/rankings firmed up while the server was down.
    asyncio.create_task(_sync_highest_rank_bot())
    # Backfill DOB for any te_players missing it (no-op if all already set).
    from app.services.rankings import backfill_all_dob, refresh_elo_ratings
    asyncio.create_task(backfill_all_dob())
    asyncio.create_task(refresh_elo_ratings())


def stop_scheduler() -> None:
    import asyncio

    asyncio.create_task(eventstream.stop())
    espn_monitor.stop()
    scheduler.shutdown(wait=False)
