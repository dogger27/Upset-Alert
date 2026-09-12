"""Single entry point. Surface Elo when both players have it, overall Elo
when both have that, the rank model otherwise — each with the ranking folded
in where the fitted model wants it."""
from .rank import rank_win_prob
from .elo import blend_win_prob


def predict(rank_x=None, rank_y=None, elo_x=None, elo_y=None,
            surface="Hard", best_of=3, selo_x=None, selo_y=None) -> dict:
    """Returns {"p": P(X wins), "model": "surface"|"elo"|"rank"}.

    `selo_x`/`selo_y` are the players' Elo for THIS match's surface (Tennis
    Abstract hElo/cElo/gElo); `elo_x`/`elo_y` their overall Elo. A pair is
    answered entirely in the best scale both players share, so a missing
    figure on one side never mixes two scales.
    """
    if selo_x is not None and selo_y is not None:
        return {"p": blend_win_prob(selo_x, selo_y, rank_x, rank_y, best_of, surface_elo=True),
                "model": "surface"}
    if elo_x is not None and elo_y is not None:
        return {"p": blend_win_prob(elo_x, elo_y, rank_x, rank_y, best_of), "model": "elo"}
    if rank_x is None and rank_y is None:
        raise ValueError("need ranks or Elo ratings for both players")
    return {"p": rank_win_prob(rank_x, rank_y, surface, best_of), "model": "rank"}
