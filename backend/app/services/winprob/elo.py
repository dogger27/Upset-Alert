"""P(X beats Y) from Elo ratings. Pass Tennis Abstract's surface-blended
hElo / cElo / gElo for the match surface — they are already a 50/50 blend of
overall and surface-only ratings, so do not blend again."""
import math
from ._params import params
from .sets import set_prob_from_match_prob, match_from_set_prob

def elo_win_prob(elo_x: float, elo_y: float, best_of=3) -> float:
    scale = params("elo")["logit_scale"]
    z = scale * math.log(10) * (elo_x - elo_y) / 400.0
    p3 = 1.0 / (1.0 + math.exp(-z))                # best-of-3 probability
    if best_of == 5:
        return match_from_set_prob(set_prob_from_match_prob(p3, 3), 5)
    return p3
