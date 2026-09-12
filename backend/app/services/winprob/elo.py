"""P(X beats Y) from Elo ratings.

Two curves live here. `elo_win_prob` is textbook Elo (400-point scale, one
free steepness in models.json "elo"). `blend_win_prob` is what the standings
use: the Elo difference AND the official ranking, each with a slope fitted on
this app's own results (models.json "blend"; see scripts/fit_winprob.py).
Both invert to a per-set probability and re-expand for best-of-five.

Pass Tennis Abstract's surface-blended hElo / cElo / gElo for the match
surface where you have it and say so with `surface_elo=True`: the surface
figure is the better predictor by a wide margin, and it takes a steeper slope
than the overall rating — do not blend it with the overall Elo again, it
already is one.
"""
import math
from ._params import params
from .sets import set_prob_from_match_prob, match_from_set_prob


def _expand(p3: float, best_of: int) -> float:
    """A best-of-three probability, re-expressed for the match format."""
    if best_of == 5:
        return match_from_set_prob(set_prob_from_match_prob(p3, 3), 5)
    return p3


def elo_win_prob(elo_x: float, elo_y: float, best_of=3) -> float:
    scale = params("elo")["logit_scale"]
    z = scale * math.log(10) * (elo_x - elo_y) / 400.0
    return _expand(1.0 / (1.0 + math.exp(-z)), best_of)


def blend_win_prob(elo_x: float, elo_y: float, rank_x=None, rank_y=None,
                   best_of=3, surface_elo=False) -> float:
    """Elo plus the ranking: logit = k_elo·ln10·Δelo/400 + k_rank·log2(rank_y/rank_x).

    The rank term is only added when BOTH rankings are known — the fitted
    slope describes a real gap between two ranked players, not the gap to a
    cap. Antisymmetric either way.
    """
    b = params("blend")
    k_elo, k_rank = ((b["k_elo_surface"], b["k_rank_surface"]) if surface_elo
                     else (b["k_elo"], b["k_rank"]))
    z = k_elo * math.log(10) * (elo_x - elo_y) / 400.0
    if rank_x and rank_y:
        cap = params("rank")["rank_cap"]
        z += k_rank * math.log2(min(rank_y, cap) / min(rank_x, cap))
    return _expand(1.0 / (1.0 + math.exp(-z)), best_of)


def own_win_prob(own_x: tuple, own_y: tuple, rank_x=None, rank_y=None, best_of=3) -> float:
    """Our own Elo (services/history/ratings.py): each side is (overall,
    surface) and the prediction rating is the fitted mix of the two —
    surface_w on the surface figure, the rest on the overall — then the same
    logistic, ranking term and best-of-five expansion as the blend. Every
    constant is models.json "own", fitted by scripts/fit_own_elo.py.
    """
    o = params("own")
    w = float(o.get("surface_w", 0.5))
    rx = w * own_x[1] + (1.0 - w) * own_x[0]
    ry = w * own_y[1] + (1.0 - w) * own_y[0]
    z = float(o["k_logit"]) * math.log(10) * (rx - ry) / 400.0
    k_rank = float(o.get("k_rank", 0.0))
    if k_rank and rank_x and rank_y:
        cap = params("rank")["rank_cap"]
        z += k_rank * math.log2(min(rank_y, cap) / min(rank_x, cap))
    return _expand(1.0 / (1.0 + math.exp(-z)), best_of)
