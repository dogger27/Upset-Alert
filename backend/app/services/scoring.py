"""
Scoring engine for all four league modes.

Scoring modes:
  classic      — points double each round: R1=1, R2=2, R3=4, R4=8, QF=16, SF=32, F=64/128
  atp_wta      — official ATP/WTA ranking points per round
  upset_bonus  — classic base + seed-difference bonus for correct upset picks
  custom       — owner-defined points per round number

Tiebreaker order (all computed here, applied in the API layer):
  1. Total score
  2. Most correct picks (correct_count)
  3. Correct champion pick
  4. Correct finalist pick(s)
"""

from dataclasses import dataclass, field
from typing import Optional

from app.models.league import League
from app.models.prediction import UserPrediction
from app.models.tournament import Match, Player, Tournament


# ---------------------------------------------------------------------------
# Points tables
# ---------------------------------------------------------------------------

def _classic_points(num_rounds: int) -> dict[int, int]:
    """round_number -> points, doubling from 1."""
    return {r: 2 ** (r - 1) for r in range(1, num_rounds + 1)}


# ATP/WTA Grand Slam points (round_number, draw_size=128)
_ATP_WTA_128 = {1: 10, 2: 45, 3: 90, 4: 180, 5: 360, 6: 720, 7: 2000}
_ATP_WTA_64  = {1: 10, 2: 45, 3: 90, 4: 180, 5: 360, 6: 720}
_ATP_WTA_32  = {1: 10, 2: 45, 3: 90, 4: 180, 5: 360}

_ATP_WTA_BY_SIZE: dict[int, dict[int, int]] = {
    128: _ATP_WTA_128,
    64:  _ATP_WTA_64,
    32:  _ATP_WTA_32,
}


def _points_table(league: League, tournament: Tournament) -> dict[int, int]:
    mode = league.scoring_mode
    if mode == "classic" or mode == "upset_bonus":
        return _classic_points(tournament.num_rounds)
    if mode == "atp_wta":
        return _ATP_WTA_BY_SIZE.get(tournament.draw_size, _classic_points(tournament.num_rounds))
    if mode == "custom":
        raw = league.custom_points or {}
        return {int(k): int(v) for k, v in raw.items()}
    return _classic_points(tournament.num_rounds)


def _upset_bonus(winner_seed: Optional[int], loser_seed: Optional[int]) -> int:
    """Bonus points for an upset. Returns 0 if no upset."""
    if winner_seed is None and loser_seed is not None:
        # Unseeded beats seeded — bonus = loser's seed value
        return loser_seed
    if winner_seed is not None and loser_seed is not None and winner_seed > loser_seed:
        return winner_seed - loser_seed
    return 0


# ---------------------------------------------------------------------------
# Per-user score computation
# ---------------------------------------------------------------------------

@dataclass
class UserScore:
    user_id: int
    total_points: float
    correct_count: int
    champion_correct: bool
    finalist_correct: bool

    # Tiebreaker key (lower = better rank)
    def tiebreak_key(self) -> tuple:
        return (
            -self.total_points,
            -self.correct_count,
            0 if self.champion_correct else 1,
            0 if self.finalist_correct else 1,
        )


def score_user(
    user_id: int,
    predictions: list[UserPrediction],  # all predictions for this user in this tournament
    completed_matches: list[Match],      # matches with winner_id set
    tournament: Tournament,
    league: League,
) -> UserScore:
    """
    Compute a single user's score within a league.
    predictions: list of UserPrediction objects for this user + this tournament.
    completed_matches: Match objects where status == "completed".
    """
    pts_table = _points_table(league, tournament)
    use_upset_bonus = (league.scoring_mode == "upset_bonus")

    # Index predictions by match_id for fast lookup
    pred_by_match: dict[int, Optional[int]] = {
        p.match_id: p.predicted_winner_id for p in predictions
    }

    total_points = 0.0
    correct_count = 0
    champion_correct = False
    finalist_correct = False

    final_round = tournament.num_rounds
    sf_round = final_round - 1

    for match in completed_matches:
        if match.winner_id is None:
            continue
        predicted_winner_id = pred_by_match.get(match.id)
        if predicted_winner_id is None:
            continue

        if predicted_winner_id == match.winner_id:
            base_pts = pts_table.get(match.round_number, 0)
            bonus = 0

            if use_upset_bonus:
                winner: Optional[Player] = match.winner
                loser_id = (
                    match.player2_id
                    if match.winner_id == match.player1_id
                    else match.player1_id
                )
                loser = match.player2 if match.winner_id == match.player1_id else match.player1
                bonus = _upset_bonus(
                    winner.seed if winner else None,
                    loser.seed if loser else None,
                )

            total_points += base_pts + bonus
            correct_count += 1

            if match.round_number == final_round:
                champion_correct = True
            if match.round_number == sf_round:
                finalist_correct = True

    return UserScore(
        user_id=user_id,
        total_points=total_points,
        correct_count=correct_count,
        champion_correct=champion_correct,
        finalist_correct=finalist_correct,
    )


def rank_users(scores: list[UserScore]) -> list[UserScore]:
    """Return scores sorted by tiebreaker order."""
    return sorted(scores, key=lambda s: s.tiebreak_key())
