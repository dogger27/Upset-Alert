"""P(X beats Y) from ATP ranks. Logistic on log2 rank ratio; antisymmetric."""
import math
from ._params import params, norm_surface

def _rank_logit_slope(surface: str, best_of: int) -> float:
    p = params("rank")
    return (p["beta"] + p["beta_bo5"] * (best_of == 5)
            + p["beta_clay"] * (surface == "Clay") + p["beta_grass"] * (surface == "Grass"))

def rank_win_prob(rank_x, rank_y, surface="Hard", best_of=3) -> float:
    """Probability that the player ranked rank_x beats the player ranked rank_y.
    Unranked / None / 0 ranks are capped at models.json rank_cap."""
    cap = params("rank")["rank_cap"]
    rx = min(rank_x, cap) if rank_x else cap
    ry = min(rank_y, cap) if rank_y else cap
    s = math.log2(ry / rx)
    k = _rank_logit_slope(norm_surface(surface), best_of)
    return 1.0 / (1.0 + math.exp(-k * s))
