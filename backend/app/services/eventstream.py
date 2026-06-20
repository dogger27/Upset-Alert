"""
Real-time Wikimedia EventStreams listener for tournament draw updates.

Two-tier subscription:
- ID subscriptions  (page_id → title): for pages that already exist on Wikipedia.
  Matched against event["pageid"] — immune to page renames.
- Title subscriptions (title): for pages not yet created (wiki_page_id is NULL).
  Matched against event["title"] as a fallback; promoted to ID subscription the
  moment the page is created and we learn its page_id.
"""

import asyncio
import json
import logging
import re
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)

WIKIMEDIA_STREAM_URL = "https://stream.wikimedia.org/v2/stream/recentchange"

_SEASON_PAGE_RE = re.compile(r'^\d{4} (ATP|WTA) Tour$')


class EventStreamListener:

    def __init__(self):
        self._id_subs: dict[int, str] = {}    # page_id → title (known pages)
        self._title_subs: set[str] = set()    # titles for not-yet-created pages
        self.client: Optional[httpx.AsyncClient] = None
        self.running = False
        self._on_season_page_edit: Optional[Callable] = None

    # ── Public subscription API ──────────────────────────────────────────────

    async def subscribe(self, title: str, page_id: Optional[int] = None) -> None:
        if page_id:
            if page_id not in self._id_subs:
                self._id_subs[page_id] = title
                logger.debug("Subscribed by ID %d (%s)", page_id, title)
        else:
            if title not in self._title_subs:
                self._title_subs.add(title)
                logger.debug("Subscribed by title %r (no page ID yet)", title)

    async def unsubscribe(self, title: str, page_id: Optional[int] = None) -> None:
        if page_id and page_id in self._id_subs:
            del self._id_subs[page_id]
            logger.debug("Unsubscribed ID %d (%s)", page_id, title)
        self._title_subs.discard(title)

    @property
    def subscriptions(self) -> set[str]:
        """All currently watched titles (for logging / sync diffing)."""
        return set(self._id_subs.values()) | self._title_subs

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.client = httpx.AsyncClient(timeout=None)
        asyncio.create_task(self._listen_loop())
        logger.info("EventStreams listener started")

    async def stop(self) -> None:
        self.running = False
        if self.client:
            await self.client.aclose()
        logger.info("EventStreams listener stopped")

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        while self.running:
            try:
                await self._stream_events()
            except Exception as exc:
                logger.warning("EventStreams connection lost: %s. Reconnecting in 5s…", exc)
                await asyncio.sleep(5)

    async def _stream_events(self) -> None:
        async with self.client.stream("GET", WIKIMEDIA_STREAM_URL) as response:
            async for line in response.aiter_lines():
                if not line or not self.running:
                    continue
                if line.startswith("data:"):
                    try:
                        data_str = line[5:].strip()
                        if data_str:
                            await self._handle_event(json.loads(data_str))
                    except json.JSONDecodeError:
                        pass
                    except Exception as exc:
                        logger.debug("Error processing event: %s", exc)

    async def _handle_event(self, event: dict) -> None:
        if event.get("wiki") != "enwiki":
            return

        action = event.get("type")
        if action not in ("edit", "new"):
            return

        title = event.get("title", "")
        page_id = event.get("pageid")  # integer, present on edit/new events

        # ── Match by page ID (reliable, immune to renames) ──────────────────
        if page_id and page_id in self._id_subs:
            matched_title = self._id_subs[page_id]

            if _SEASON_PAGE_RE.match(matched_title):
                logger.info("Season page edited: %s — refreshing tournament titles", matched_title)
                if self._on_season_page_edit:
                    asyncio.create_task(self._on_season_page_edit(matched_title))
                return

            verb = "created" if action == "new" else "updated"
            logger.info("Draw %s (ID %d): %s", verb, page_id, matched_title)
            asyncio.create_task(self._scrape_tournament(matched_title))
            return

        # ── Match by title (pages not yet created / season pages we subscribed
        #    by title because we don't cache their page IDs) ──────────────────
        if title and title in self._title_subs:
            if _SEASON_PAGE_RE.match(title):
                logger.info("Season page edited: %s — refreshing tournament titles", title)
                if self._on_season_page_edit:
                    asyncio.create_task(self._on_season_page_edit(title))
                return

            verb = "created" if action == "new" else "updated"
            logger.info("Draw %s (title match): %s", verb, title)

            # Promote title → ID subscription now that we know the page_id
            if page_id:
                self._title_subs.discard(title)
                self._id_subs[page_id] = title
                logger.debug("Promoted %r to ID subscription (%d)", title, page_id)

            asyncio.create_task(self._scrape_tournament(title))

    async def _scrape_tournament(self, title: str) -> None:
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
                    logger.info("Scraping draw for %s %s", tournament.year, tournament.name)
                    await _do_scrape(tournament, db, force_refresh=True)
                    await db.commit()
        except Exception as exc:
            logger.warning("Failed to scrape %s: %s", title, exc)
