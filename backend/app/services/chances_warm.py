"""Every position of the scrub, computed when the match that created it
finishes — so the slider reads a number instead of waiting for one.

THE ARITHMETIC THAT MAKES THIS CHEAP. A rewound position is the draw as it
stood after N results: `scoring._snapshot` clears every later winner AND the
players a later slot only learned from them, so position 40's snapshot is a
pure function of the first 40 results. Nothing that happens afterwards can
change it. Neither do the picks. So each position needs computing EXACTLY ONCE
— a finished match adds one new position and leaves every earlier one alone.

What used to ruin that: `DrawOdds.cache_key` carried the live score of every
match in play, so the poller's next tick — ten seconds — made a different key
and discarded every walk for that draw. Now a past moment is priced without
what is on court (`without_live`), which is also the honest snapshot: a match
being played now was not two sets old back then.

Only for draws whose PICKS ARE SHUT: a pick is part of the cache key, so
warming a draw people are still editing is work thrown away. See `warm_draw`.

So: ~0.2s of arithmetic per completed match per scope (each league with picks,
plus the global table), and a first pass over a draw's whole timeline that is
paid once per ratings week. Both run here, in the background, behind the same
one-at-a-time gate user requests use, so a warm pass can never outrank someone
waiting for a screen.
"""

import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.league import LeagueMember
from app.models.prediction import UserPrediction
from app.models.tournament import Draw, Match
from app.services.locking import draw_lock_state
from app.services.scoring import _points_table, chances_at_async, finish_range_walks
from app.services.win_chances import draw_odds

logger = logging.getLogger(__name__)

# How far back a draw is still worth keeping warm. Someone reading an older one
# pays for the positions they visit, as before. Kept short on purpose: the
# nightly rating recompute moves `ratings_as_of` and therefore invalidates
# every walk, so this window IS the nightly bill — 141s per Slam draw.
ACTIVE_WINDOW = timedelta(days=21)

# STOP A SCOPE AFTER THIS MANY POSITIONS ALREADY HELD. Positions are walked
# newest-first and a finished match adds exactly one, at the end: so in the
# steady state the first position is new and everything older is held, and
# there is nothing to gain from reading the other hundred and twenty keys.
# Eight rather than one because a result can land in the MIDDLE of the
# timeline (a Wikipedia backfill, a corrected completed_at), which shifts
# every position after it — and that region is contiguous with the end, so
# walking backwards recomputes all of it before reaching eight holds.
HOLDS_BEFORE_STOP = 8

# One warm pass at a time, and never two for the same draw.
_lock = asyncio.Lock()


def _timeline_ids(all_matches: list) -> list[int]:
    """The timeline order the routers publish. It has to match theirs exactly,
    or a warmed position is a different moment than the one asked for."""
    done = [m for m in all_matches if m.status == "completed" and not m.is_bye]
    return [m.id for m in sorted(
        done, key=lambda m: (m.completed_at is not None, m.completed_at or "", m.id))]


async def _scopes(db, draw_id: int) -> list[tuple[str, dict]]:
    """Every field of brackets that can ask about this draw: the global table,
    and one per league with picks in it — a league's walk ranks only its own
    members, so it is a different question with a different answer.

    A cash pool matters here: the league's view of that draw hides members who
    did not pay in, which changes who is being ranked. Warming the wrong set
    would compute a cache entry nobody ever asks for.
    """
    rows = (await db.execute(
        select(UserPrediction.user_id, UserPrediction.match_id, UserPrediction.predicted_winner_id)
        .where(UserPrediction.draw_id == draw_id,
               UserPrediction.predicted_winner_id.isnot(None)))).all()
    if not rows:
        return []
    everyone: dict[int, dict] = {}
    for uid, mid, w in rows:
        everyone.setdefault(uid, {})[mid] = w

    out: list[tuple[str, dict]] = [("global", everyone)]
    league_ids = (await db.execute(
        select(LeagueMember.league_id).where(LeagueMember.user_id.in_(everyone)).distinct())).scalars().all()
    from app.routers.leagues import _pool_visible
    for lid in league_ids:
        members = (await db.execute(
            select(LeagueMember.user_id).where(LeagueMember.league_id == lid))).scalars().all()
        visible = await _pool_visible(db, lid, draw_id)
        picks = {u: everyone[u] for u in members
                 if u in everyone and (visible is None or u in visible)}
        if picks:
            out.append((f"league:{lid}", picks))
    return out


async def warm_draw(draw_id: int, budget: float = 240.0) -> dict:
    """Fill the cache for every timeline position of one draw, every scope.

    Positions already held cost a dict lookup, so a pass over an unchanged
    draw is nearly free and this can be called as often as it likes. `budget`
    bounds a FIRST pass over a long timeline: whatever it does not reach is
    picked up by the next call (or by the reader, as before).
    """
    started = time.monotonic()
    computed = held = 0
    async with AsyncSessionLocal() as db:
        draw = await db.get(Draw, draw_id)
        if draw is None:
            return {"draw": draw_id, "skipped": "no such draw"}
        all_matches = (await db.execute(
            select(Match).where(Match.draw_id == draw_id))).scalars().all()
        tl = _timeline_ids(all_matches)
        if not tl:
            return {"draw": draw_id, "positions": 0}
        # NEVER WARM A DRAW WHOSE PICKS CAN STILL CHANGE. The picks are part of
        # the walk's cache key — they have to be, a different bracket is a
        # different answer — so one person saving one pick invalidates every
        # position of every scope they belong to. Precomputing into that is
        # work thrown away, over and over.
        #
        # Which costs nothing, because of WHEN the two lock modes close:
        #   draw_start (109 of 111 draws): the bracket shuts at the first ball,
        #     so while picks are open there is no timeline to scrub at all.
        #   r1_progressive: picks stay editable through round one. That IS a
        #     window where both are true, and it is the one this skips — those
        #     positions are computed when someone actually visits them, as
        #     they were before any of this.
        # Once shut, picks only move by an admin editing them or a qualifier
        # resolving into someone's bracket, and the five-minute pass is the
        # self-heal for both.
        lock = await draw_lock_state(db, draw)
        if not lock.draw_locked:
            return {"draw": draw_id, "positions": len(tl), "skipped": "picks still open"}
        scopes = await _scopes(db, draw_id)
        if not scopes:
            return {"draw": draw_id, "positions": len(tl), "scopes": 0}
        odds = await draw_odds(db, draw, all_matches)
        if odds is None:
            return {"draw": draw_id, "positions": len(tl), "skipped": "no odds"}
        pts = _points_table(draw)
        rounds = draw.num_rounds or 7
        # NEWEST FIRST. A reader who scrubs is most often looking at what just
        # happened, and a first pass that runs out of budget should have done
        # the positions they will reach first.
        for name, picks in scopes:
            holds = 0
            for pos in range(len(tl), 0, -1):
                if holds >= HOLDS_BEFORE_STOP:
                    break
                if time.monotonic() - started > budget:
                    logger.info("chances warm: budget reached on %s at %s", name, pos)
                    return {"draw": draw_id, "computed": computed, "held": held,
                            "scopes": len(scopes), "positions": len(tl),
                            "seconds": round(time.monotonic() - started, 1),
                            "incomplete": True}
                before = finish_range_walks()
                await chances_at_async(draw_id, all_matches, tl, pos, pts, rounds, picks, odds=odds)
                # Did that WALK, or just read? The engine's own counter, not a
                # stopwatch: the last positions of a draw enumerate eight
                # futures and beat any "surely that was cached" threshold.
                if finish_range_walks() == before:
                    held += 1
                    holds += 1
                else:
                    computed += 1
                    holds = 0
                # A REAL PAUSE, not just a yield. The walk runs in a worker
                # thread but its Python half holds the GIL, and the live
                # poller has ten seconds to fetch and store every score on
                # court. Twenty milliseconds between positions keeps a long
                # warm pass off its back for the price of two seconds per
                # hundred positions.
                await asyncio.sleep(0.02)
    return {"draw": draw_id, "computed": computed, "held": held, "scopes": len(scopes),
            "positions": len(tl), "seconds": round(time.monotonic() - started, 1)}


def warm_soon(draw_ids: list[int], budget: float = 120.0) -> None:
    """Fire a warm pass off the caller's path, swallowing its failures.

    The callers are the results sweep and the scheduler, and neither should
    ever fail — or log a bare "Task exception was never retrieved" — because a
    cache could not be filled. The numbers are still correct without this;
    they are just computed when someone asks.
    """
    async def _run():
        try:
            out = await warm_draws(draw_ids, budget=budget)
            if out.get("computed"):
                logger.info("chances warm: %s", out)
        except Exception:
            logger.warning("chances warm failed for %s", draw_ids, exc_info=True)
    asyncio.create_task(_run())


async def warm_draws(draw_ids: list[int], budget: float = 240.0) -> dict:
    """Warm several draws under one lock, sharing one budget."""
    out: dict = {"draws": [], "computed": 0}
    async with _lock:
        started = time.monotonic()
        for did in draw_ids:
            left = budget - (time.monotonic() - started)
            if left <= 5:
                break
            r = await warm_draw(did, budget=left)
            out["draws"].append(r)
            out["computed"] += r.get("computed", 0)
    return out


async def active_draw_ids(db, window: Optional[timedelta] = None) -> list[int]:
    """Draws worth keeping warm: recent, and with something played.

    Newest first, so the tournament being watched is warmed before an older
    one that nobody has open.
    """
    since = date.today() - (window or ACTIVE_WINDOW)
    rows = (await db.execute(
        select(Draw.id)
        .where(Draw.start_date >= since)
        .order_by(Draw.start_date.desc()))).scalars().all()
    out = []
    for did in rows:
        played = (await db.execute(
            select(Match.id).where(Match.draw_id == did, Match.status == "completed",
                                   Match.is_bye == False).limit(1))).first()   # noqa: E712
        if played:
            out.append(did)
    return out


async def warm_active(budget: float = 240.0) -> dict:
    """The periodic pass. Nearly free when nothing has finished since the last
    one, which is what makes it safe to run on a short interval: it is also
    the self-heal after anything that invalidates a walk — a nightly rating
    recompute, a model change, an admin editing someone's picks."""
    async with AsyncSessionLocal() as db:
        ids = await active_draw_ids(db)
    if not ids:
        return {"draws": 0}
    return await warm_draws(ids, budget=budget)
