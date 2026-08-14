"""
Whether a draw's predictions can still be changed, and which of its matches.

One place, because locking is asserted in three: the write path rejects a
change, the draw endpoint tells the client what to grey out, and the client
decides what to make clickable. Those three disagreeing is the whole failure
mode — a bracket that looks editable and 403s, or worse, one that looks locked
while the server would happily take the change.
"""

from dataclasses import dataclass, field

from sqlalchemy import select

from app.models.tournament import Match
from app.services.settings import (
    LOCK_AT_DRAW_START, LOCK_PROGRESSIVE_R1, resolve_draw_lock_mode,
)


@dataclass
class LockState:
    mode: str
    # The whole bracket is closed; no pick may change.
    draw_locked: bool
    # Individually frozen matches, meaningful only while draw_locked is False.
    locked_match_ids: set = field(default_factory=set)
    # Shown to the user, and logged when a write is refused.
    reason: str = ""


def match_in_play(m: Match) -> bool:
    """
    True once a match can no longer be predicted: it is being played, or it is
    over.

    live_scores_json is what espn_monitor writes while a match is on court, and
    it is cleared when the result lands — so "playing" and "played" are two
    different fields and both have to be asked. A bye has a winner from the
    moment the draw is released, which is correct: there is nothing to predict.
    """
    return m.winner_id is not None or m.live_scores_json is not None or m.status == "completed"


async def draw_lock_state(db, draw) -> LockState:
    """
    Resolve a draw's lock state, stamping its mode if it has none yet.

    selections_unlocked is checked first and wins outright in both modes: it is
    the admin's deliberate override, and it exists precisely to reopen a draw
    that the normal rules have closed.
    """
    mode = await resolve_draw_lock_mode(db, draw)

    if draw.selections_unlocked:
        return LockState(mode=mode, draw_locked=False, reason="unlocked by an admin")

    if mode == LOCK_AT_DRAW_START:
        # Unchanged behaviour: the bracket closes as one, when play begins.
        return LockState(
            mode=mode,
            draw_locked=draw.is_locked,
            reason="the draw has started" if draw.is_locked else "",
        )

    # LOCK_PROGRESSIVE_R1 — matches freeze as they go in play, and the bracket
    # closes once the first round is done.
    rows = (await db.execute(
        select(Match).where(Match.draw_id == draw.id)
    )).scalars().all()
    r1_done = _r1_complete(rows)

    if draw.status == "completed" or r1_done:
        return LockState(
            mode=mode, draw_locked=True,
            reason="every first-round match is complete",
        )

    return LockState(
        mode=mode,
        draw_locked=False,
        locked_match_ids=_locked_with_downstream(rows, draw.num_rounds),
        reason="",
    )


def rejected_changes(state: LockState, submitted: dict, existing: dict) -> list:
    """
    Which submitted picks are not allowed, comparing against what is stored.

    Only a CHANGE to a locked match is refused. The client sends its whole pick
    set on every save, so a bracket with one match under way would otherwise be
    unsavable in its entirety — the user edits an untouched later match and the
    request is rejected because it also carries their (unchanged) pick on the
    one in play.
    """
    if state.draw_locked:
        return list(submitted)
    return [
        mid for mid, winner_id in submitted.items()
        if mid in state.locked_match_ids and existing.get(mid) != winner_id
    ]


def _locked_with_downstream(matches, num_rounds: int) -> set:
    """
    Matches in play, plus everything DOWNSTREAM of them.

    A match starting does not only settle itself — it leaks into every match its
    winner could still reach. Watching the top seed go down 0-6, 0-5 tells you
    plenty about who wins the quarter-final, so leaving that quarter-final
    editable hands an advantage to whoever happens to be watching. The whole path
    from a started match to the final therefore locks with it.

    Byes seed nothing. A bye carries a winner from the moment the draw is
    released, so propagating from it would lock most of the bracket before a ball
    was struck — the bye's own row is locked (there is nothing to predict) but it
    starts no chain.

    The parent of match n in round r is match (n+1)//2 in round r+1, which is the
    same relation the bracket views use to resolve feeders.
    """
    locked_keys = set()
    for m in matches:
        if m.is_bye or not match_in_play(m):
            continue
        r, n = m.round_number, m.match_number
        while r <= num_rounds:
            locked_keys.add((r, n))
            r, n = r + 1, (n + 1) // 2

    return {
        m.id for m in matches
        if (m.round_number, m.match_number) in locked_keys or m.is_bye or match_in_play(m)
    }


def _r1_complete(matches) -> bool:
    """Every first-round contest decided.

    Byes are excluded — they carry a winner from the moment the draw is
    released, so counting them would call the round complete before a ball was
    struck in a draw that has any. An empty first round is NOT complete: no
    matches means the draw is not out, and treating that as finished would lock
    every unreleased draw and reveal every unreleased bracket.
    """
    r1 = [m for m in matches if m.round_number == 1 and not m.is_bye]
    return bool(r1) and all(m.winner_id is not None for m in r1)


async def predictions_visible(db, draw) -> bool:
    """
    Whether one user may see ANOTHER user's picks for this draw.

    Held back until the first round is complete, in both modes. Under
    progressive locking it is the difference between a game and a copying
    exercise: picks stay editable through round 1, so a visible bracket is a
    bracket to crib from. Under the original mode nothing can change after the
    first ball, so this is only a fairness nicety — but the rule is the same in
    both, because "when can I see everyone else's picks" should not have a
    different answer per draw.

    A completed draw is always visible: the round-complete emails, standings and
    draw history all report on brackets after the fact, and a finished
    tournament has nothing left to protect.
    """
    if draw.status == "completed":
        return True
    matches = (await db.execute(
        select(Match.round_number, Match.is_bye, Match.winner_id)
        .where(Match.draw_id == draw.id)
    )).all()
    return _r1_complete([
        type("M", (), {"round_number": r, "is_bye": b, "winner_id": w})()
        for r, b, w in matches
    ])
