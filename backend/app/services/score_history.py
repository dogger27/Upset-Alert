"""
The journey of a live score, one row per change — see models/score_history.py
for why it exists and why it is transient.

record_snapshot is called from sofascore_live's hot path and must therefore be
harmless: it adds to the session the poller already owns and never commits,
flushes or queries, so it cannot take the write lock on its own or lengthen the
transaction beyond the insert itself.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.models.score_history import MatchScoreSnapshot, ScheduleScoreSnapshot

logger = logging.getLogger(__name__)

# One day after the draw finishes, the history goes — the popup then shows the
# final score alone. Chosen by the user: the scrubber matters while a
# tournament is being followed, not months later.
KEEP_AFTER_DRAW_DAYS = 1
# A match can never legitimately produce this many score changes; beyond it
# something is looping, and the newest rows are the ones worth keeping.
PER_MATCH_CAP = 2000
# Snapshots this old belong to matches that never completed (abandoned draws,
# walkovers recorded oddly) and would otherwise live forever.
ABSOLUTE_MAX_DAYS = 60


def record_snapshot(db, match_id: int, snap: dict) -> None:
    """Append one score moment. The caller owns the commit."""
    db.add(MatchScoreSnapshot(
        match_id=match_id,
        at=datetime.now(timezone.utc).replace(tzinfo=None),
        snap=snap,
    ))


def record_entry_snapshot(db, schedule_entry_id: int, snap: dict) -> None:
    """record_snapshot for a row that exists only as a schedule entry.
    Same contract: adds to the caller's session, never commits or queries."""
    db.add(ScheduleScoreSnapshot(
        schedule_entry_id=schedule_entry_id,
        at=datetime.now(timezone.utc).replace(tzinfo=None),
        snap=snap,
    ))


async def prune(db) -> int:
    """Delete history nobody can scrub any more. Returns rows removed."""
    from app.models.tournament import Draw, Match

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    removed = 0

    # Draws completed more than a day ago: everything they hold goes at once.
    done_cutoff = now - timedelta(days=KEEP_AFTER_DRAW_DAYS)
    old_draws = (await db.execute(
        select(Match.draw_id)
        .join(Draw, Draw.id == Match.draw_id)
        .where(Draw.status == "completed")
        .group_by(Match.draw_id)
        .having(func.max(Match.completed_at) < done_cutoff)
    )).scalars().all()
    if old_draws:
        match_ids = (await db.execute(
            select(Match.id).where(Match.draw_id.in_(old_draws)))).scalars().all()
        if match_ids:
            res = await db.execute(delete(MatchScoreSnapshot).where(
                MatchScoreSnapshot.match_id.in_(match_ids)))
            removed += res.rowcount or 0

    # Runaway single matches: keep the newest PER_MATCH_CAP rows.
    over = (await db.execute(
        select(MatchScoreSnapshot.match_id)
        .group_by(MatchScoreSnapshot.match_id)
        .having(func.count() > PER_MATCH_CAP)
    )).scalars().all()
    for mid in over:
        keep_from = (await db.execute(
            select(MatchScoreSnapshot.id)
            .where(MatchScoreSnapshot.match_id == mid)
            .order_by(MatchScoreSnapshot.id.desc())
            .offset(PER_MATCH_CAP - 1).limit(1))).scalar_one_or_none()
        if keep_from is not None:
            res = await db.execute(delete(MatchScoreSnapshot).where(
                MatchScoreSnapshot.match_id == mid,
                MatchScoreSnapshot.id < keep_from))
            removed += res.rowcount or 0

    # The backstop for matches that never resolved at all.
    res = await db.execute(delete(MatchScoreSnapshot).where(
        MatchScoreSnapshot.at < now - timedelta(days=ABSOLUTE_MAX_DAYS)))
    removed += res.rowcount or 0

    # Entry-keyed history (qualifying singles, doubles): no draw to complete,
    # so the day itself is the clock — scrubbed while the sheet is current,
    # gone KEEP_AFTER_DRAW_DAYS after its play date passes. Same per-row cap
    # and absolute backstop as the match table.
    from app.models.schedule import ScheduleEntry
    old_entries = (await db.execute(
        select(ScheduleEntry.id).where(
            ScheduleEntry.play_date < (now - timedelta(days=KEEP_AFTER_DRAW_DAYS)).date())
    )).scalars().all()
    if old_entries:
        res = await db.execute(delete(ScheduleScoreSnapshot).where(
            ScheduleScoreSnapshot.schedule_entry_id.in_(old_entries)))
        removed += res.rowcount or 0
    over = (await db.execute(
        select(ScheduleScoreSnapshot.schedule_entry_id)
        .group_by(ScheduleScoreSnapshot.schedule_entry_id)
        .having(func.count() > PER_MATCH_CAP)
    )).scalars().all()
    for eid in over:
        keep_from = (await db.execute(
            select(ScheduleScoreSnapshot.id)
            .where(ScheduleScoreSnapshot.schedule_entry_id == eid)
            .order_by(ScheduleScoreSnapshot.id.desc())
            .offset(PER_MATCH_CAP - 1).limit(1))).scalar_one_or_none()
        if keep_from is not None:
            res = await db.execute(delete(ScheduleScoreSnapshot).where(
                ScheduleScoreSnapshot.schedule_entry_id == eid,
                ScheduleScoreSnapshot.id < keep_from))
            removed += res.rowcount or 0
    res = await db.execute(delete(ScheduleScoreSnapshot).where(
        ScheduleScoreSnapshot.at < now - timedelta(days=ABSOLUTE_MAX_DAYS)))
    removed += res.rowcount or 0

    if removed:
        await db.commit()
    return removed
