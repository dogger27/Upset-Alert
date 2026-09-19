"""THE TIEBREAK IS THE FINAL (owner, 2026-09-18, third question 2026-09-19).

Level on points, two brackets are separated by their answers to the three
questions asked on entering the draw: how many SETS the final will go, how
many aces the champion will hit, and how long it will last. Closest on sets
wins the tie; still level, closest on aces; still level, closest on minutes;
still level, they share the place. A
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


def _gap(guess, actual) -> Optional[int]:
    if guess is None or actual is None:
        return None
    return abs(int(guess) - int(actual))


def diffs_for(guess: Optional[tuple], actual_aces: Optional[int],
              actual_minutes: Optional[int],
              actual_sets: Optional[int] = None) -> tuple:
    """(|sets off|, |aces off|, |minutes off|), None wherever either side is
    missing — a guess made before the sets question existed has no sets answer,
    and it must not be read as a perfect one."""
    if not guess:
        return None, None, None
    g_sets, g_aces, g_min = guess
    return (_gap(g_sets, actual_sets), _gap(g_aces, actual_aces), _gap(g_min, actual_minutes))


async def guesses_for(db, draw_id: int) -> dict[int, tuple]:
    """{user_id: (sets, aces, minutes)} — sets is None for a guess stored
    before that question was asked."""
    from app.models.final_guess import DrawFinalGuess
    rows = (await db.execute(select(DrawFinalGuess).where(DrawFinalGuess.draw_id == draw_id))).scalars().all()
    return {g.user_id: (g.final_sets, g.final_aces, g.final_duration_min) for g in rows}


_DEFAULTS: dict = {}


async def default_for(draw) -> Optional[tuple]:
    """(sets, aces, minutes) a bracket that never answered is taken to have
    said — last year's average for this gender, surface and format. Cached per
    (tour, surface, format) for the process: it is a settled figure."""
    from app.services.history import db as hdb
    from app.services.history.final_stats import default_guess
    from app.services.history.link import norm_surface
    from app.services.schedule import _best_of

    tour = "wta" if (getattr(draw, "gender", "") or "").upper() == "F" else "atp"
    surface = norm_surface(getattr(draw, "surface", None))
    best_of = _best_of(draw, "singles", "main")
    key = (tour, surface, best_of)
    if key not in _DEFAULTS:
        try:
            got = await hdb.run(lambda c: default_guess(c, tour, surface, best_of))
        except Exception:      # noqa: BLE001 — a missing default must not break a page
            got = None
        _DEFAULTS[key] = (got.get("sets"), got["aces"], got["minutes"]) if got else None
    return _DEFAULTS[key]


def final_played(draw) -> bool:
    return any(getattr(draw, f, None) is not None
               for f in ("final_winner_aces", "final_duration_min", "final_sets"))


def apply(scores, draw, guesses: dict, default: Optional[tuple] = None) -> None:
    """Stamp each UserScore's tie diffs from its guess and the draw's actuals.

    A BRACKET THAT NEVER ANSWERED IS TAKEN TO HAVE SAID THE DEFAULT (owner,
    2026-09-18): last year's average for this gender, surface and format. So
    everyone is separable, and a reader who never opened the dialog is not
    punished for it — they simply held the average. Nothing is stamped before
    the final is played: level stays level.
    """
    if not final_played(draw):
        return
    for s in (scores.values() if isinstance(scores, dict) else scores):
        st, a, m = diffs_for(guesses.get(s.user_id) or default,
                             draw.final_winner_aces, draw.final_duration_min,
                             getattr(draw, "final_sets", None))
        s.tie_sets_diff, s.tie_aces_diff, s.tie_minutes_diff = st, a, m
