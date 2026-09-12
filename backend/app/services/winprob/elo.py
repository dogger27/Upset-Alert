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
from typing import Optional

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


INITIAL_RATING = 1500.0


def own_params(tour: str = None) -> dict:
    """models.json "own", with the tour's own overrides applied.

    THE TWO TOURS NEED DIFFERENT NUMBERS, and not by a little. The men's
    record runs five times deeper — a median 260 matches behind each player
    in our 2026 draws against the women's 54, because the record carries ATP
    Challenger and qualifying and no WTA equivalent exists. So the women's
    fit leans much harder on the world ranking (k_rank 0.139 against 0.053)
    and wants its thin ratings shrunk, while shrinking the men's ratings
    only throws information away. Measured both ways; see the ledger in
    memory and scripts/fit_own_elo.py --shrink.

    Only the PREDICTION parameters vary by tour. The rating pass itself
    (k0, k_decay, welo) is one walk over both tours and cannot.
    """
    o = dict(params("own"))
    o.update((params("own").get("by_tour") or {}).get(tour or "", {}) or {})
    return o


def shrink_rating(rating: float, n_matches: Optional[int], n0: float) -> float:
    """A rating pulled toward the tour mean by how little is behind it.

    r <- 1500 + (r - 1500) * n / (n + n0). A player with n0 matches keeps
    half of their distance from the mean; one with none keeps nothing. This
    is James-Stein shrinkage, applied the way Gollub (2021) applies it to
    serve estimates: the rating of a player with twenty matches is a guess
    wearing a number's clothes, and the ranking term should carry them.
    """
    if not n0 or n_matches is None:
        return rating
    return INITIAL_RATING + (rating - INITIAL_RATING) * (n_matches / (n_matches + n0))


def layoff_factor(days_since: Optional[float], tau: float, grace: float) -> float:
    """How much of a rating survives time away from the tour.

    exp(-(days - grace)/tau), floored at a full-strength 1.0 inside the
    grace period — an off-season is not an injury. A rating is frozen at
    whatever it was when its owner last walked off court, and after eight
    months out that number is a claim about a different player.
    FiveThirtyEight's documented treatment; worth about 0.002 of log loss on
    the women's tour and nothing on the men's, which is the same story as
    the shrinkage: thin, volatile records benefit from being doubted.
    """
    if not tau or days_since is None:
        return 1.0
    return math.exp(-max(0.0, days_since - grace) / tau)


def own_win_prob(own_x: tuple, own_y: tuple, rank_x=None, rank_y=None, best_of=3,
                 tour: str = None) -> float:
    """Our own Elo (services/history/ratings.py). Each side is (overall,
    surface, matches played, days since last played) and the prediction rating is the fitted mix of
    the two figures — surface_w on the surface one, the rest on the overall
    — shrunk toward the mean by how thin it is, then the same logistic,
    ranking term and best-of-five expansion as the blend. Every constant is
    models.json "own" and its per-tour overrides, fitted by
    scripts/fit_own_elo.py.
    """
    o = own_params(tour)
    w = float(o.get("surface_w", 0.5))
    n0 = float(o.get("shrink_n0", 0.0))
    nx = own_x[2] if len(own_x) > 2 else None
    ny = own_y[2] if len(own_y) > 2 else None
    tau, grace = float(o.get("layoff_tau", 0.0)), float(o.get("layoff_grace", 60))
    gx = own_x[3] if len(own_x) > 3 else None
    gy = own_y[3] if len(own_y) > 3 else None
    rx = shrink_rating(w * own_x[1] + (1.0 - w) * own_x[0], nx, n0)
    ry = shrink_rating(w * own_y[1] + (1.0 - w) * own_y[0], ny, n0)
    fx, fy = layoff_factor(gx, tau, grace), layoff_factor(gy, tau, grace)
    rx = INITIAL_RATING + (rx - INITIAL_RATING) * fx
    ry = INITIAL_RATING + (ry - INITIAL_RATING) * fy
    z = float(o["k_logit"]) * math.log(10) * (rx - ry) / 400.0
    k_rank = float(o.get("k_rank", 0.0))
    if k_rank and rank_x and rank_y:
        cap = params("rank")["rank_cap"]
        z += k_rank * math.log2(min(rank_y, cap) / min(rank_x, cap))
    return _expand(1.0 / (1.0 + math.exp(-z)), best_of)
