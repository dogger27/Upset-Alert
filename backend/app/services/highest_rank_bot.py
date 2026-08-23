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
from app.services.system_log import app_log

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


def project_bracket(
    entries: list[DrawEntry], matches: list[Match],
    user_picks: Optional[dict[int, int]] = None,
) -> dict[int, int]:
    """{match_id: winner_entry_id} for every match that can be resolved.

    Advances the better-ranked entrant, EXCEPT where `user_picks` already says
    otherwise — and then carries that choice forward. A user who picks an upset
    in the first round must not meet the player they just knocked out in the
    second: the projection has to follow their bracket, not the seeding's.

    A stored pick for someone who cannot actually reach the match is ignored FOR
    PROPAGATION only (the stored row is never touched here). That happens when
    an earlier pick changes and a later one is left stranded behind it, and the
    alternative — carrying a player forward out of a match they are not in —
    invents a bracket nobody chose.

    Matches where neither side has resolved to a real entry are omitted, which
    is an unnamed qualifier slot: there is nobody to advance yet.
    """
    picks_in = user_picks or {}
    entries_by_id = {e.id: e for e in entries}
    by_round: dict[int, dict[int, Match]] = {}
    for m in matches:
        by_round.setdefault(m.round_number, {})[m.match_number] = m
    if not by_round:
        return {}

    rounds_sorted = sorted(by_round)
    picks: dict[int, int] = {}
    # Projected winner entry id, keyed by (round_number, match_number).
    winner_of: dict[tuple[int, int], Optional[int]] = {}

    def decide(match, a, b):
        """The user's choice where it is one of these two, else the favourite."""
        chosen = picks_in.get(match.id)
        if chosen is not None and chosen in {e.id for e in (a, b) if e}:
            return entries_by_id.get(chosen)
        if a and b:
            return _better(a, b)
        return a or b

    first_round = rounds_sorted[0]
    for match_number, match in by_round[first_round].items():
        p1 = entries_by_id.get(match.player1_id) if match.player1_id else None
        p2 = entries_by_id.get(match.player2_id) if match.player2_id else None
        # A bye is not a contest and cannot be upset: whoever is there advances.
        winner = (p1 or p2) if match.is_bye else decide(match, p1, p2)
        winner_of[(first_round, match_number)] = winner.id if winner else None
        if winner:
            picks[match.id] = winner.id

    for r in rounds_sorted[1:]:
        for match_number, match in by_round[r].items():
            id_a = winner_of.get((r - 1, match_number * 2 - 1))
            id_b = winner_of.get((r - 1, match_number * 2))
            ea = entries_by_id.get(id_a) if id_a else None
            eb = entries_by_id.get(id_b) if id_b else None
            winner = decide(match, ea, eb)
            winner_of[(r, match_number)] = winner.id if winner else None
            if winner:
                picks[match.id] = winner.id

    return picks


def simulate_highest_rank_picks(
    entries: list[DrawEntry], matches: list[Match]
) -> dict[int, int]:
    """The pure seeding projection, with nobody's opinion in it — what the
    Highest_Rank account plays."""
    return project_bracket(entries, matches)


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


async def fill_missing_picks(db, draw, user_id: int,
                             restrict_to: Optional[set] = None) -> int:
    """Give a user the favourite on every match they have not picked. Returns
    how many were written; the caller commits.

    NO MATCH ANYONE COULD PICK is left blank for someone who has entered a draw.
    Byes are the exception and are never written; see below. An unpicked
    match scores nothing and reads as an oversight rather than a decision, so
    the default is the same projection the Highest_Rank account plays — the
    better-ranked player advancing — and the only picks that differ from it are
    the ones the user deliberately changed. An upset is a choice; a blank is
    not.

    Their own picks are read first and the projection is built AROUND them, so a
    first-round upset carries through: the player they knocked out does not
    reappear in the second round holding their pick. Nothing already stored is
    ever overwritten, whether it was chosen or defaulted earlier.

    `restrict_to` narrows this to particular matches. The save path uses it for
    matches that are already LOCKED, which is the one case where the fill has to
    happen before the request is validated: a user joining a draw that is under
    way cannot pick those, and without a stored pick any value they submit reads
    as a change to a locked match and is refused.

    A match the projection omits is skipped — an unnamed qualifier slot, where a
    default would be a guess about who is even playing.
    """
    stored = {p.match_id: p.predicted_winner_id for p in (await db.execute(
        select(UserPrediction).where(
            UserPrediction.user_id == user_id,
            UserPrediction.draw_id == draw.id))).scalars().all()}

    entries = (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == draw.id))).scalars().all()
    matches = (await db.execute(
        select(Match).where(Match.draw_id == draw.id))).scalars().all()
    projected = project_bracket(entries, matches, stored)

    written = 0
    for match in matches:
        if match.id in stored:
            continue
        # A BYE IS NOT A MATCH TO PREDICT. It carries a winner from the moment
        # the draw is released and there is no contest to have an opinion about,
        # which is why every scoring query in the app excludes byes explicitly —
        # a pick sitting on one is called a stray pick there, and scoring it
        # would hand out free points. Writing them deliberately would be
        # manufacturing exactly what those filters exist to ignore.
        if match.is_bye:
            continue
        if restrict_to is not None and match.id not in restrict_to:
            continue
        winner_id = projected.get(match.id)
        if winner_id is None:
            continue
        db.add(UserPrediction(user_id=user_id, draw_id=draw.id,
                              match_id=match.id, predicted_winner_id=winner_id))
        written += 1

    if written:
        await app_log(
            "info", "predictions",
            f"Filled {written} unpicked match(es) with the better-ranked player "
            f"for user {user_id} in draw {draw.id}",
            {"draw_id": draw.id, "user_id": user_id, "filled": written})
    return written


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
