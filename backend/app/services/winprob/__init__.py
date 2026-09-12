"""Tennis match win-probability models — vendored, pure Python, no deps.

Started as a package the owner supplied (fitted on Jeff Sackmann's `tennis_atp`,
tour-level main draw, 2000–2024, by hand outside this repo; `scripts/` is that
refit tooling and needs pandas/scikit-learn plus the CSVs, so it is provenance
rather than runtime). It has since been refitted on THIS APP'S OWN RESULTS and
extended; every coefficient lives in `models.json` — refit, never hand-edit:

    scripts/fit_winprob.py          the "blend" section, leak-free, with error bars
    scripts/winprob_calibration.py  the quick (and flattering) sanity check

    from app.services.winprob import predict, live_win_prob_games
    predict(selo_x=2027, selo_y=2073, elo_x=2093, elo_y=2147, rank_x=2, rank_y=3, best_of=5)
    live_win_prob_games(p_match=0.46, sets_x=0, sets_y=1, games_x=5, games_y=2, best_of=5)

WHAT `predict` DOES, in order of preference, and always antisymmetrically:

  1. "surface" — both players have Tennis Abstract's Elo for the match
     surface (hElo/cElo/gElo): logit = k_elo_surface·Δelo + k_rank·Δlog2(rank).
     The surface figure is, in Tennis Abstract's own words, the more accurate
     forecast, and on our matches it is worth ~0.03 of log loss over the
     overall rating — three times anything a recalibration buys.
  2. "elo" — both have an overall Elo: the same blend with the overall slope.
  3. "rank" — the original rank-only logistic model, untouched.

A pair is answered entirely in the best scale BOTH players share, so a
missing figure on one side never mixes two scales. That makes the model
mildly intransitive, which costs nothing here — a bracket only ever needs one
match's probability at a time, never a global ordering.

The ranking term is real (its 90% bootstrap interval excludes zero) and it is
also a confession: it is there because our weekly Elo snapshot can be a week
stale, and the ranking moves on Monday morning.

The upstream package also carried a Tennis Abstract HTML scraper. It is NOT
vendored: Elo already arrives in our own database weekly
(`te_rankings_snapshots`, see `services/rankings.refresh_elo_ratings`), and a
second scraper of the same page would be a second thing to keep alive.

Tennis Abstract's Elo ratings are CC BY-NC-SA 4.0: non-commercial, attribution
required. The standings' Chances column and the H2H Elo note both credit it.
"""
from .rank import rank_win_prob
from .sets import set_win_prob, match_from_set_prob, live_win_prob
from .elo import elo_win_prob, blend_win_prob
from .games import live_win_prob_games
from .predict import predict
from .points import upset_points

__all__ = ["predict", "rank_win_prob", "set_win_prob", "match_from_set_prob",
           "live_win_prob", "live_win_prob_games", "elo_win_prob", "blend_win_prob",
           "upset_points"]
