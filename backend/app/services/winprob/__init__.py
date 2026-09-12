"""Tennis match win-probability models — vendored, pure Python, no deps.

Fitted by hand on Jeff Sackmann's `tennis_atp` (tour-level main draw,
2000–2024) outside this repo; `scripts/` is the refit tooling and needs
pandas/scikit-learn and a local copy of the CSVs, so it is provenance rather
than runtime. Every coefficient lives in `models.json` — refit, never hand-edit.

    from app.services.winprob import predict
    predict(elo_x=2010, elo_y=1880, best_of=5)      # {"p": .., "model": "elo"}
    predict(rank_x=12, rank_y=40, surface="Clay")   # {"p": .., "model": "rank"}

`predict` is ANTISYMMETRIC — p(x,y) + p(y,x) == 1 — and prefers Elo when both
players have a rating, ranks otherwise. That per-pair fallback is deliberate:
Elo and rank are different scales, so a pair with one rating missing is
answered entirely in the scale both players do share. It makes the model
mildly intransitive, which costs nothing here — a bracket only ever needs one
match's probability at a time, never a global ordering.

The upstream package also carried a Tennis Abstract HTML scraper. It is NOT
vendored: Elo already arrives in our own database weekly
(`te_rankings_snapshots.elo`, see `services/rankings.refresh_elo_ratings`),
and a second scraper of the same page would be a second thing to keep alive.

Tennis Abstract's Elo ratings are CC BY-NC-SA 4.0: non-commercial, attribution
required. The standings' Chances column and the H2H Elo note both credit it.
"""
from .rank import rank_win_prob
from .sets import set_win_prob, match_from_set_prob, live_win_prob
from .elo import elo_win_prob
from .predict import predict
from .points import upset_points

__all__ = ["predict", "rank_win_prob", "set_win_prob", "match_from_set_prob",
           "live_win_prob", "elo_win_prob", "upset_points"]
