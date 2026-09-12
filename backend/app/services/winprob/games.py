"""In-play win probability from the GAME score, not just the set score.

`sets.live_win_prob` knows that a player is a set down. It does not know that
the player is also 5-2 up in the second, which is most of what a person
watching the match knows. This module adds that: the set in progress is
walked game by game as a Markov chain, and the result is folded into the
same best-of-N arithmetic the set model uses.

The chain of models, each derived from the one before it by inversion so
that a match at 0-0, 0-0 comes back to exactly the pre-match number:

    p_match  (pre-match, from Elo/rank)
      -> p_set   the per-set probability whose best-of-N gives p_match
      -> p_game  the per-game probability whose set from 0-0 gives p_set

A set is won at six games with two clear, or seven, or a tiebreak at 6-6.
The tiebreak is treated as one contest at the SET probability: it is more
skill-sensitive than a single game (many points) and less than a set, and
p_set is the honest middle of that range without a per-point model.

WHAT IS LEFT OUT, deliberately:

* Who is serving. Service games are won far more often than return games, so
  4-3 with the leader to serve is not 4-3 with the leader receiving. Folding
  that in needs hold/break probabilities per player, which the Elo model does
  not carry. The game-level chain uses one p_game for every game, which is
  right on average over a set and a little wrong at any one moment.
* The point score inside the game. It is the most perishable fact on the
  page — 40-30 is gone in twenty seconds — and the standings column is not
  a live scoreboard.

Every function is pure and cheap (a 7×7 grid), and memoised per p_game.
"""
from functools import lru_cache

from .sets import live_win_prob_from_set_prob, set_prob_from_match_prob


def _bisect(f, target: float, lo: float = 0.0, hi: float = 1.0, steps: int = 60) -> float:
    """The x in [lo, hi] at which the increasing function f reaches target."""
    for _ in range(steps):
        mid = (lo + hi) / 2
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


@lru_cache(maxsize=4096)
def set_win_prob_from_games(p_game: float, games_x: int, games_y: int, p_tiebreak: float) -> float:
    """P(X wins the set) from a game score, with p_game per game.

    Terminal states first, so a finished set reads 1 or 0 whatever the
    counts; 6-6 is the tiebreak; everything else is one more game either way.
    """
    if games_x >= 6 and games_x - games_y >= 2:
        return 1.0
    if games_y >= 6 and games_y - games_x >= 2:
        return 0.0
    if games_x >= 7:
        return 1.0
    if games_y >= 7:
        return 0.0
    if games_x == 6 and games_y == 6:
        return p_tiebreak
    return (p_game * set_win_prob_from_games(p_game, games_x + 1, games_y, p_tiebreak)
            + (1.0 - p_game) * set_win_prob_from_games(p_game, games_x, games_y + 1, p_tiebreak))


@lru_cache(maxsize=1024)
def game_prob_from_set_prob(p_set: float) -> float:
    """The per-game probability whose set from 0-0 (tiebreak at p_set) is p_set."""
    return _bisect(lambda g: set_win_prob_from_games(g, 0, 0, p_set), p_set)


def live_win_prob_games(p_match: float, sets_x: int, sets_y: int,
                        games_x: int = 0, games_y: int = 0, in_tiebreak: bool = False,
                        best_of: int = 3) -> float:
    """P(X wins the match) from the full scoreboard.

    `sets_x`/`sets_y` are COMPLETED sets; `games_x`/`games_y` the set in
    progress (0-0 when none is, which reduces exactly to the set model).
    `in_tiebreak` says the current set is at 6-6 with the tiebreak under way;
    game counts are then ignored, since the tiebreak is the contest.
    """
    need = (best_of + 1) // 2
    if sets_x >= need:
        return 1.0
    if sets_y >= need:
        return 0.0
    p_set = set_prob_from_match_prob(p_match, best_of)
    if in_tiebreak:
        p_this = p_set
    else:
        p_game = game_prob_from_set_prob(p_set)
        p_this = set_win_prob_from_games(p_game, games_x, games_y, p_set)
    return (p_this * live_win_prob_from_set_prob(p_set, sets_x + 1, sets_y, best_of)
            + (1.0 - p_this) * live_win_prob_from_set_prob(p_set, sets_x, sets_y + 1, best_of))
