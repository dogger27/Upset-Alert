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
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, or_, select

from app.core.config import settings
from app.database import AsyncSessionLocal
from app.models.schedule import ScheduleEntry
from app.models.tournament import Draw, DrawEntry, Match
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

# How far ahead of its first ball a draw must be joinable. Two days is comfortably
# after a bracket is published and comfortably before anyone needs a score from it,
# so a warning here is actionable rather than merely early.
COVERAGE_LEAD_DAYS = 2

# How long after a match was due on court before its having no score is worth
# saying out loud. Long enough to cover a rain delay or a five-setter running
# over on the same court, short enough to still be "before play gets away".
COVERAGE_GRACE = timedelta(hours=3)


async def _play_was_due(db, draw, now: datetime) -> bool:
    """Should a match on this draw have been on court by now?

    `start_date` is a DATE and this clock is UTC, so a draw at an American venue
    counts as having started from about 6pm the previous evening, local — hours
    before the first ball. Both of Sunday's draws alerted eleven times on the
    Saturday evening for having no scores, when their first match was still
    twenty hours away. That is not a fault being caught early; it is a fault
    being invented.

    The order of play knows when play actually starts, so it is asked. Main-draw
    singles only, because that is what `matches` holds and therefore what the
    caller is looking for scores on.
    """
    earliest = (await db.execute(
        select(func.min(ScheduleEntry.expected_start_at)).where(
            ScheduleEntry.draw_id == draw.id,
            ScheduleEntry.stage == "main",
            ScheduleEntry.discipline == "singles",
            ScheduleEntry.expected_start_at.isnot(None)))).scalar_one_or_none()
    if earliest is not None:
        if earliest.tzinfo is None:
            earliest = earliest.replace(tzinfo=timezone.utc)
        return now - earliest >= COVERAGE_GRACE
    # No sheet to go on. A bare date cannot say anything sharper than a whole
    # day, so wait one — still well inside a tournament, and never on the
    # evening before it starts.
    return draw.start_date < now.date()


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


async def _coverage_check(db) -> None:
    """Say so when a draw is about to be played and cannot be scored.

    THIS IS THE POINT OF THE WHOLE MODULE. Everything above is a mechanism, and
    a mechanism that fails silently is indistinguishable from one that was never
    built — which is exactly how this went wrong: resolution ran once by hand in
    August, nothing called it again, and for two days the only tournament on the
    calendar with live scores was the one somebody had happened to resolve.
    Nothing was broken. Nothing logged. There was simply no score, and no reason
    for anyone to look.

    So the guarantee is not "the resolver works". It is that a draw about to be
    played without the means to be scored says so, whatever the reason — an
    unpublished bracket, a block, a name nothing matches, or some future cause
    nobody has thought of. Checked from the OUTCOME rather than from any of the
    steps, so it stays true if the steps are rewritten.
    """
    now = datetime.now(timezone.utc)
    today = date.today()
    horizon = today + timedelta(days=COVERAGE_LEAD_DAYS)
    draws = (await db.execute(
        select(Draw).where(
            Draw.status != "completed",
            Draw.start_date.isnot(None),
            Draw.start_date <= horizon,
            or_(Draw.end_date.is_(None), Draw.end_date >= today),
        ))).scalars().all()

    for d in draws:
        # Whether play is actually DUE, not merely whether the calendar has
        # reached the start date — the other branches still fire in advance, on
        # purpose, but they should not claim a draw is under way while it isn't.
        due = d.start_date <= today and await _play_was_due(db, d, now)
        when = "under way" if due else f"starts {d.start_date}"
        problem = None

        if not (d.sofa_tournament_id and d.sofa_season_id):
            problem = ("no Sofascore tournament id, so nothing can score it — "
                       "usually a bracket Sofascore has not published yet")
        else:
            stamped = (await db.execute(
                select(func.count()).select_from(DrawEntry).where(
                    DrawEntry.draw_id == d.id,
                    DrawEntry.sofa_player_id.isnot(None)))).scalar_one()
            if stamped == 0:
                problem = ("a tournament id but not one player resolved, so no "
                           "match on it can be joined to a live event")
            elif due:
                # Playing, joinable, and still nothing has arrived. That is the
                # case no amount of retrying fixes by itself.
                seen = (await db.execute(
                    select(func.count()).select_from(Match).where(
                        Match.draw_id == d.id,
                        or_(Match.sofa_live_json.isnot(None),
                            Match.sofa_winner_id.isnot(None))))).scalar_one()
                if seen == 0:
                    problem = ("everything resolved, but not one match has "
                               "received a score — check the poller and the "
                               "egress before play gets away")

        if problem:
            logger.warning("Sofascore coverage: %s %s (%s) — %s",
                           d.name, d.year, d.gender, problem)
            await app_log(
                "warning", "sofascore",
                f"'{d.name}' {d.year} ({d.gender}) {when} with {problem}.",
                {"draw_id": d.id, "start_date": str(d.start_date),
                 "sofa_tournament_id": d.sofa_tournament_id,
                 "sofa_season_id": d.sofa_season_id},
                dedup_key=f"sofa_coverage_{d.id}", dedup_hours=24)


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
            # AFTER resolving, so a draw fixed on this very pass is not reported
            # as broken a second later.
            async with AsyncSessionLocal() as db:
                await _coverage_check(db)
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
