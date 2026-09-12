"""Per-set model and live (in-play) win probability.

Use the direct models (rank / elo) for pre-match odds. Use these only for
in-play updates from the current set score — the set model is slightly
less accurate than the direct fit for pre-match prediction."""
import math
from math import comb
from ._params import params

def set_win_prob(rank_x, rank_y, best_of=3) -> float:
    """P(X wins a single set) from ranks."""
    cap = params("rank")["rank_cap"]
    rx = min(rank_x, cap) if rank_x else cap
    ry = min(rank_y, cap) if rank_y else cap
    p = params("set")
    k = p["beta"] + p["beta_bo5"] * (best_of == 5)
    return 1.0 / (1.0 + math.exp(-k * math.log2(ry / rx)))

def set_prob_from_match_prob(p_match: float, best_of=3) -> float:
    """Invert BO3/BO5 combinatorics: per-set p that yields this match p (bisection)."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if match_from_set_prob(mid, best_of) < p_match: lo = mid
        else: hi = mid
    return (lo + hi) / 2

def match_from_set_prob(p_set: float, best_of=3) -> float:
    """P(win match) from a per-set probability, assuming independent sets."""
    return live_win_prob_from_set_prob(p_set, 0, 0, best_of)

def live_win_prob_from_set_prob(p_set: float, sets_x: int, sets_y: int, best_of=3) -> float:
    """P(X wins) given per-set prob and the current set count."""
    need_x = (best_of + 1) // 2 - sets_x
    need_y = (best_of + 1) // 2 - sets_y
    if need_x <= 0: return 1.0
    if need_y <= 0: return 0.0
    return sum(comb(need_x - 1 + k, k) * p_set ** need_x * (1 - p_set) ** k
               for k in range(need_y))

def live_win_prob(rank_x=None, rank_y=None, sets_x=0, sets_y=0, best_of=3,
                  p_match=None) -> float:
    """In-play P(X wins). Pass ranks, or pass p_match (e.g. from the Elo model)
    and it will be inverted to a per-set probability first."""
    if p_match is not None:
        p_set = set_prob_from_match_prob(p_match, best_of)
    else:
        p_set = set_win_prob(rank_x, rank_y, best_of)
    return live_win_prob_from_set_prob(p_set, sets_x, sets_y, best_of)
