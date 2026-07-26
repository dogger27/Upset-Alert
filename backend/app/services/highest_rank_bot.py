"""
"Highest_Rank" baseline user — a synthetic account that always predicts the
higher-ranked player to win every match. Gives real users a fixed baseline to
compare their own bracket against in Global standings.

The whole bracket is simulated once from initial bracket assignment + rankings
(NOT from live results — Match.player1_id/player2_id for round 2+ stay null
in the DB until real results land, but the bracket TREE is fully known the
moment the draw is released). Re-running this is idempotent: it recomputes
the full projected bracket and upserts, so it self-corrects as qualifiers/
alternates get named or rankings are backfilled, right up until the draw locks.
"""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tournament import Draw, DrawEntry, Match
from app.models.prediction import UserPrediction
from app.models.user import User

logger = logging.getLogger(__name__)

HIGHEST_RANK_USERNAME = "Highest_Rank"


def _rank_key(entry: DrawEntry) -> tuple:
    """Lower is better. Missing ranking falls back to seed, then entry id, so
    the comparison is always deterministic even for unranked/qualifier slots."""
    return (
        entry.ranking if entry.ranking is not None else float("inf"),
        entry.seed if entry.seed is not None else float("inf"),
        entry.id,
    )


def _better(a: DrawEntry, b: DrawEntry) -> DrawEntry:
    return a if _rank_key(a) <= _rank_key(b) else b


def simulate_highest_rank_picks(
    entries: list[DrawEntry], matches: list[Match]
) -> dict[int, int]:
    """Returns {match_id: predicted_winner_entry_id} for every match that can
    be resolved from the current entries/rankings. Matches where neither
    branch has resolved to a real entry yet (e.g. an unnamed qualifier slot)
    are simply omitted."""
    entries_by_id = {e.id: e for e in entries}
    by_round: dict[int, dict[int, Match]] = {}
    for m in matches:
        by_round.setdefault(m.round_number, {})[m.match_number] = m
    if not by_round:
        return {}

    rounds_sorted = sorted(by_round)
    picks: dict[int, int] = {}
    # Simulated winner entry id, keyed by (round_number, match_number).
    winner_of: dict[tuple[int, int], Optional[int]] = {}

    first_round = rounds_sorted[0]
    for match_number, match in by_round[first_round].items():
        p1 = entries_by_id.get(match.player1_id) if match.player1_id else None
        p2 = entries_by_id.get(match.player2_id) if match.player2_id else None
        if match.is_bye:
            winner = p1 or p2
        elif p1 and p2:
            winner = _better(p1, p2)
        else:
            winner = p1 or p2
        winner_of[(first_round, match_number)] = winner.id if winner else None
        if winner:
            picks[match.id] = winner.id

    for r in rounds_sorted[1:]:
        for match_number, match in by_round[r].items():
            id_a = winner_of.get((r - 1, match_number * 2 - 1))
            id_b = winner_of.get((r - 1, match_number * 2))
            ea = entries_by_id.get(id_a) if id_a else None
            eb = entries_by_id.get(id_b) if id_b else None
            winner = _better(ea, eb) if (ea and eb) else (ea or eb)
            winner_of[(r, match_number)] = winner.id if winner else None
            if winner:
                picks[match.id] = winner.id

    return picks


async def get_bot_user(db: AsyncSession) -> Optional[User]:
    result = await db.execute(select(User).where(User.username == HIGHEST_RANK_USERNAME))
    return result.scalar_one_or_none()


async def sync_draw_picks(db: AsyncSession, draw: Draw, bot_user_id: int) -> bool:
    """Recompute and upsert the bot's full-bracket prediction for one draw.
    Returns True if anything was written."""
    entries_result = await db.execute(select(DrawEntry).where(DrawEntry.draw_id == draw.id))
    entries = entries_result.scalars().all()
    matches_result = await db.execute(select(Match).where(Match.draw_id == draw.id))
    matches = matches_result.scalars().all()
    if not entries or not matches:
        return False

    picks = simulate_highest_rank_picks(entries, matches)

    existing_result = await db.execute(
        select(UserPrediction).where(
            UserPrediction.user_id == bot_user_id,
            UserPrediction.draw_id == draw.id,
        )
    )
    existing = {p.match_id: p for p in existing_result.scalars().all()}

    for match_id, winner_id in picks.items():
        if match_id in existing:
            existing[match_id].predicted_winner_id = winner_id
        else:
            db.add(UserPrediction(
                user_id=bot_user_id,
                draw_id=draw.id,
                match_id=match_id,
                predicted_winner_id=winner_id,
            ))

    # Clear any previously-projected pick that's no longer resolvable (branch
    # got a fresh unnamed qualifier slot upstream) so stale winners don't linger.
    for match_id in set(existing) - set(picks):
        await db.delete(existing[match_id])

    return True


async def sync_open_draws(db: AsyncSession) -> int:
    """Scheduler entry point — only touches draws that haven't locked yet.
    Called on its own interval; idempotent, so re-running is always safe."""
    bot = await get_bot_user(db)
    if not bot:
        return 0

    result = await db.execute(select(Draw).where(Draw.draw_released_direct_at.isnot(None)))
    draws = result.scalars().all()

    synced = 0
    for draw in draws:
        if draw.is_locked:
            continue
        if await sync_draw_picks(db, draw, bot.id):
            synced += 1
    await db.commit()
    return synced
