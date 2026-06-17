"""
Background scheduler:
- Auto-discovers and adds tournaments daily for current + next 2 years
- Real-time EventStreams listener for tournament draw page updates
- Dynamic subscriptions: subscribes on tournament add, unsubscribes on completion
"""

import logging
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.tournament import Tournament
from app.services.eventstream import EventStreamListener

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()
eventstream = EventStreamListener()


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
            try:
                await _do_scrape(t, db, force_refresh=force_refresh)
                await db.commit()
                logger.info("Refreshed %s %s (%s)", t.year, t.name, t.gender)
            except Exception as exc:
                logger.warning("Failed to refresh %s: %s", t.wiki_page_title, exc)
                await db.rollback()


async def _sync_subscriptions() -> None:
    """Sync EventStreams subscriptions with active/pending tournaments."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Tournament).where(
                Tournament.status.in_(["upcoming", "open", "active"])
            )
        )
        tournaments = result.scalars().all()
        active_titles = {t.wiki_page_title for t in tournaments}

        # Subscribe to new tournaments
        for title in active_titles - eventstream.subscriptions:
            await eventstream.subscribe(title)

        # Unsubscribe from completed tournaments
        for title in eventstream.subscriptions - active_titles:
            await eventstream.unsubscribe(title)


def start_scheduler() -> None:
    import asyncio

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
    scheduler.start()
    logger.info("Tournament discovery scheduled (daily at midnight UTC)")
    logger.info("Active tournament refresh scheduled (every 30 min)")
    logger.info("EventStreams listener started for real-time draw updates")
    logger.info("Subscription sync scheduled (every 5 min)")
    asyncio.create_task(eventstream.start())
    # Subscribe immediately on startup so EventStreams catches edits from the
    # first second — don't wait up to 5 min for the interval job to fire.
    asyncio.create_task(_sync_subscriptions())
    # Force-refresh on startup to catch any results that arrived while the
    # server was down.
    asyncio.create_task(_refresh_active_tournaments(force_refresh=True))


def stop_scheduler() -> None:
    import asyncio

    asyncio.create_task(eventstream.stop())
    scheduler.shutdown(wait=False)
