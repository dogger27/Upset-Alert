"""
Scoring engine — Classic Mode.

Points are awarded per correct pick, scaled by tournament tier and round:

              R128/96  R64/56/48  R32  R16  QF   SF   F
  ATP/WTA 250    —        1       1    2    3    4    6
  ATP/WTA 500    —        1       1    2    4    8   12
  ATP/WTA 1000   1        1       2    4    8   12   16
  Grand Slam     1        2       4    8   12   16   20

Tiebreaker order (when total points are equal):
  1. Most correct picks in the Final
  2. Most correct picks in the Semifinals
  3. Most correct picks in the Quarterfinals
  … and so on back through the earliest round
"""

from dataclasses import dataclass, field
from typing import Optional

from app.models.league import League
from app.models.prediction import UserPrediction
from app.models.tournament import DrawEntry, Match, Draw


# ---------------------------------------------------------------------------
# Classic Mode points table
# ---------------------------------------------------------------------------

# Keyed by rounds-from-final: 0=Final, 1=SF, 2=QF, 3=R16, 4=R32, 5=R64, 6=R128
_CLASSIC_BY_TIER: dict[str, dict[int, int]] = {
    "250":  {0: 6,  1: 4,  2: 3,  3: 2,  4: 1,  5: 1},
    "500":  {0: 12, 1: 8,  2: 4,  3: 2,  4: 1,  5: 1},
    "1000": {0: 16, 1: 12, 2: 8,  3: 4,  4: 2,  5: 1,  6: 1},
    "GS":   {0: 20, 1: 16, 2: 12, 3: 8,  4: 4,  5: 2,  6: 1},
}


def _tier(tournament: Draw) -> str:
    cat = (tournament.category or "").upper()
    if "SLAM" in cat or "GRAND" in cat:
        return "GS"
    if "1000" in cat:
        return "1000"
    if "500" in cat:
        return "500"
    return "250"


def _points_table(tournament: Draw) -> dict[int, int]:
    """Map round_number → points for Classic Mode."""
    by_rff = _CLASSIC_BY_TIER[_tier(tournament)]
    n = tournament.num_rounds
    return {r: by_rff.get(n - r, 0) for r in range(1, n + 1)}


# ---------------------------------------------------------------------------
# Per-user score computation
# ---------------------------------------------------------------------------

@dataclass
class UserScore:
    user_id: int
    total_points: float
    correct_count: int
    # correct picks per round_number; used for tiebreaking
    correct_by_round: dict[int, int] = field(default_factory=dict)

    def tiebreak_key(self, num_rounds: int) -> tuple:
        """Lower value = better rank. Compares round-by-round from Final backwards."""
        return (
            -self.total_points,
            *(-self.correct_by_round.get(r, 0) for r in range(num_rounds, 0, -1)),
        )


def score_user(
    user_id: int,
    predictions: list[UserPrediction],
    completed_matches: list[Match],
    tournament: Draw,
    league: League,
) -> UserScore:
    pts_table = _points_table(tournament)
    pred_by_match: dict[int, Optional[int]] = {
        p.match_id: p.predicted_winner_id for p in predictions
    }

    total_points = 0.0
    correct_count = 0
    correct_by_round: dict[int, int] = {}

    for match in completed_matches:
        if match.winner_id is None:
            continue
        if pred_by_match.get(match.id) != match.winner_id:
            continue

        total_points += pts_table.get(match.round_number, 0)
        correct_count += 1
        correct_by_round[match.round_number] = correct_by_round.get(match.round_number, 0) + 1

    return UserScore(
        user_id=user_id,
        total_points=total_points,
        correct_count=correct_count,
        correct_by_round=correct_by_round,
    )


def rank_users(scores: list[UserScore], num_rounds: int) -> list[UserScore]:
    """Return scores sorted by tiebreaker order."""
    return sorted(scores, key=lambda s: s.tiebreak_key(num_rounds))
