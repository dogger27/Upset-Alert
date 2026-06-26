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
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)

WIKIMEDIA_STREAM_URL = "https://stream.wikimedia.org/v2/stream/recentchange"
# Don't replay more than this on reconnect — avoids a flood after a long outage
_MAX_REPLAY_WINDOW = timedelta(hours=1)

_SEASON_PAGE_RE = re.compile(r'^\d{4} (ATP|WTA) Tour$')


_HEARTBEAT_INTERVAL = 60  # seconds


class EventStreamListener:

    def __init__(self):
        self._id_subs: dict[int, str] = {}    # page_id → title (known pages)
        self._title_subs: set[str] = set()    # titles for not-yet-created pages
        self.client: Optional[httpx.AsyncClient] = None
        self.running = False
        self._on_season_page_edit: Optional[Callable] = None
        self._last_event_ts: Optional[str] = None  # ISO 8601 dt from last event
        self._enwiki_count: int = 0           # enwiki events since last heartbeat
        self._heartbeat_task: Optional[asyncio.Task] = None

    # ── Public subscription API ──────────────────────────────────────────────

    def current_page_id_for(self, title: str) -> Optional[int]:
        """Return the page_id currently subscribed for this title, or None."""
        return next((pid for pid, t in self._id_subs.items() if t == title), None)

    async def subscribe(self, title: str, page_id: Optional[int] = None) -> None:
        if page_id:
            # If this title is already subscribed under a DIFFERENT page_id, remove
            # the stale entry first — this happens when a wrong page_id gets corrected.
            old_pid = self.current_page_id_for(title)
            if old_pid is not None and old_pid != page_id:
                del self._id_subs[old_pid]
                logger.info(
                    "Updated ID subscription for %r: page_id %d → %d",
                    title, old_pid, page_id,
                )
            self._id_subs[page_id] = title
            self._title_subs.discard(title)  # promote away from title-only if needed
            if old_pid != page_id:
                logger.debug("Subscribed by ID %d (%s)", page_id, title)
        else:
            if title not in self._title_subs and title not in set(self._id_subs.values()):
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
        self.client = httpx.AsyncClient(
            timeout=None,
            headers={
                "User-Agent": (
                    "UpsetAlert/1.0 (https://upsetalert.paulwiens.com; "
                    "pdwiens@gmail.com) python-httpx"
                )
            },
        )
        asyncio.create_task(self._listen_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("EventStreams listener started")

    async def stop(self) -> None:
        self.running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self.client:
            await self.client.aclose()
        logger.info("EventStreams listener stopped")

    async def _heartbeat_loop(self) -> None:
        while self.running:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            count = self._enwiki_count
            self._enwiki_count = 0
            id_sub_summary = {pid: title for pid, title in self._id_subs.items()}
            logger.info(
                "EventStreams heartbeat: %d enwiki events in last %ds | "
                "id_subs=%d %s | title_subs=%d %s | last_event_ts=%s",
                count, _HEARTBEAT_INTERVAL,
                len(self._id_subs), list(id_sub_summary.keys()),
                len(self._title_subs), list(self._title_subs),
                self._last_event_ts,
            )

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        while self.running:
            try:
                await self._stream_events()
            except Exception as exc:
                logger.warning("EventStreams connection lost: %s. Reconnecting in 5s…", exc)
                await asyncio.sleep(5)

    def _stream_url(self) -> str:
        """Build the stream URL, resuming from the last known position when available."""
        if self._last_event_ts:
            try:
                last = datetime.fromisoformat(self._last_event_ts.replace("Z", "+00:00"))
                cutoff = datetime.now(timezone.utc) - _MAX_REPLAY_WINDOW
                since = max(last, cutoff)
                ts = since.strftime("%Y-%m-%dT%H:%M:%SZ")
                logger.info("EventStreams reconnecting from %s", ts)
                return f"{WIKIMEDIA_STREAM_URL}?since={ts}"
            except Exception:
                pass
        return WIKIMEDIA_STREAM_URL

    async def _stream_events(self) -> None:
        url = self._stream_url()
        logger.info("EventStreams connecting: %s", url)
        async with self.client.stream("GET", url) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f"HTTP {response.status_code} from EventStreams: {body[:200]}"
                )
            logger.info("EventStreams connected (HTTP 200)")
            async for line in response.aiter_lines():
                if not line or not self.running:
                    continue
                if line.startswith("data:"):
                    try:
                        data_str = line[5:].strip()
                        if data_str:
                            event = json.loads(data_str)
                            # Record stream position from every event (not just enwiki)
                            if dt := (event.get("meta") or {}).get("dt"):
                                self._last_event_ts = dt
                            await self._handle_event(event)
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

        self._enwiki_count += 1
        logger.debug("enwiki %s pageid=%s title=%r", action, page_id, title)

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
            import traceback
            tb = traceback.format_exc()
            logger.warning("Failed to scrape %s: %s", title, exc)
            from app.services.system_log import app_log
            await app_log(
                "error", "scheduler",
                f"EventStream scrape failed for '{title}': {exc}",
                {"wiki_title": title, "error": str(exc), "traceback": tb},
                dedup_key=f"eventstream_fail_{title}_{type(exc).__name__}", dedup_hours=1.0,
            )
