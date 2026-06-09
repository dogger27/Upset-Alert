"""
Real-time Wikimedia EventStreams listener for tournament draw updates.

Subscribes to changes on tournament draw pages and triggers immediate scrapes.
"""

import asyncio
import json
import logging
from typing import Optional, Set

import httpx

logger = logging.getLogger(__name__)

WIKIMEDIA_STREAM_URL = "https://stream.wikimedia.org/v2/stream/recentchange"


class EventStreamListener:
    """Listens to Wikimedia EventStreams for tournament draw page changes."""

    def __init__(self):
        self.subscriptions: Set[str] = set()  # Set of wiki_page_titles to watch
        self.client: Optional[httpx.AsyncClient] = None
        self.running = False

    async def start(self) -> None:
        """Start the EventStreams listener."""
        if self.running:
            return
        self.running = True
        self.client = httpx.AsyncClient(timeout=None)
        asyncio.create_task(self._listen_loop())
        logger.info("EventStreams listener started")

    async def stop(self) -> None:
        """Stop the EventStreams listener."""
        self.running = False
        if self.client:
            await self.client.aclose()
        logger.info("EventStreams listener stopped")

    async def subscribe(self, wiki_page_title: str) -> None:
        """Subscribe to changes on a tournament draw page."""
        self.subscriptions.add(wiki_page_title)
        logger.debug("Subscribed to %s (total: %d)", wiki_page_title, len(self.subscriptions))

    async def unsubscribe(self, wiki_page_title: str) -> None:
        """Unsubscribe from a tournament draw page."""
        self.subscriptions.discard(wiki_page_title)
        logger.debug("Unsubscribed from %s (total: %d)", wiki_page_title, len(self.subscriptions))

    async def _listen_loop(self) -> None:
        """Main event listening loop with reconnection."""
        while self.running:
            try:
                await self._stream_events()
            except Exception as exc:
                logger.warning("EventStreams connection lost: %s. Reconnecting in 5s...", exc)
                await asyncio.sleep(5)

    async def _stream_events(self) -> None:
        """Stream and process events from Wikimedia."""
        async with self.client.stream("GET", WIKIMEDIA_STREAM_URL) as response:
            async for line in response.aiter_lines():
                if not line or not self.running:
                    continue

                if line.startswith("data:"):
                    try:
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        event = json.loads(data_str)
                        await self._handle_event(event)
                    except json.JSONDecodeError:
                        pass
                    except Exception as exc:
                        logger.debug("Error processing event: %s", exc)

    async def _handle_event(self, event: dict) -> None:
        """Process a Wikimedia event."""
        wiki = event.get("wiki")
        if wiki != "enwiki":
            return

        action = event.get("type")
        if action != "edit":
            return

        title = event.get("title", "")
        if not title:
            return

        # Check if this is a page we're subscribed to
        if title not in self.subscriptions:
            return

        logger.info("Tournament draw updated on Wikipedia: %s (bot=%s)", title, event.get("bot"))

        # Trigger scrape for this tournament
        from app.database import AsyncSessionLocal
        from app.models.tournament import Tournament
        from app.routers.tournaments import _do_scrape
        from sqlalchemy import select

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Tournament).where(Tournament.wiki_page_title == title)
                )
                tournament = result.scalar_one_or_none()
                if tournament:
                    logger.info("Scraping updated draw for %s %s", tournament.year, tournament.name)
                    await _do_scrape(tournament, db, force_refresh=True)
                    await db.commit()
        except Exception as exc:
            logger.warning("Failed to scrape %s: %s", title, exc)
