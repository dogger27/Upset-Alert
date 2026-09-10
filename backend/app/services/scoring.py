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
from app.models.tournament import Match, Draw


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


def potential_points(
    pred_by_match: dict[int, Optional[int]],
    all_matches: list[Match],
    position_by_entry: dict[int, Optional[int]],
    pts_table: dict[int, int],
) -> float:
    """Points still on the table for these picks, in the best case.

    The best case is simple: every undecided match the pick can still be
    right about pays out. A pick can still be right when the player it names
    has not lost a match yet AND that player belongs in this match's half of
    the draw — which is a question of bracket position, not of the other
    picks. Line `pos` reaches round-r match number ceil(pos / 2^r), whatever
    was picked on the way; a pick that reaches the final from line 3 pays out
    even if the same bracket had someone else winning line 3's second round,
    because the final's pick is scored on its own.

    Undecided means no winner and not completed. A bye is never a contest.
    Add the user's current total for the "Max" the standings show.
    """
    eliminated: set[int] = set()
    for m in all_matches:
        if m.is_bye or m.winner_id is None:
            continue
        loser = m.player2_id if m.winner_id == m.player1_id else m.player1_id
        if loser is not None:
            eliminated.add(loser)

    out = 0.0
    for m in all_matches:
        if m.is_bye or m.winner_id is not None or m.status == "completed":
            continue
        pick = pred_by_match.get(m.id)
        if pick is None or pick in eliminated:
            continue
        pos = position_by_entry.get(pick)
        if pos is None:
            continue
        if -(-pos // (1 << m.round_number)) != m.match_number:
            continue
        out += pts_table.get(m.round_number, 0)
    return out


def rank_users(scores: list[UserScore], num_rounds: int) -> list[UserScore]:
    """Return scores sorted by tiebreaker order."""
    return sorted(scores, key=lambda s: s.tiebreak_key(num_rounds))


# ---------------------------------------------------------------------------
# Finish range — the best and worst place a bracket can still end on
# ---------------------------------------------------------------------------

# Every undecided match doubles the number of futures. 15 is "R32 complete" on
# any draw (8 R16 + 4 QF + 2 SF + F): 32,768 futures, a tenth of a second for
# thirty brackets. 16 is R32 with one match left; 31 is R32 not yet started,
# two billion futures and hours of CPU. The owner chose R16 as the line.
FINISH_RANGE_MAX_UNDECIDED = 15

# Per-round correct counts are packed into one integer key beneath the points,
# so a whole leaderboard ranks with vector compares. 128 > 64, the most matches
# any round has (R128).
_KEY_BASE = 128

# A pick that names nobody must never equal a match nobody wins.
_NO_PICK = -2
_NO_PLAYER = -1


def _undecided(all_matches: list) -> list:
    """Contests still open, in bracket order. A bye is never a contest."""
    return sorted((m for m in all_matches if not m.is_bye and m.winner_id is None),
                  key=lambda m: (m.round_number, m.match_number))


def finish_range_available(all_matches: list) -> bool:
    return len(_undecided(all_matches)) <= FINISH_RANGE_MAX_UNDECIDED


def finish_range(
    all_matches: list,
    pts_table: dict[int, int],
    num_rounds: int,
    banked: dict[int, UserScore],
    picks: dict[int, dict[int, Optional[int]]],
) -> Optional[dict[int, tuple[int, int]]]:
    """Best and worst finishing place for every bracket, over every future.

    Enumerates every combination of winners for the undecided matches, walking
    the bracket forward so a later match is contested by whoever this future
    advanced into it, scores every bracket in every future, and ranks them
    with the same tiebreak as rank_users. Returns {user_id: (best, worst)}:
    the best and worst PLACE the bracket holds over every future, where a
    place is one plus the brackets strictly ahead — competition ranking,
    exactly what the standings print, so two brackets level in third are
    both third and a tie never pushes the range past the podium.

    `banked` is each user's score on the decided matches (score_user); `picks`
    is each user's predicted winner by match id. None when the draw has more
    undecided matches than FINISH_RANGE_MAX_UNDECIDED, or nobody to rank.
    """
    if not banked:
        return None
    undecided = _undecided(all_matches)
    n = len(undecided)
    if n > FINISH_RANGE_MAX_UNDECIDED:
        return None

    import numpy as np

    users = sorted(banked)
    u_count = len(users)
    by_slot = {(m.round_number, m.match_number): m for m in all_matches}
    col_of = {m.id: i for i, m in enumerate(undecided)}

    # Each side of an undecided match is a fixed player, the winner of an
    # undecided feeder (a column of this future), or nobody.
    def _side(m, pid, feeder_no):
        if pid is not None:
            return ("const", pid)
        feeder = by_slot.get((m.round_number - 1, feeder_no))
        if feeder is None:
            return ("const", _NO_PLAYER)
        if feeder.id in col_of:
            return ("col", col_of[feeder.id])
        return ("const", feeder.winner_id if feeder.winner_id is not None else _NO_PLAYER)

    sides = [(_side(m, m.player1_id, 2 * m.match_number - 1),
              _side(m, m.player2_id, 2 * m.match_number)) for m in undecided]

    # Points and the tiebreak weight of a correct pick in each undecided match,
    # folded into one integer: points ride above every round count.
    pts_scale = _KEY_BASE ** num_rounds
    weight = np.array([pts_table.get(m.round_number, 0) * pts_scale
                       + _KEY_BASE ** (m.round_number - 1) for m in undecided], dtype=np.int64)
    base = np.array([
        int(round(banked[u].total_points)) * pts_scale
        + sum(banked[u].correct_by_round.get(r, 0) * _KEY_BASE ** (r - 1) for r in range(1, num_rounds + 1))
        for u in users], dtype=np.int64)
    pick_mat = np.full((u_count, n), _NO_PICK, dtype=np.int64)
    for ui, u in enumerate(users):
        mine = picks.get(u) or {}
        for ci, m in enumerate(undecided):
            p = mine.get(m.id)
            if p is not None:
                pick_mat[ui, ci] = p

    worlds = 1 << n
    # The rank step compares every bracket with every other, per future; keep
    # that cube to a few million cells whatever the user count.
    chunk = max(1, min(4096, 4_000_000 // max(1, u_count * u_count)))
    best = np.full(u_count, u_count + 1, dtype=np.int64)
    worst = np.zeros(u_count, dtype=np.int64)
    for start in range(0, worlds, chunk):
        idx = np.arange(start, min(start + chunk, worlds), dtype=np.int64)
        bits = (idx[:, None] >> np.arange(n, dtype=np.int64)) & 1 if n else np.zeros((len(idx), 0), dtype=np.int64)
        win = np.empty((len(idx), n), dtype=np.int64)
        for ci in range(n):
            s1, s2 = sides[ci]
            a = win[:, s1[1]] if s1[0] == "col" else np.full(len(idx), s1[1], dtype=np.int64)
            b = win[:, s2[1]] if s2[0] == "col" else np.full(len(idx), s2[1], dtype=np.int64)
            # A side nobody can fill loses by walkover, whatever the coin says.
            w = np.where(bits[:, ci] == 0, a, b)
            w = np.where(a == _NO_PLAYER, b, w)
            w = np.where(b == _NO_PLAYER, a, w)
            win[:, ci] = w
        correct = pick_mat[None, :, :] == win[:, None, :]            # worlds × users × matches
        key = base[None, :] + correct @ weight                       # worlds × users
        ahead = key[:, None, :] > key[:, :, None]                    # [w, me, other]
        place = 1 + ahead.sum(2)                                     # worlds × users
        best = np.minimum(best, place.min(0))
        worst = np.maximum(worst, place.max(0))
    return {u: (int(best[i]), int(worst[i])) for i, u in enumerate(users)}


# Same draw, same brackets, same results: same answer. Keyed on everything the
# range depends on, so a pick edited by an admin or a result reverted is a
# miss, not a stale hit.
_FINISH_CACHE: dict[tuple, Optional[dict[int, tuple[int, int]]]] = {}
_FINISH_CACHE_MAX = 64


def finish_range_cached(draw_id: int, all_matches: list, pts_table: dict[int, int], num_rounds: int,
                        banked: dict[int, UserScore], picks: dict[int, dict[int, Optional[int]]]):
    key = (
        draw_id, num_rounds,
        tuple(sorted((m.id, m.winner_id, bool(m.is_bye), m.player1_id, m.player2_id) for m in all_matches)),
        tuple(sorted((u, tuple(sorted((k, v) for k, v in (picks.get(u) or {}).items() if v is not None)))
                     for u in banked)),
    )
    if key in _FINISH_CACHE:
        return _FINISH_CACHE[key]
    out = finish_range(all_matches, pts_table, num_rounds, banked, picks)
    if len(_FINISH_CACHE) >= _FINISH_CACHE_MAX:
        _FINISH_CACHE.pop(next(iter(_FINISH_CACHE)))
    _FINISH_CACHE[key] = out
    return out


async def finish_range_async(draw_id: int, all_matches: list, pts_table: dict[int, int], num_rounds: int,
                             banked: dict[int, UserScore], picks: dict[int, dict[int, Optional[int]]]):
    """finish_range_cached off the event loop. The matches are copied to plain
    records first, so no ORM object is touched from the worker thread."""
    import asyncio
    from types import SimpleNamespace
    plain = [SimpleNamespace(id=m.id, round_number=m.round_number, match_number=m.match_number,
                             player1_id=m.player1_id, player2_id=m.player2_id,
                             winner_id=m.winner_id, is_bye=bool(m.is_bye)) for m in all_matches]
    return await asyncio.to_thread(finish_range_cached, draw_id, plain, pts_table, num_rounds, banked, picks)


# A podium is locked when the worst place a bracket can hold is third or
# better. Places are competition-ranked, so two brackets level in third both
# take the bronze.
PODIUM_PLACES = 3


def podium_locked(rng: Optional[tuple]) -> Optional[bool]:
    return None if rng is None else rng[1] <= PODIUM_PLACES
