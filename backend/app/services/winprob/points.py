import math

def upset_points(p_win: float, base=1.0, cap=8.0) -> float:
    """Pick'em value of a correct pick with pre-match win probability p_win.
    -log2(p): a coin flip is worth 1.0, a 25% underdog 2.0, 12.5% 3.0."""
    p = min(max(p_win, 1e-9), 1.0)
    return min(base * -math.log2(p), cap)
