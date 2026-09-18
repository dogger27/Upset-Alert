"""THE TIEBREAK IS THE FINAL (owner, 2026-09-18).

Level on points, two brackets are separated by their answers to the two
questions asked on entering the draw: how many aces the champion would hit
in the final, and how long it would last. Closest on aces wins the tie;
still level, closest on minutes; still level, they share the place. A
bracket that never answered sits below every answered bracket it is level
with. Before the final is played nobody can be separated, and the standings
say so by sharing the place — the round-by-round weighting this replaces is
gone from every surface (scoring.tiebreak_key, finish_range, the app and
the site's own sorts).

The actuals are written to the draw by the results sweep once the final
finishes (sofascore_results.capture_final_stats); the guesses live in
draw_final_guesses.
"""
from typing import Optional

from sqlalchemy import select


def diffs_for(guess: Optional[tuple], actual_aces: Optional[int],
              actual_minutes: Optional[int]) -> tuple[Optional[int], Optional[int]]:
    """(|aces guess - actual|, |minutes guess - actual|), None where either side is missing."""
    if not guess:
        return None, None
    g_aces, g_min = guess
    a = abs(int(g_aces) - int(actual_aces)) if (g_aces is not None and actual_aces is not None) else None
    m = abs(int(g_min) - int(actual_minutes)) if (g_min is not None and actual_minutes is not None) else None
    return a, m


async def guesses_for(db, draw_id: int) -> dict[int, tuple[int, int]]:
    from app.models.final_guess import DrawFinalGuess
    rows = (await db.execute(select(DrawFinalGuess).where(DrawFinalGuess.draw_id == draw_id))).scalars().all()
    return {g.user_id: (g.final_aces, g.final_duration_min) for g in rows}


def final_played(draw) -> bool:
    return getattr(draw, "final_winner_aces", None) is not None or getattr(draw, "final_duration_min", None) is not None


def apply(scores, draw, guesses: dict) -> None:
    """Stamp each UserScore's tie diffs from its guess and the draw's actuals.
    Nothing is stamped before the final is played: level stays level."""
    if not final_played(draw):
        return
    for s in (scores.values() if isinstance(scores, dict) else scores):
        a, m = diffs_for(guesses.get(s.user_id), draw.final_winner_aces, draw.final_duration_min)
        s.tie_aces_diff, s.tie_minutes_diff = a, m
