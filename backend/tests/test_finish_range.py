"""finish_range: the best and worst place a bracket can still finish on.

The oracle is the scoring engine itself — every future scored with the plain
per-user loop and ranked with rank_users — so the packed-key vector version is
checked against the code the standings actually run.
"""
import itertools
import random
from types import SimpleNamespace as NS

from app.services.scoring import (
    FINISH_RANGE_MAX_UNDECIDED, UserScore, finish_range, finish_range_available, rank_users,
)


def _m(id, r, k, p1=None, p2=None, winner=None, bye=False):
    return NS(id=id, round_number=r, match_number=k, player1_id=p1, player2_id=p2,
              winner_id=winner, is_bye=bye, status="completed" if winner is not None else "scheduled")


def _bracket(size, decided_r1=0, rng=None):
    """A `size` draw, R1 lines 1..size, with the first `decided_r1` R1 matches played."""
    rng = rng or random.Random(0)
    ms, mid, rounds = [], 1, size.bit_length() - 1
    for r in range(1, rounds + 1):
        for k in range(1, size // (2 ** r) + 1):
            if r == 1:
                p1, p2 = 2 * k - 1, 2 * k
                w = rng.choice([p1, p2]) if k <= decided_r1 else None
                ms.append(_m(mid, r, k, p1, p2, w))
            else:
                ms.append(_m(mid, r, k))
            mid += 1
    # R2 slots fed by decided R1 matches are filled, as the scraper fills them.
    by = {(m.round_number, m.match_number): m for m in ms}
    for m in ms:
        if m.round_number == 2:
            f1, f2 = by[(1, 2 * m.match_number - 1)], by[(1, 2 * m.match_number)]
            m.player1_id, m.player2_id = f1.winner_id, f2.winner_id
    return ms


def _random_picks(ms, size, rng):
    """A cascade: each pick advances from the picks below it."""
    picks, by = {}, {(m.round_number, m.match_number): m for m in ms}
    for m in sorted(ms, key=lambda m: (m.round_number, m.match_number)):
        if m.round_number == 1:
            cands = [m.player1_id, m.player2_id]
        else:
            cands = [picks.get(by[(m.round_number - 1, 2 * m.match_number - 1)].id),
                     picks.get(by[(m.round_number - 1, 2 * m.match_number)].id)]
        cands = [c for c in cands if c is not None]
        if cands and rng.random() > 0.05:   # a few blanks: partial brackets compete too
            picks[m.id] = rng.choice(cands)
    return picks


def _score(picks, ms, pts):
    total, by_round = 0, {}
    for m in ms:
        if m.is_bye or m.winner_id is None or picks.get(m.id) != m.winner_id:
            continue
        total += pts[m.round_number]
        by_round[m.round_number] = by_round.get(m.round_number, 0) + 1
    return total, by_round


def _oracle(ms, pts, num_rounds, picks_by_user):
    undecided = sorted((m for m in ms if not m.is_bye and m.winner_id is None),
                       key=lambda m: (m.round_number, m.match_number))
    by = {(m.round_number, m.match_number): m for m in ms}
    best = {u: 10 ** 9 for u in picks_by_user}
    worst = {u: 0 for u in picks_by_user}
    for coin in itertools.product((0, 1), repeat=len(undecided)):
        winner = {m.id: m.winner_id for m in ms}
        for m, c in zip(undecided, coin):
            s1 = m.player1_id if m.player1_id is not None else winner.get(by[(m.round_number - 1, 2 * m.match_number - 1)].id)
            s2 = m.player2_id if m.player2_id is not None else winner.get(by[(m.round_number - 1, 2 * m.match_number)].id)
            winner[m.id] = (s1, s2)[c]
        future = [NS(id=m.id, round_number=m.round_number, is_bye=m.is_bye, winner_id=winner[m.id]) for m in ms]
        scores = []
        for u, p in picks_by_user.items():
            t, br = _score(p, future, pts)
            scores.append(UserScore(user_id=u, total_points=t, correct_count=sum(br.values()), correct_by_round=br))
        ranked = rank_users(scores, num_rounds)
        keys = {s.user_id: s.tiebreak_key(num_rounds) for s in ranked}
        # The place the standings print: one plus the brackets strictly ahead.
        for u in picks_by_user:
            ahead = sum(1 for v in keys.values() if v < keys[u])
            best[u] = min(best[u], 1 + ahead)
            worst[u] = max(worst[u], 1 + ahead)
    return {u: (best[u], worst[u]) for u in picks_by_user}


def _banked(ms, pts, picks_by_user):
    out = {}
    for u, p in picks_by_user.items():
        t, br = _score(p, ms, pts)
        out[u] = UserScore(user_id=u, total_points=t, correct_count=sum(br.values()), correct_by_round=br)
    return out


PTS16 = {1: 2, 2: 4, 3: 8, 4: 12}


def test_matches_the_oracle_on_random_draws():
    rng = random.Random(7)
    for trial in range(6):
        ms = _bracket(16, decided_r1=rng.choice([4, 6, 8]), rng=rng)
        picks = {u: _random_picks(ms, 16, rng) for u in range(1, rng.randint(3, 9))}
        got = finish_range(ms, PTS16, 4, _banked(ms, PTS16, picks), picks)
        assert got == _oracle(ms, PTS16, 4, picks), f"trial {trial}"


def test_full_r16_is_the_limit():
    ms = _bracket(32, decided_r1=16)
    assert finish_range_available(ms)
    assert sum(1 for m in ms if m.winner_id is None) == FINISH_RANGE_MAX_UNDECIDED
    ms = _bracket(32, decided_r1=15)
    assert not finish_range_available(ms)
    assert finish_range(ms, {1: 1, 2: 2, 3: 4, 4: 8, 5: 12}, 5, {1: UserScore(1, 0, 0)}, {1: {}}) is None


def test_decided_draw_is_the_standings():
    ms = _bracket(4, decided_r1=2, rng=random.Random(1))
    by = {(m.round_number, m.match_number): m for m in ms}
    f = by[(2, 1)]
    f.player1_id, f.player2_id = by[(1, 1)].winner_id, by[(1, 2)].winner_id
    f.winner_id = f.player1_id
    pts = {1: 1, 2: 2}
    picks = {1: {m.id: m.winner_id for m in ms}, 2: {}, 3: {}}
    got = finish_range(ms, pts, 2, _banked(ms, pts, picks), picks)
    # Two brackets level in second are both second, in every future.
    assert got == {1: (1, 1), 2: (2, 2), 3: (2, 2)}


def test_bye_and_walkover_sides():
    # A 4-draw where line 4 never existed: R1 match 2 is a bye and the
    # final's second side comes from it already.
    ms = [_m(1, 1, 1, 1, 2), _m(2, 1, 2, 3, None, winner=3, bye=True), _m(3, 2, 1, None, 3)]
    pts = {1: 1, 2: 2}
    picks = {1: {1: 1, 3: 1}, 2: {1: 2, 3: 3}}
    got = finish_range(ms, pts, 2, _banked(ms, pts, picks), picks)
    assert got == _oracle(ms, pts, 2, picks)


def test_podium_locks_at_third():
    from app.services.scoring import podium_locked
    assert podium_locked((2, 3)) is True
    assert podium_locked((2, 4)) is False
    assert podium_locked(None) is None


def test_tie_for_third_is_third():
    # Three brackets, two of them identical: level in every future, and the
    # standings print both as the same place — so the range says so too.
    ms = _bracket(4, decided_r1=2, rng=random.Random(3))
    pts = {1: 1, 2: 2}
    same = _random_picks(ms, 4, random.Random(5))
    picks = {1: same, 2: dict(same), 3: {m.id: m.winner_id for m in ms if m.winner_id}}
    got = finish_range(ms, pts, 2, _banked(ms, pts, picks), picks)
    assert got[1] == got[2]
    assert got == _oracle(ms, pts, 2, picks)


def test_worlds_from_the_semis():
    from app.services.scoring import enumerate_worlds
    # An 8-draw with the quarters done: two semis and a final = 8 worlds.
    ms = _bracket(8, decided_r1=4, rng=random.Random(2))
    pts = {1: 1, 2: 2, 3: 4}
    names = {i: f"P{i}" for i in range(1, 9)}
    worlds = enumerate_worlds(ms, pts, names)
    assert len(worlds) == 8
    finals = {(w["final"]["winner"], w["final"]["loser"]) for w in worlds}
    assert len(finals) == 8                       # every label is unique
    for w in worlds:
        assert [r["round_number"] for r in w["results"]] == [2, 2, 3]
        assert w["results"][-1]["points"] == 4
        # The final is contested by the two semi winners of that world.
        semi_winners = {w["results"][0]["winner_id"], w["results"][1]["winner_id"]}
        assert {w["final"]["winner_id"], w["final"]["loser_id"]} == semi_winners


def test_worlds_off_before_the_semis_and_after_the_final():
    from app.services.scoring import enumerate_worlds
    assert enumerate_worlds(_bracket(16, decided_r1=8), {1: 1, 2: 2, 3: 4, 4: 8}, {}) is None
    ms = _bracket(4, decided_r1=2, rng=random.Random(1))
    by = {(m.round_number, m.match_number): m for m in ms}
    f = by[(2, 1)]; f.player1_id, f.player2_id = by[(1, 1)].winner_id, by[(1, 2)].winner_id
    assert len(enumerate_worlds(ms, {1: 1, 2: 2}, {})) == 2
    f.winner_id = f.player1_id
    assert enumerate_worlds(ms, {1: 1, 2: 2}, {}) is None
