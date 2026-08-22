"""
Keeps every draw joinable to Sofascore, by itself.

The identity layer — `draws.sofa_tournament_id` / `sofa_season_id` and
`draw_entries.sofa_player_id` — is what every other Sofascore service reads. The
live poller filters by tournament and joins players by id; the results sweep
pages that season's finished events; the doubles sweep needs the doubles
uniqueTournament. A draw without those ids is invisible to all three, and shows
no live score at all, forever, silently.

It was resolved ONCE, by hand, for Cincinnati on 2026-08-20, and nothing ever
called it again. On 2026-08-22 that meant Cincinnati was the only tournament on
the calendar with live scoring, Winston-Salem and Monterrey were starting the
next morning with none, and the US Open was nine days out with none — and the
first anyone would have known is that the scores stopped when Cincinnati
finished. The automatic cutover would also have sat closed forever, having no
new matches to compare.

So: a loop. Resolution is idempotent and already skips draws with nothing
pending, so the only thing this adds is the calendar.

WHY IT REPEATS RATHER THAN RUNNING ONCE PER DRAW. A draw's entries arrive over
days — the bracket is published before qualifying finishes, and the last slots
fill on the morning of play. A single pass can only stamp who was in the field
when it ran. RESOLVE_RETRY_HOURS puts a floor under that so the handful of names
Sofascore genuinely does not carry cost one attempt every six hours rather than
one per pass forever.
"""

import asyncio
import logging

from app.core.config import settings
from app.database import AsyncSessionLocal
from app.services.sofascore import (RESOLVE_RETRY_HOURS, SofascoreBlocked,
                                    resolve_pending_draws)
from app.services.system_log import app_log

logger = logging.getLogger(__name__)

# Hourly. A draw needs its ids before its first ball, and draws are published
# days ahead — so this has hours of slack, and the retry floor means most passes
# find nothing to do and issue no requests at all.
POLL_INTERVAL = 3600.0

# Let the rest of the app settle, and stagger away from the other Sofascore
# loops so a restart does not fire every one of them at the same instant.
STARTUP_DELAY = 120.0

# A block costs live scoring until it clears, so back off hard rather than
# retrying on the hourly cadence into a host that has just refused us.
BLOCKED_BACKOFF = 6 * 3600.0


async def _once() -> int:
    async with AsyncSessionLocal() as db:
        reports = await resolve_pending_draws(db, retry_hours=RESOLVE_RETRY_HOURS)
        await db.commit()

    if not reports:
        return 0
    stamped = sum(r.get("resolved", 0) for r in reports)
    for r in reports:
        if r.get("error"):
            # Worth a record but not an alarm: a tournament whose field is not
            # on Sofascore yet is the ordinary state days before it starts, and
            # the retry will pick it up. It only becomes a problem if it is
            # still true on the morning of play, which the draw-health check is
            # the right place to notice.
            logger.info("Sofascore resolve: %s — %s", r.get("draw"), r["error"])
        else:
            logger.info("Sofascore resolve: %s — %d/%d entries stamped",
                        r.get("draw"), r.get("resolved", 0), r.get("total", 0))
    return stamped


async def start() -> None:
    if not (settings.sofascore_live_enabled or settings.sofascore_results_enabled):
        # Nothing reads the ids, so spending requests to keep them fresh would
        # buy nothing.
        return
    logger.info("Sofascore draw resolver started (interval=%.0fs)", POLL_INTERVAL)
    await asyncio.sleep(STARTUP_DELAY)
    while True:
        delay = POLL_INTERVAL
        try:
            await _once()
        except SofascoreBlocked as exc:
            delay = BLOCKED_BACKOFF
            logger.warning("Sofascore resolve blocked, backing off %.0fh: %s",
                           BLOCKED_BACKOFF / 3600, exc)
            await app_log(
                "warning", "sofascore",
                f"Draw resolution refused by Sofascore ({exc}). Backing off "
                f"{BLOCKED_BACKOFF / 3600:.0f}h. Draws resolved before this keep "
                f"their ids and keep scoring; any not yet resolved will have no "
                f"live scores until this clears.",
                dedup_key="sofa_resolve_blocked", dedup_hours=6)
        except Exception as exc:
            logger.warning("Sofascore draw resolve failed: %s", exc)
        await asyncio.sleep(delay)
