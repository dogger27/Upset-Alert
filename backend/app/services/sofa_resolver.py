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
from app.services.draw_dates import release_deadline
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


async def _once() -> tuple[int, set]:
    """Returns (entries stamped, draw ids whose Sofascore field is UNNAMED).

    The second half is for the coverage check in the same pass: "nobody
    stamped" means something different when Sofascore has published a bracket
    of placeholders than when it has published a field of real names and we
    matched none of them.
    """
    async with AsyncSessionLocal() as db:
        reports = await resolve_pending_draws(db, retry_hours=RESOLVE_RETRY_HOURS)
        await db.commit()

    unnamed = {r.get("draw_id") for r in reports if r.get("field_unnamed")}
    if not reports:
        return 0, unnamed
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
    return stamped, unnamed


async def _refine_deadlines(db) -> int:
    """Set the pick deadline from Sofascore's own main-draw schedule.

    A deadline is the first ball, and until now nothing could say when that
    was. Wikipedia gives the calendar — the date range, months ahead, which
    every release date and ranking week is built on — but not a time. ESPN's
    board can once an order of play is published, and before that fills in a
    placeholder that set Guadalajara's deadline eighteen hours early (owner,
    2026-09-12).

    So: for a draw about to start whose picks are still open and whose first
    ball nobody has observed yet, ask Sofascore once per pass. One request,
    and it stops the moment there is an answer — `first_match_at` is the
    record of having one.

    Refuses on the same two grounds ESPN's refinement does, because the
    failure modes are the same whoever publishes them: a start more than a day
    from our own start_date belongs to some other event, and an hour outside a
    plausible session is a placeholder rather than a time.
    """
    from zoneinfo import ZoneInfo

    from app.services.espn_monitor import (SESSION_EARLIEST_HOUR,
                                           SESSION_LATEST_HOUR)
    from app.services.sofascore import first_main_draw_start

    today = date.today()
    horizon = today + timedelta(days=COVERAGE_LEAD_DAYS)
    draws = (await db.execute(
        select(Draw).where(
            Draw.picks_locked_at.is_(None),
            Draw.status.notin_(("active", "completed")),
            Draw.start_date.isnot(None),
            Draw.start_date <= horizon,
            Draw.start_date >= today - timedelta(days=1),
            Draw.first_match_at.is_(None),
            Draw.sofa_tournament_id.isnot(None),
            Draw.sofa_season_id.isnot(None),
            Draw.venue_timezone.isnot(None),
        ))).scalars().all()

    set_count = 0
    for d in draws:
        try:
            first = await first_main_draw_start(d.sofa_tournament_id, d.sofa_season_id)
        except SofascoreBlocked:
            raise
        except Exception:
            logger.warning("Sofascore deadline: %s %s could not be read",
                           d.name, d.year, exc_info=True)
            continue
        if first is None:
            # The main draw is not scheduled yet. Ordinary until a day or two
            # out; the estimate stands and the next pass asks again.
            continue
        try:
            local = first.astimezone(ZoneInfo(d.venue_timezone))
        except Exception:
            continue
        if abs((local.date() - d.start_date).days) > 1:
            logger.info("Sofascore deadline: ignoring %s for %s %s (start_date %s)",
                        local.date(), d.name, d.year, d.start_date)
            continue
        if not (SESSION_EARLIEST_HOUR <= local.hour <= SESSION_LATEST_HOUR):
            logger.info("Sofascore deadline: %s %s first event at %s local — "
                        "not a session start, left alone",
                        d.name, d.year, local.strftime("%H:%M"))
            continue

        old = d.closing_time
        naive = first.replace(tzinfo=None)
        d.first_match_at = naive
        d.first_match_local_hour, d.first_match_local_minute = local.hour, local.minute
        d.day1_start_hour, d.day1_start_minute = local.hour, local.minute
        d.closing_time = naive
        set_count += 1
        await db.commit()
        await app_log(
            "info", "sofascore",
            f"Pick deadline for {d.year} {d.name} "
            f"({'ATP' if d.gender == 'M' else 'WTA'}) set from Sofascore's main "
            f"draw: {local:%a %d %b %H:%M} local (was {old} UTC, now {naive} UTC).",
            {"draw_id": d.id, "old_closing_time": str(old),
             "new_closing_time": str(naive), "first_match_local": local.isoformat()},
            dedup_key=f"sofa_deadline_{d.id}", dedup_hours=24)
    return set_count


async def _coverage_check(db, unnamed: set | None = None) -> None:
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
            # NOT WHILE THE BRACKET IS STILL DUE. This branch says Sofascore
            # has not published the draw — which is exactly the expected state
            # before our own release date, so saying it then is noise. Guadalajara
            # 2026 warned two days before a draw that was not due out until the
            # next day (owner, 2026-09-11). The other branches below still fire
            # in advance on purpose: they need an id to exist, which means the
            # bracket IS published, so a problem then is real.
            deadline = release_deadline(d.start_date, d.draw_release_direct)
            if deadline is None or today >= deadline:
                problem = ("no Sofascore tournament id, so nothing can score it — "
                           "usually a bracket Sofascore has not published yet")
        else:
            stamped = (await db.execute(
                select(func.count()).select_from(DrawEntry).where(
                    DrawEntry.draw_id == d.id,
                    DrawEntry.sofa_player_id.isnot(None)))).scalar_one()
            if stamped == 0:
                # AN ID IS NOT A FIELD. This branch used to fire on the premise
                # that an id existing means the bracket is published, so a
                # problem then is real — but Sofascore publishes the TREE
                # first: SP Open came back as thirty slots named R16P1, R16P2 …
                # every one of them disabled, two days out (owner, 2026-09-12).
                # Nothing can match a placeholder, so "not one player resolved"
                # was the ordinary state of a draw nobody has named yet.
                #
                # Still said the moment play is DUE, whatever the reason —
                # that is this module's whole guarantee, and a draw on court
                # with placeholders for a field is exactly as unscoreable as
                # one with no ids at all.
                # `unnamed is None` means nobody told us — no information is
                # not evidence of innocence, so it warns, as it always did.
                if due or unnamed is None or d.id not in unnamed:
                    problem = ("a tournament id but not one player resolved, so "
                               "no match on it can be joined to a live event")
                else:
                    problem = None
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
            stamped, unnamed = await _once()
            # The first ball, from the one source that publishes it days ahead.
            async with AsyncSessionLocal() as db:
                await _refine_deadlines(db)
            # AFTER resolving, so a draw fixed on this very pass is not reported
            # as broken a second later.
            async with AsyncSessionLocal() as db:
                await _coverage_check(db, unnamed)
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
