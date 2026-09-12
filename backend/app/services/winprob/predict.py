"""Single entry point. Our own rating when both players have one and the
model has been fitted; else Tennis Abstract's surface Elo, then its overall
Elo, then the rank model — each with the ranking folded in where the fitted
model wants it."""
from ._params import params
from .rank import rank_win_prob
from .elo import blend_win_prob, own_win_prob


def predict(rank_x=None, rank_y=None, elo_x=None, elo_y=None,
            surface="Hard", best_of=3, selo_x=None, selo_y=None,
            own_x=None, own_y=None, tour=None) -> dict:
    """Returns {"p": P(X wins), "model": "own"|"surface"|"elo"|"rank"}.

    `own_x`/`own_y` are (overall, surface, matches played) from our own
    rating pass, and `tour` selects that tour's fitted parameters;
    `selo_x`/`selo_y` the players' Tennis Abstract Elo for THIS match's
    surface; `elo_x`/`elo_y` their overall Elo. A pair is answered entirely
    in the best scale both players share, so a missing figure on one side
    never mixes two scales.
    """
    if own_x is not None and own_y is not None and params("own").get("fitted"):
        return {"p": own_win_prob(own_x, own_y, rank_x, rank_y, best_of, tour), "model": "own"}
    if selo_x is not None and selo_y is not None:
        return {"p": blend_win_prob(selo_x, selo_y, rank_x, rank_y, best_of, surface_elo=True),
                "model": "surface"}
    if elo_x is not None and elo_y is not None:
        return {"p": blend_win_prob(elo_x, elo_y, rank_x, rank_y, best_of), "model": "elo"}
    if rank_x is None and rank_y is None:
        raise ValueError("need ranks or Elo ratings for both players")
    return {"p": rank_win_prob(rank_x, rank_y, surface, best_of), "model": "rank"}
