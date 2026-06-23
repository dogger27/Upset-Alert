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

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.tournament import Tournament
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
                from app.services.system_log import app_log
                # "Page not found" for a future year is expected — Wikipedia page won't
                # exist until later in the year. Log as warning, not error.
                is_future_not_found = year > current_year and "Page not found" in str(exc)
                level = "warning" if is_future_not_found else "error"
                await app_log(level, "scheduler", f"Tournament discovery failed for {year}: {exc}",
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
            select(Tournament).where(
                Tournament.status != "completed",
                or_(
                    # Group 1: active window (started within last 14 days)
                    (
                        Tournament.start_date.isnot(None) &
                        (Tournament.start_date <= today) &
                        (Tournament.start_date >= today - timedelta(days=14))
                    ),
                    # Group 2: upcoming — DA draw date has arrived, not yet confirmed
                    (
                        Tournament.draw_release_direct.isnot(None) &
                        (Tournament.draw_release_direct <= today) &
                        Tournament.draw_released_direct_at.is_(None)
                    ),
                    # Group 3: upcoming — Qual date has arrived, not yet confirmed
                    (
                        Tournament.draw_release_qualifiers.isnot(None) &
                        (Tournament.draw_release_qualifiers <= today) &
                        Tournament.draw_released_qualifiers_at.is_(None)
                    ),
                )
            )
        )
        tournaments = result.scalars().all()
        logger.info("Daily refresh: %d tournaments to check", len(tournaments))
        for t in tournaments:
            await asyncio.sleep(1)  # throttle Wikipedia requests to avoid 429s
            # Capture before any DB operation can expire these attributes
            t_id = t.id
            t_name = t.name
            t_wiki = t.wiki_page_title
            try:
                prev_draw_released = t.draw_released_direct_at
                prev_status = t.status

                await _do_scrape(t, db, force_refresh=force_refresh)
                await db.commit()
                logger.info("Refreshed %s %s (%s)", t.year, t_name, t.gender)

                # Prefetch H2H and DOB for any new matchups/players (uses own sessions)
                from app.services.h2h import prefetch_h2h_for_draw
                from app.services.rankings import prefetch_dob_for_draw
                await prefetch_h2h_for_draw(t_id)
                await prefetch_dob_for_draw(t_id)

                # Fire notifications as background tasks so they don't block the scrape loop
                from app.services.notifications import notify_draw_released, notify_tournament_complete
                just_released = prev_draw_released is None and t.draw_released_direct_at is not None
                just_completed = prev_status != "completed" and t.status == "completed"
                if just_released:
                    asyncio.create_task(notify_draw_released(
                        t_id, t.category or "", t.gender, t.year, t_name,
                    ))
                if just_completed:
                    asyncio.create_task(notify_tournament_complete(t_id))
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
    """Re-run title discovery when a season page is edited, update wiki_page_titles."""
    import re
    from sqlalchemy import and_
    from app.services.scraper import fetch_wikitext
    from app.services.discovery import parse_season_schedule

    m = re.match(r'^(\d{4}) (ATP|WTA) Tour$', season_title)
    if not m:
        return
    year = int(m.group(1))
    gender = 'M' if m.group(2) == 'ATP' else 'F'

    try:
        wikitext, _ = await fetch_wikitext(season_title, force_refresh=True)
        discovered = parse_season_schedule(wikitext, year, gender)

        async with AsyncSessionLocal() as db:
            updated = 0
            for d in discovered:
                result = await db.execute(
                    select(Tournament).where(
                        and_(
                            Tournament.year == year,
                            Tournament.gender == gender,
                            Tournament.name == d.name,
                            Tournament.wiki_page_title != d.wiki_page_title,
                        )
                    )
                )
                t = result.scalar_one_or_none()
                if t and d.wiki_page_title:
                    logger.info("Season page edit: correcting %s title %r → %r",
                                t.name, t.wiki_page_title, d.wiki_page_title)
                    t.wiki_page_title = d.wiki_page_title
                    updated += 1
            if updated:
                await db.commit()
                logger.info("Updated %d tournament title(s) from %s edit", updated, season_title)

        await _sync_subscriptions()
    except Exception as exc:
        logger.warning("Failed to refresh titles from season page %s: %s", season_title, exc)


async def _refresh_elo() -> None:
    from app.services.rankings import refresh_elo_ratings
    await refresh_elo_ratings()


async def _sync_subscriptions() -> None:
    """Sync EventStreams subscriptions with active/pending tournaments + season pages."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Tournament).where(
                Tournament.status.in_(["upcoming", "open", "active"])
            )
        )
        tournaments = result.scalars().all()

    # Tournament draw pages: use page_id when known, title-only when page doesn't exist yet
    wanted: dict[str, int | None] = {t.wiki_page_title: t.wiki_page_id for t in tournaments}

    # Season pages: always subscribed by title (we don't store their page IDs)
    for title in _season_pages():
        wanted[title] = None

    current = eventstream.subscriptions
    added = removed = 0
    for title, page_id in wanted.items():
        if title not in current:
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
    asyncio.create_task(eventstream.start())
    asyncio.create_task(espn_monitor.start())
    # Subscribe immediately on startup so EventStreams catches edits from the
    # first second — don't wait up to 5 min for the interval job to fire.
    asyncio.create_task(_sync_subscriptions())
    # Force-refresh on startup to catch any results that arrived while the
    # server was down.
    asyncio.create_task(_refresh_active_tournaments(force_refresh=True))
    # Backfill DOB for any te_players missing it (no-op if all already set).
    from app.services.rankings import backfill_all_dob, refresh_elo_ratings
    asyncio.create_task(backfill_all_dob())
    asyncio.create_task(refresh_elo_ratings())


def stop_scheduler() -> None:
    import asyncio

    asyncio.create_task(eventstream.stop())
    espn_monitor.stop()
    scheduler.shutdown(wait=False)
