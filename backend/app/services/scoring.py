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

# ── THE CHANCES GO BACK FURTHER THAN THE RANGE, BY SAMPLING ─────────────────
# The two columns are different kinds of quantity and that is what decides
# how each may be computed.
#
#   The Finish RANGE is an EXTREME — the best and worst place over EVERY
#   future. A sample can only ever miss the most extreme one, so it would
#   report a range narrower than the truth and quietly claim a place was safe
#   when it is not. It stays exact, and therefore stays gated at 15.
#
#   Win and Top 3 are EXPECTATIONS. A sample estimates those honestly, with
#   an error of sqrt(p(1-p)/N): at 100,000 draws that is 0.16 points at worst
#   and 0.05 at a tenth, which a column printing whole percentages cannot
#   show. So they are drawn instead of enumerated as soon as enumeration
#   becomes impossible, and the reader gets them from the first round rather
#   than the last weekend.
#
# And the early rounds are where the range is useless anyway: with 63 matches
# left everyone can still finish first and last, so "1-19" tells nobody
# anything while "12%" tells them plenty.
CHANCES_SAMPLES = 100_000
# THE SCRUB PAYS FOR ITS OWN RESPONSIVENESS. The live figure is computed once
# per state and sits there being read, so it takes the full sample. A rewound
# position is computed while someone's finger is on the slider, and the wait
# is the whole experience of the feature: 40,000 draws is three times faster
# (0.48s at the deepest position, 0.12s at R32) and its worst disagreement
# with the full sample, measured over a real 19-bracket league at three
# depths, was 0.4 of a percentage point — at most a single row rounding the
# other way. 10,000 was tried and rejected: 1.4 points on Top 3.
CHANCES_SCRUB_SAMPLES = 40_000
# Fixed, so the same draw in the same state always produces the same number.
# A column that moved while nothing had happened would read as broken, which
# is the whole reason the exact path was built first.
CHANCES_SEED = 20260912
# 127 is a full 128 draw with nothing played. The cost is samples x matches,
# not 2^matches, so the ceiling is about arithmetic time rather than
# combinatorics — measured at well under a second for the worst case.
CHANCES_MAX_UNDECIDED = 127

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


def chances_available(all_matches: list) -> bool:
    """Win and Top 3 can be had — exactly, or by sampling."""
    return len(_undecided(all_matches)) <= CHANCES_MAX_UNDECIDED


def chances_sampled(all_matches: list) -> bool:
    """...and whether this draw is past the point where they are exact."""
    n = len(_undecided(all_matches))
    return FINISH_RANGE_MAX_UNDECIDED < n <= CHANCES_MAX_UNDECIDED


def finish_range(
    all_matches: list,
    pts_table: dict[int, int],
    num_rounds: int,
    banked: dict[int, UserScore],
    picks: dict[int, dict[int, Optional[int]]],
    odds=None,
    sample: bool = False,
    samples: Optional[int] = None,
) -> Optional[dict[int, tuple]]:
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

    WITH `sample` the futures are DRAWN instead of enumerated —
    CHANCES_SAMPLES of them, from a fixed seed, each already distributed by
    the odds so every draw carries the same weight. That lifts the 15-match
    ceiling (the cost becomes samples x matches rather than 2^matches) and is
    the only way the chances can exist in the first week of a draw. The range
    then comes back as (None, None, p_win, p_podium): best and worst are
    EXTREMES over every future, a sample can only miss the most extreme one,
    and a range narrower than the truth would claim a place is safe when it
    is not. `sample` requires `odds`; without them there is nothing to draw
    from and the call returns None.

    WITH `odds` every future is also WEIGHTED, and the answer becomes
    (best, worst, p_win, p_podium) — the chance the bracket finishes first and
    the chance it finishes in the top three. The futures are already being
    walked; the weight is the product of one probability per match, asked of
    the odds source for the two players that future put in it. So the two
    probabilities cost almost nothing beyond the range, and they are exact:
    no sampling, no number that changes on a refresh while nothing has
    happened. `odds` needs two methods — `pair_prob(a, b)` and
    `live_override(match_id)` — and knows nothing about brackets; see
    `services/win_chances.DrawOdds`.
    """
    if not banked:
        return None
    undecided = _undecided(all_matches)
    n = len(undecided)
    if sample and odds is None:
        return None                      # nothing to draw the futures from
    if n > (CHANCES_MAX_UNDECIDED if sample else FINISH_RANGE_MAX_UNDECIDED):
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

    # ── The weight of a future, when there is an odds source to ask ──────────
    # EVERY PLAYER A SIDE CAN RESOLVE TO is a `const` somewhere in `sides`: a
    # `col` side is another undecided match's winner, and that match's own
    # sides are in the same list. Sixteen of them at fifteen matches, so the
    # whole pairwise table is a couple of hundred cells — built once here and
    # indexed per future, rather than one model call per future per match.
    pair_p = live_over = lookup = None
    any_empty_side = any(pid == _NO_PLAYER for pair in sides for kind, pid in pair if kind == "const")
    if odds is not None:
        cand_ids = sorted({pid for pair in sides for kind, pid in pair if kind == "const"})
        at = {pid: i for i, pid in enumerate(cand_ids)}
        # A DENSE LOOKUP, NOT A BINARY SEARCH. Two searchsorted calls per
        # match per chunk was the single biggest cost in the walk — 127
        # matches over a full draw, and each call is O(samples log players).
        # Player ids are small integers, so one array indexed by id answers
        # it in one step. Offset by one so the empty-slot sentinel (-1) has
        # somewhere to live.
        # max() of nothing: a fully decided draw has no undecided match and so
        # no candidates, and the loop below never runs anyway.
        lookup = np.zeros((max(cand_ids) if cand_ids else 0) + 2, dtype=np.int64)
        for i, pid in enumerate(cand_ids):
            lookup[pid + 1] = i
        pair_p = np.full((max(1, len(cand_ids)), max(1, len(cand_ids))), 0.5)
        # HALF THE PAIRS: the model is antisymmetric, so p(y beats x) is one
        # minus p(x beats y) and asking for both doubles the work for nothing.
        for i, x in enumerate(cand_ids):
            for j in range(i + 1, len(cand_ids)):
                y = cand_ids[j]
                if x == _NO_PLAYER:
                    q = 0.0                       # an empty slot loses by walkover
                elif y == _NO_PLAYER:
                    q = 1.0
                else:
                    q = odds.pair_prob(x, y)
                pair_p[i, j], pair_p[j, i] = q, 1.0 - q
        # A MATCH IN PROGRESS is not at its pre-match odds any more. Only the
        # pair actually on court is overridden: the same two players meeting in
        # a later round of some other future are back to level terms.
        live_over = {}
        for ci, m in enumerate(undecided):
            ov = odds.live_override(m.id)
            if ov and ov[0] in at and ov[1] in at:
                live_over[ci] = (at[ov[0]], at[ov[1]], ov[2])

    worlds = (samples or CHANCES_SAMPLES) if sample else 1 << n
    # The rank step compares every bracket with every other, per future; keep
    # that cube to a few million cells whatever the user count.
    chunk = (max(1, min(20_000, 2_000_000 // max(1, u_count)))
             if sample else max(1, min(4096, 4_000_000 // max(1, u_count * u_count))))
    best = np.full(u_count, u_count + 1, dtype=np.int64)
    worst = np.zeros(u_count, dtype=np.int64)
    p_win = np.zeros(u_count)
    p_pod = np.zeros(u_count)
    p_total = 0.0
    rng = np.random.default_rng(CHANCES_SEED) if sample else None
    for start in range(0, worlds, chunk):
        size = min(chunk, worlds - start)
        if sample:
            # ONE UNIFORM PER MATCH PER SAMPLE, compared against that match's
            # probability. The future is therefore drawn FROM the distribution,
            # so every sample weighs the same and the weighting that the exact
            # path does by multiplication is done here by the draw itself.
            bits = None
            coin = rng.random((size, n))
        else:
            idx = np.arange(start, start + size, dtype=np.int64)
            bits = (idx[:, None] >> np.arange(n, dtype=np.int64)) & 1 if n else np.zeros((size, 0), dtype=np.int64)
            coin = None
        win = np.empty((size, n), dtype=np.int64)
        weight_of = None if sample else (np.ones(size) if odds is not None else None)
        for ci in range(n):
            s1, s2 = sides[ci]
            # A FIXED SIDE STAYS A SCALAR. It used to be broadcast into a
            # full-length array for every match, which over a 127-match draw
            # allocated a quarter of a million values nothing read twice.
            a = win[:, s1[1]] if s1[0] == "col" else s1[1]
            b = win[:, s2[1]] if s2[0] == "col" else s2[1]
            if odds is not None:
                ia, ib = lookup[np.add(a, 1)], lookup[np.add(b, 1)]
                p = pair_p[ia, ib]
                ov = live_over.get(ci)
                if ov is not None:
                    i0, j0, pl = ov
                    p = np.where((ia == i0) & (ib == j0), pl,
                                 np.where((ia == j0) & (ib == i0), 1.0 - pl, p))
            # `take_a` is the coin: the first side wins this future or not.
            take_a = (coin[:, ci] < p) if sample else (bits[:, ci] == 0)
            w = np.where(take_a, a, b)
            if any_empty_side:
                # A side nobody can fill loses by walkover, whatever the coin
                # says. Only checked where a draw actually has an empty slot:
                # a power-of-two bracket has none, and these two comparisons
                # ran 127 times a chunk for nothing.
                w = np.where(np.equal(a, _NO_PLAYER), b, w)
                w = np.where(np.equal(b, _NO_PLAYER), a, w)
            win[:, ci] = w
            if weight_of is not None:
                # A walkover leaves two coins describing the same future; the
                # losing coin gets probability zero, so the duplicate carries
                # no weight rather than being counted twice.
                weight_of *= np.where(take_a, p, 1.0 - p)
        if sample:
            # ACCUMULATED, NOT MATERIALISED. The exact path builds a
            # worlds x users x matches boolean and contracts it with one
            # matmul, which is the right shape when there are thirty-two
            # thousand worlds. At a hundred thousand samples and a hundred
            # and twenty-seven matches that tensor is a hundred and fifty
            # million values per chunk, and building it costs more than the
            # arithmetic it feeds. Adding each match's points straight into
            # the running score touches the same number of elements with no
            # temporary and no second pass.
            key = np.repeat(base[None, :].astype(np.int64), size, axis=0)
            for ci in range(n):
                key += weight[ci] * (win[:, ci:ci + 1] == pick_mat[None, :, ci])
        else:
            correct = pick_mat[None, :, :] == win[:, None, :]        # worlds × users × matches
            key = base[None, :] + correct @ weight                   # worlds × users
        if sample:
            # NO PLACE CUBE WHEN SAMPLING. The exact path needs each
            # bracket's PLACE in every future, to take the min and max of it,
            # and that costs a users x users comparison per future. The
            # chances need only two questions, and both have an O(users)
            # answer:
            #
            #   first?   its key equals the best key in that future — and a
            #            tie is a win for everyone level, which is exactly
            #            the semantics the standings print.
            #   top 3?   its key is at least the third-best key. That is the
            #            same statement as "at most two brackets strictly
            #            ahead", ties included: with keys 10,9,8,8,8 the
            #            third-best is 8 and all five are inside the podium,
            #            which is right, because the three level on 8 all
            #            hold third.
            #
            # Dropping the cube took a full 128 draw from four seconds to
            # well under one, which is what makes the column affordable in
            # the first week rather than only the last weekend.
            top1 = key.max(1)
            kth = (np.partition(key, -PODIUM_PLACES, axis=1)[:, -PODIUM_PLACES]
                   if u_count > PODIUM_PLACES else key.min(1))
            p_win += (key == top1[:, None]).sum(0)
            p_pod += (key >= kth[:, None]).sum(0)
            p_total += float(size)
        else:
            ahead = key[:, None, :] > key[:, :, None]                # [w, me, other]
            place = 1 + ahead.sum(2)                                 # worlds × users
            best = np.minimum(best, place.min(0))
            worst = np.maximum(worst, place.max(0))
            if odds is not None:
                p_win += ((place == 1) * weight_of[:, None]).sum(0)
                p_pod += ((place <= PODIUM_PLACES) * weight_of[:, None]).sum(0)
                p_total += float(weight_of.sum())
    if odds is None:
        return {u: (int(best[i]), int(worst[i])) for i, u in enumerate(users)}
    # Normalised, not assumed: the weights sum to one by construction, and
    # dividing by what they actually summed to is what keeps a rounding drift
    # or a degenerate walkover from showing up as 101%.
    scale = 1.0 / p_total if p_total > 0 else 0.0
    out = {}
    if sample:
        # NO RANGE FROM A SAMPLE. best/worst are extremes and a sample misses
        # the extreme ones; the callers read None and print a dash, which is
        # what the column already does before the range is computable.
        return {u: (None, None, float(p_win[i] * scale), float(p_pod[i] * scale))
                for i, u in enumerate(users)}
    for i, u in enumerate(users):
        lo, hi = int(best[i]), int(worst[i])
        pw, pp = float(p_win[i] * scale), float(p_pod[i] * scale)
        # THE RANGE IS THE AUTHORITY ON CERTAINTY, not the sum of fifteen
        # multiplications. First in every future IS one, and the arithmetic
        # came back 0.9999999999999999 — which would have printed ">99%" beside
        # a Finish of "1–1". Snapping to the combinatorial fact is not
        # rounding: it is the only thing that keeps the two columns from
        # contradicting each other.
        if hi == 1:
            pw = 1.0
        elif lo > 1:
            pw = 0.0
        if hi <= PODIUM_PLACES:
            pp = 1.0
        elif lo > PODIUM_PLACES:
            pp = 0.0
        out[u] = (lo, hi, pw, pp)
    return out


# Same draw, same brackets, same results: same answer. Keyed on everything the
# range depends on, so a pick edited by an admin or a result reverted is a
# miss, not a stale hit.
_FINISH_CACHE: dict[tuple, Optional[dict[int, tuple[int, int]]]] = {}
# A WARMED DRAW IS ITS WHOLE TIMELINE, not a dozen entries: 127 positions for
# every scope that can ask (each league with picks, plus the global table) is
# ~760 for one Slam. At 512 a warm draw evicted itself and the work was redone
# on the next visit, which is the opposite of the point. Each entry is a dict
# of a few dozen small tuples — a few KB — so this is tens of megabytes at
# worst, and only for draws someone is actually reading.
_FINISH_CACHE_MAX = 4096
# Walks actually performed, ever. The warm pass reads it across a call to know
# whether that position was computed or merely read — a stopwatch cannot tell
# them apart, because the last few positions of a draw are exact walks over
# eight futures and finish faster than any plausible "that was cached"
# threshold. Mistaking those for cache hits made the warm pass stop eight
# positions in and leave the rest of the timeline cold.
_FINISH_CACHE_MISSES = 0


def finish_range_walks() -> int:
    """How many walks have been computed (not read from cache) in this process."""
    return _FINISH_CACHE_MISSES


# ── THE WHOLE HISTORY, ASSEMBLED, SO THE CLIENT CAN HOLD IT ─────────────────
# Positions live in _FINISH_CACHE one at a time, keyed by their snapshot — and
# reading all of them back means BUILDING a snapshot per position just to make
# the key, which is 3.5ms each and half a second for a Slam. Too much for a
# request that only wants to hand the browser a map it can scrub through
# offline. So the assembled answer is kept too, written as each position is
# computed.
#
# Keyed WITHOUT the snapshot, so each stored position carries the id of the
# last match in its slice. That is what catches a result landing in the MIDDLE
# of the timeline (a Wikipedia backfill, a corrected completed_at): every
# later position then means a different moment, and its stored id no longer
# matches the one at that index. Validation is a list walk, no snapshots.
_CHANCES_HISTORY: dict[tuple, dict[int, tuple]] = {}
_CHANCES_HISTORY_MAX = 48   # one entry per draw per scope per ratings week


def chances_fingerprint(all_matches: list, num_rounds: int,
                        picks: dict[int, dict[int, Optional[int]]], odds=None) -> str:
    """EVERYTHING THE CHANCES DEPEND ON EXCEPT WHICH MOMENT THEY DESCRIBE, as
    a short digest — the answer's version.

    Two jobs, and they are the same question asked twice:

      it keys the assembled history, which previously keyed on picks, odds and
      the draw id alone. A PLAYER REPLACED IN THE BRACKET changes none of
      those, so a stored map would have been handed out unchanged for a draw
      whose field had moved — the per-position walks were safe (their key
      carries the snapshot) but the map served to the client was not;

      and the client keys its request on it, so a completed match, a
      replacement, a withdrawal, an edited pick or a new rating week all make
      the browser ask again by themselves. It was keyed on the timeline LENGTH,
      which a replacement does not change.

    The field is (id, both sides, winner, bye) per match: that is what a
    replacement, a withdrawal and a completed match each move.
    """
    import hashlib
    parts = [
        str(draw_of(all_matches)), str(num_rounds), str(CHANCES_SCRUB_SAMPLES),
        repr(sorted((m.id, m.player1_id, m.player2_id, m.winner_id, bool(m.is_bye))
                    for m in all_matches)),
        repr(sorted((u, tuple(sorted((k, v) for k, v in (pk or {}).items() if v is not None)))
                    for u, pk in picks.items())),
        repr(getattr(odds, "cache_key", None)),
    ]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def draw_of(all_matches: list):
    """The draw these matches belong to, for the fingerprint. Matches carry
    draw_id; a plain SimpleNamespace snapshot may not, and then the rest of the
    digest identifies it anyway."""
    for m in all_matches:
        d = getattr(m, "draw_id", None)
        if d is not None:
            return d
    return None


def chances_history_key(draw_id: int, num_rounds: int,
                        picks: dict[int, dict[int, Optional[int]]], odds=None,
                        all_matches: Optional[list] = None) -> tuple:
    """Everything the answers depend on except which moment they describe."""
    return (
        draw_id, num_rounds, CHANCES_SCRUB_SAMPLES,
        tuple(sorted((u, tuple(sorted((k, v) for k, v in (pk or {}).items() if v is not None)))
                     for u, pk in picks.items())),
        getattr(odds, "cache_key", None),
        # THE FIELD, or a replaced player leaves a stale map in place: nothing
        # else in this key moves when one entry becomes another.
        chances_fingerprint(all_matches or [], num_rounds, picks, odds) if all_matches else None,
    )


def chances_history_store(key: tuple, position: int, last_match_id: Optional[int],
                          chances: dict) -> None:
    slot = _CHANCES_HISTORY.get(key)
    if slot is None:
        if len(_CHANCES_HISTORY) >= _CHANCES_HISTORY_MAX:
            _CHANCES_HISTORY.pop(next(iter(_CHANCES_HISTORY)))
        slot = _CHANCES_HISTORY[key] = {}
    slot[position] = (last_match_id, chances)


def chances_history_held(key: tuple, timeline_ids: list[int]) -> dict[int, dict]:
    """Every position held for this key that still describes the moment the
    current timeline puts at that index."""
    slot = _CHANCES_HISTORY.get(key)
    if not slot:
        return {}
    out = {}
    for pos, (last_id, chances) in slot.items():
        if 1 <= pos <= len(timeline_ids) and timeline_ids[pos - 1] == last_id:
            out[pos] = chances
    return out


def finish_range_cached(draw_id: int, all_matches: list, pts_table: dict[int, int], num_rounds: int,
                        banked: dict[int, UserScore], picks: dict[int, dict[int, Optional[int]]],
                        odds=None, sample: bool = False, samples: Optional[int] = None):
    key = (
        draw_id, num_rounds,
        tuple(sorted((m.id, m.winner_id, bool(m.is_bye), m.player1_id, m.player2_id) for m in all_matches)),
        tuple(sorted((u, tuple(sorted((k, v) for k, v in (picks.get(u) or {}).items() if v is not None)))
                     for u in banked)),
        # The odds source's own key: a new Elo week, a set won in a match in
        # progress, or a coefficient change all make this a different answer
        # for the same bracket and the same results.
        getattr(odds, "cache_key", None),
        # Sampled and enumerated are different answers to the same question,
        # and one of them has no range in it. The sample SIZE is part of it
        # too: the scrub draws fewer futures than the live figure does.
        sample, samples if sample else None,
    )
    if key in _FINISH_CACHE:
        return _FINISH_CACHE[key]
    global _FINISH_CACHE_MISSES
    _FINISH_CACHE_MISSES += 1
    out = finish_range(all_matches, pts_table, num_rounds, banked, picks, odds, sample, samples)
    if len(_FINISH_CACHE) >= _FINISH_CACHE_MAX:
        _FINISH_CACHE.pop(next(iter(_FINISH_CACHE)))
    _FINISH_CACHE[key] = out
    return out


async def finish_range_async(draw_id: int, all_matches: list, pts_table: dict[int, int], num_rounds: int,
                             banked: dict[int, UserScore], picks: dict[int, dict[int, Optional[int]]],
                             odds=None, sample: bool = False):
    """finish_range_cached off the event loop. The matches are copied to plain
    records first, so no ORM object is touched from the worker thread — and
    neither does `odds`, which is built on the loop and is pure data after."""
    import asyncio
    from types import SimpleNamespace
    plain = [SimpleNamespace(id=m.id, round_number=m.round_number, match_number=m.match_number,
                             player1_id=m.player1_id, player2_id=m.player2_id,
                             winner_id=m.winner_id, is_bye=bool(m.is_bye)) for m in all_matches]
    return await asyncio.to_thread(finish_range_cached, draw_id, plain, pts_table, num_rounds,
                                   banked, picks, odds, sample)


# A podium is locked when the worst place a bracket can hold is third or
# better. Places are competition-ranked, so two brackets level in third both
# take the bronze.
PODIUM_PLACES = 3


def podium_locked(rng: Optional[tuple]) -> Optional[bool]:
    return None if rng is None else rng[1] <= PODIUM_PLACES


# ---------------------------------------------------------------------------
# What-if worlds — every way the last matches can go, one label each
# ---------------------------------------------------------------------------

# From the semis on: 3 undecided matches make 8 worlds, the final alone 2.
# Each is labelled by its final ("Zverev def. Shelton"), which is unique
# from the semis on — four possible finals, two ways each.
WORLDS_MAX_UNDECIDED = 3


def enumerate_worlds(all_matches: list, pts_table: dict[int, int],
                     names_by_entry: dict[int, str]) -> Optional[list[dict]]:
    """Every future of the undecided matches, walked forward through the
    bracket, as plain results. None when there is nothing left to play or too
    much (see WORLDS_MAX_UNDECIDED). Each world: {"results": [{match_id,
    round_number, points, winner_id, loser_id}...], "final": {winner_id,
    loser_id, winner, loser}} — the final is the last undecided match, and
    its names are what the world is called."""
    import itertools
    undecided = _undecided(all_matches)
    n = len(undecided)
    if n == 0 or n > WORLDS_MAX_UNDECIDED:
        return None
    by_slot = {(m.round_number, m.match_number): m for m in all_matches}
    worlds: list[dict] = []
    seen: set[tuple] = set()
    for coin in itertools.product((0, 1), repeat=n):
        winner = {m.id: m.winner_id for m in all_matches}
        results = []
        for m, c in zip(undecided, coin):
            def _side(pid, feeder_no):
                if pid is not None:
                    return pid
                feeder = by_slot.get((m.round_number - 1, feeder_no))
                return winner.get(feeder.id) if feeder is not None else None
            s1 = _side(m.player1_id, 2 * m.match_number - 1)
            s2 = _side(m.player2_id, 2 * m.match_number)
            # A side nobody can fill loses by walkover, whatever the coin says.
            w = (s1, s2)[c]
            if w is None:
                w = s2 if s1 is None else s1
            lo = s2 if w == s1 else s1
            winner[m.id] = w
            results.append({"match_id": m.id, "round_number": m.round_number,
                            "points": pts_table.get(m.round_number, 0),
                            "winner_id": w, "loser_id": lo})
        key = tuple(r["winner_id"] for r in results)
        if key in seen:      # a walkover makes two coins the same world
            continue
        seen.add(key)
        last = results[-1]
        worlds.append({
            "results": results,
            "final": {"winner_id": last["winner_id"], "loser_id": last["loser_id"],
                      "winner": names_by_entry.get(last["winner_id"]),
                      "loser": names_by_entry.get(last["loser_id"])},
        })
    return worlds


# ---------------------------------------------------------------------------
# Finish history — the range as it stood at every point of the timeline
# ---------------------------------------------------------------------------

def _snapshot(all_matches: list, decided: set) -> list:
    """The draw as it stood when only `decided` (match ids) had results: every
    other match loses its winner, and its players too unless they came from
    a decided feeder — a later round's slots were blank at the time."""
    from types import SimpleNamespace
    by_slot = {(m.round_number, m.match_number): m for m in all_matches}
    out = []
    for m in all_matches:
        if m.id in decided:
            out.append(SimpleNamespace(id=m.id, round_number=m.round_number, match_number=m.match_number,
                                       player1_id=m.player1_id, player2_id=m.player2_id,
                                       winner_id=m.winner_id, is_bye=bool(m.is_bye)))
            continue
        def _side(pid, feeder_no):
            if m.round_number == 1:
                return pid
            f = by_slot.get((m.round_number - 1, feeder_no))
            return f.winner_id if (f is not None and f.id in decided) else None
        out.append(SimpleNamespace(id=m.id, round_number=m.round_number, match_number=m.match_number,
                                   player1_id=_side(m.player1_id, 2 * m.match_number - 1),
                                   player2_id=_side(m.player2_id, 2 * m.match_number),
                                   winner_id=None, is_bye=bool(m.is_bye)))
    return out


def finish_history(draw_id: int, all_matches: list, timeline_ids: list[int], pts_table: dict[int, int],
                   num_rounds: int, picks: dict[int, dict[int, Optional[int]]],
                   odds=None) -> tuple[Optional[int], dict]:
    """{position: {user_id: (best, worst[, p_win, p_podium])}} for every position from
    the first at which the range is computable (FINISH_RANGE_MAX_UNDECIDED
    matches left) through the present, and that first position. The slider
    shows a snapshot; this is the Finish column of each snapshot. A dozen
    enumerations at most, halving in size as the draw closes — about twice
    the cost of the live one, and each cached like it."""
    byes = {m.id for m in all_matches if m.is_bye}
    contests = sum(1 for m in all_matches if not m.is_bye)
    first = max(1, contests - FINISH_RANGE_MAX_UNDECIDED)
    if len(timeline_ids) < first or not picks:
        return None, {}
    out: dict = {}
    # A PAST MOMENT IS PRICED WITHOUT WHAT IS ON COURT NOW — see
    # DrawOdds.without_live: it is both the honest snapshot and the only way
    # these answers survive the poller's next tick.
    odds = odds.without_live() if hasattr(odds, "without_live") else odds
    for p in range(first, len(timeline_ids) + 1):
        rng = _position_range(draw_id, all_matches, byes, timeline_ids, p, pts_table,
                              num_rounds, picks, odds, sample=False)
        if rng:
            out[p] = rng
    return first, out


def _position_range(draw_id: int, all_matches: list, byes: set, timeline_ids: list[int], position: int,
                    pts_table: dict[int, int], num_rounds: int,
                    picks: dict[int, dict[int, Optional[int]]], odds=None, sample: bool = False,
                    samples: Optional[int] = None):
    """One snapshot: the draw as it stood after `position` results, scored, and
    run through the same walk the live table uses."""
    by_id = {m.id: m for m in all_matches}
    played = timeline_ids[:position]
    snap = _snapshot(all_matches, byes | set(played))
    banked = {}
    for uid, pk in picks.items():
        total, by_round = 0.0, {}
        for mid in played:
            m = by_id.get(mid)
            if m is not None and pk.get(mid) == m.winner_id:
                total += pts_table.get(m.round_number, 0)
                by_round[m.round_number] = by_round.get(m.round_number, 0) + 1
        banked[uid] = UserScore(user_id=uid, total_points=total, correct_count=sum(by_round.values()),
                                correct_by_round=by_round)
    return finish_range_cached(draw_id, snap, pts_table, num_rounds, banked, picks, odds, sample, samples)


def chances_at(draw_id: int, all_matches: list, timeline_ids: list[int], position: int,
               pts_table: dict[int, int], num_rounds: int,
               picks: dict[int, dict[int, Optional[int]]], odds=None):
    """THE CHANCES OF ONE SNAPSHOT, COMPUTED ON DEMAND — the position under the
    slider's thumb, and only that one.

    `finish_history` walks every position from fifteen undecided matches on,
    because there the walk is exact, cheap, and brings the range with it. It
    cannot reach further back eagerly: before that line a walk is a hundred
    thousand sampled futures, about eleven milliseconds per undecided match,
    and a Slam has a hundred and twenty such positions — ninety seconds to
    answer a question the reader asked of one of them. So the early positions
    are computed one at a time, when the slider actually stops on one, and
    cached like every other walk.

    Returns `(sampled, {user_id: (p_win, p_podium)})`; the range is not
    returned, because at these depths it does not exist (see `finish_range`)
    and the caller already has it for every position where it does."""
    if not picks or not timeline_ids:
        return False, {}
    odds = odds.without_live() if hasattr(odds, "without_live") else odds
    position = max(1, min(int(position), len(timeline_ids)))
    byes = {m.id for m in all_matches if m.is_bye}
    undecided = sum(1 for m in all_matches if not m.is_bye) - position
    sample = undecided > FINISH_RANGE_MAX_UNDECIDED
    if undecided > CHANCES_MAX_UNDECIDED:
        return sample, {}
    rng = _position_range(draw_id, all_matches, byes, timeline_ids, position, pts_table,
                          num_rounds, picks, odds, sample=sample,
                          samples=CHANCES_SCRUB_SAMPLES if sample else None)
    if not rng:
        return sample, {}
    out = {u: (v[2], v[3]) for u, v in rng.items() if len(v) > 3}
    # Written through to the assembled history, so a client can be handed the
    # whole thing and scrub with no request at all.
    chances_history_store(chances_history_key(draw_id, num_rounds, picks, odds, all_matches),
                          position, timeline_ids[position - 1], out)
    return sample, out


# ONE SAMPLED WALK AT A TIME. A single position costs up to a second and a half
# of arithmetic, and this endpoint is reachable once per slider stop: a burst
# would otherwise put a thread per request against the live poller, which has
# ten seconds to fetch and store every score on court. Queued, they cost the
# same total and leave the loop alone. Built lazily — an asyncio primitive
# created at import binds the wrong loop under the test client.
_CHANCES_GATE = None


async def chances_at_async(draw_id, all_matches, timeline_ids, position, pts_table, num_rounds,
                           picks, odds=None):
    import asyncio
    from types import SimpleNamespace
    global _CHANCES_GATE
    if _CHANCES_GATE is None:
        _CHANCES_GATE = asyncio.Semaphore(1)
    plain = [SimpleNamespace(id=m.id, round_number=m.round_number, match_number=m.match_number,
                             player1_id=m.player1_id, player2_id=m.player2_id,
                             winner_id=m.winner_id, is_bye=bool(m.is_bye)) for m in all_matches]
    async with _CHANCES_GATE:
        return await asyncio.to_thread(chances_at, draw_id, plain, list(timeline_ids), position,
                                       pts_table, num_rounds, picks, odds)


async def finish_history_async(draw_id, all_matches, timeline_ids, pts_table, num_rounds, picks,
                               odds=None):
    import asyncio
    from types import SimpleNamespace
    plain = [SimpleNamespace(id=m.id, round_number=m.round_number, match_number=m.match_number,
                             player1_id=m.player1_id, player2_id=m.player2_id,
                             winner_id=m.winner_id, is_bye=bool(m.is_bye)) for m in all_matches]
    return await asyncio.to_thread(finish_history, draw_id, plain, list(timeline_ids), pts_table,
                                   num_rounds, picks, odds)
