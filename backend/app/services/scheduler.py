"""
Background scheduler:
- Auto-discovers and adds tournaments daily for current + next 2 years
- Real-time EventStreams listener for tournament draw page updates
- Dynamic subscriptions: subscribes on tournament add, unsubscribes on completion
"""

import asyncio
import logging
import traceback
from datetime import date, datetime, timedelta, timezone

import httpx

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.tournament import Draw
from app.services.espn_monitor import ESPNMonitor
from app.services.eventstream import EventStreamListener

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
                # "Page not found" for a future year is expected — Wikipedia page won't
                # exist until the season is underway. Skip app_log entirely.
                is_future_not_found = year > current_year and "Page not found" in str(exc)
                if not is_future_not_found:
                    from app.services.system_log import app_log
                    await app_log("error", "scheduler", f"Tournament discovery failed for {year}: {exc}",
                                  {"year": year, "error": str(exc)})

    # Sync EventStream subscriptions after DB is updated
    await _sync_subscriptions()


async def _refresh_active_tournaments(force_refresh: bool = False) -> None:
    """
    Daily catch-up scrape covering two groups:

    1. Active tournaments — start_date within the last 14 days, not yet completed.
       Catches match results / tournament completion that EventStreams may have missed.

    2. Upcoming tournaments awaiting draw release — expected DA or Qual date has
       arrived but the draw hasn't been confirmed yet (no draw_released_*_at).
       This is what sets the checkmarks when players are placed in the draw.
    """
    from sqlalchemy import or_
    from app.routers.tournaments import _do_scrape

    today = date.today()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Draw).where(
                Draw.status != "completed",
                or_(
                    # Group 1: active window (started within last 14 days)
                    (
                        Draw.start_date.isnot(None) &
                        (Draw.start_date <= today) &
                        (Draw.start_date >= today - timedelta(days=14))
                    ),
                    # Group 2: upcoming — DA draw date has arrived, not yet confirmed
                    (
                        Draw.draw_release_direct.isnot(None) &
                        (Draw.draw_release_direct <= today) &
                        Draw.draw_released_direct_at.is_(None)
                    ),
                    # Group 3: upcoming — Qual date has arrived, not yet confirmed
                    (
                        Draw.draw_release_qualifiers.isnot(None) &
                        (Draw.draw_release_qualifiers <= today) &
                        Draw.draw_released_qualifiers_at.is_(None)
                    ),
                )
            )
        )
        tournaments = result.scalars().all()
        logger.info("Daily refresh: %d tournaments to check", len(tournaments))
        for t in tournaments:
            await asyncio.sleep(5)  # throttle Wikipedia requests to avoid 429s
            # Capture before any DB operation can expire these attributes
            t_id = t.id
            t_name = t.name
            t_wiki = t.wiki_page_title
            try:
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
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                logger.debug("Network blip refreshing %s: %s", t_wiki, exc)
                await db.rollback()
            except Exception as exc:
                tb = traceback.format_exc()
                logger.warning("Failed to refresh %s: %s\n%s", t_wiki, exc, tb)
                await db.rollback()
                from app.services.system_log import app_log
                await app_log("error", "scheduler", f"Failed to refresh '{t_name}': {exc}",
                              {"tournament_id": t_id, "tournament_name": t_name,
                               "wiki_title": t_wiki, "error": str(exc),
                               "traceback": tb},
                              dedup_key=f"refresh_fail_{t_id}_{type(exc).__name__}", dedup_hours=1.0)


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
        logger.error("Weekly rankings job failed: %s", exc)
        await app_log("error", "rankings", f"Weekly rankings job failed: {exc}",
                      {"week_date": str(week_date), "error": str(exc)},
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
DRAW_RELEASE_NOTIFY_COOLDOWN = timedelta(minutes=20)


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
    cutoff = datetime.now(timezone.utc) - DRAW_RELEASE_NOTIFY_COOLDOWN
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Draw).where(
                Draw.draw_released_direct_at.isnot(None),
                Draw.draw_release_notified_at.is_(None),
                Draw.draw_release_detected_at.isnot(None),
                Draw.draw_release_detected_at <= cutoff,
            )
        )
        tournaments = result.scalars().all()
        if not tournaments:
            return

        to_notify = [(t.id, t.category or "", t.gender, t.year, t.name) for t in tournaments]
        now = datetime.now(timezone.utc)
        for t in tournaments:
            t.draw_release_notified_at = now
        await db.commit()

    from app.services.notifications import notify_draw_released
    for t_id, category, gender, year, name in to_notify:
        asyncio.create_task(notify_draw_released(t_id, category, gender, year, name))
    logger.info("Draw-release notification: dispatched for %d tournament(s)", len(to_notify))


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
        if t.draw_release_direct is not None:
            release_overdue = (today - t.draw_release_direct).days >= 1
        else:
            # No expected release date known — draws are essentially always
            # out by the day before start, so treat that as the deadline.
            release_overdue = t.start_date is not None and (t.start_date - today).days <= 1
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


def start_scheduler() -> None:
    scheduler.add_job(
        _auto_discover_tournaments,
        "cron",
        hour=0,
        minute=0,
        id="auto_discover",
        misfire_grace_time=3600,
    )
    # Scrape active tournaments every 30 minutes so live scores update promptly.
    scheduler.add_job(
        _refresh_active_tournaments,
        "interval",
        minutes=30,
        id="refresh_active",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _sync_subscriptions,
        "interval",
        minutes=5,
        id="sync_subscriptions",
        misfire_grace_time=120,
    )
    # Centralized "draw released" email dispatch — see _notify_pending_draw_releases
    # docstring. 10 min cadence comfortably resolves the 20 min stability cooldown.
    scheduler.add_job(
        _notify_pending_draw_releases,
        "interval",
        minutes=10,
        id="notify_draw_releases",
        misfire_grace_time=300,
    )
    # Sanity sweep for silent failures (released-but-not-open, wiki title
    # never resolving) — see _check_draw_health docstring.
    scheduler.add_job(
        _check_draw_health,
        "interval",
        minutes=60,
        id="check_draw_health",
        misfire_grace_time=600,
    )
    scheduler.add_job(
        _refresh_weekly_rankings,
        "cron",
        day_of_week="sun",
        hour=18,
        minute=0,
        timezone="America/Los_Angeles",  # PDT/PST — always fires at 6pm Pacific
        id="refresh_weekly_rankings",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _refresh_elo,
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
    logger.info("Draw health check scheduled (every 60 min)")
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
    # Catch any tournaments that were already stuck before this restart.
    asyncio.create_task(_check_draw_health())
    # Backfill DOB for any te_players missing it (no-op if all already set).
    from app.services.rankings import backfill_all_dob, refresh_elo_ratings
    asyncio.create_task(backfill_all_dob())
    asyncio.create_task(refresh_elo_ratings())


def stop_scheduler() -> None:
    import asyncio

    asyncio.create_task(eventstream.stop())
    espn_monitor.stop()
    scheduler.shutdown(wait=False)
