"""Win and podium probability: the weighted twin of the Finish range.

The oracle is a plain Python walk of every future, multiplying one match
probability at a time and summing the weight of the futures a bracket finishes
first (or top three) in. Nothing is sampled on either side, so the two must
agree to floating point.
"""
import itertools
import random
from types import SimpleNamespace as NS

import pytest

from app.services.scoring import UserScore, finish_range, rank_users
from app.services.win_chances import DrawOdds, LiveScore
from app.services.winprob import predict

from tests.test_finish_range import _bracket, _banked, _random_picks, _score, PTS16


def _odds(entries, best_of=3, live=None):
    """Odds over entry ids 1..n, ratings spread so no two players are level."""
    ratings = {i: (1700 + 37 * ((i * 7) % 11), None, i) for i in entries}
    return DrawOdds(ratings, "Hard", best_of, live or {}, ("test", best_of, tuple(sorted(live or {}))))


def _oracle(ms, pts, num_rounds, picks_by_user, odds):
    """{user: (p_win, p_podium)} by walking every future with its weight."""
    undecided = sorted((m for m in ms if not m.is_bye and m.winner_id is None),
                       key=lambda m: (m.round_number, m.match_number))
    by = {(m.round_number, m.match_number): m for m in ms}
    p_win = {u: 0.0 for u in picks_by_user}
    p_pod = {u: 0.0 for u in picks_by_user}
    total = 0.0
    for coin in itertools.product((0, 1), repeat=len(undecided)):
        winner = {m.id: m.winner_id for m in ms}
        weight = 1.0
        for m, c in zip(undecided, coin):
            s1 = m.player1_id if m.player1_id is not None else winner.get(by[(m.round_number - 1, 2 * m.match_number - 1)].id)
            s2 = m.player2_id if m.player2_id is not None else winner.get(by[(m.round_number - 1, 2 * m.match_number)].id)
            if s1 is None:
                winner[m.id], p = s2, 0.0
            elif s2 is None:
                winner[m.id], p = s1, 1.0
            else:
                winner[m.id] = (s1, s2)[c]
                p = odds.pair_prob(s1, s2, m.id)
            weight *= p if c == 0 else 1.0 - p
        future = [NS(id=m.id, round_number=m.round_number, is_bye=m.is_bye, winner_id=winner[m.id]) for m in ms]
        scores = []
        for u, pk in picks_by_user.items():
            t, br = _score(pk, future, pts)
            scores.append(UserScore(user_id=u, total_points=t, correct_count=sum(br.values()), correct_by_round=br))
        keys = {s.user_id: s.tiebreak_key(num_rounds) for s in rank_users(scores, num_rounds)}
        total += weight
        for u in picks_by_user:
            place = 1 + sum(1 for v in keys.values() if v < keys[u])
            if place == 1:
                p_win[u] += weight
            if place <= 3:
                p_pod[u] += weight
    return {u: (p_win[u] / total, p_pod[u] / total) for u in picks_by_user}


def test_matches_the_oracle_on_random_draws():
    rng = random.Random(7)
    for trial in range(5):
        ms = _bracket(16, decided_r1=rng.choice([4, 6, 8]), rng=rng)
        picks = {u: _random_picks(ms, 16, rng) for u in range(1, rng.randint(3, 8))}
        odds = _odds(range(1, 17))
        got = finish_range(ms, PTS16, 4, _banked(ms, PTS16, picks), picks, odds)
        want = _oracle(ms, PTS16, 4, picks, odds)
        for u in picks:
            # abs=1e-9, not exact: a certain place is snapped to 1.0 or 0.0
            # from the range, which is the same number the oracle reaches by
            # multiplication give or take the last bit.
            assert got[u][2] == pytest.approx(want[u][0], abs=1e-9), f"trial {trial} win u{u}"
            assert got[u][3] == pytest.approx(want[u][1], abs=1e-9), f"trial {trial} podium u{u}"


def test_range_is_unchanged_by_asking_for_odds():
    """The same enumeration, so the first two numbers must not move."""
    rng = random.Random(3)
    ms = _bracket(16, decided_r1=8, rng=rng)
    picks = {u: _random_picks(ms, 16, rng) for u in range(1, 6)}
    banked = _banked(ms, PTS16, picks)
    plain = finish_range(ms, PTS16, 4, banked, picks)
    with_odds = finish_range(ms, PTS16, 4, banked, picks, _odds(range(1, 17)))
    assert {u: v[:2] for u, v in with_odds.items()} == plain


def test_probabilities_sum_over_the_field():
    """Someone wins: the win column sums to one, plus a share for each tie.

    A tie for first is a win for everyone level, exactly as the standings
    print it — so the column can sum to more than one, and never to less.
    """
    rng = random.Random(5)
    ms = _bracket(16, decided_r1=6, rng=rng)
    picks = {u: _random_picks(ms, 16, rng) for u in range(1, 7)}
    got = finish_range(ms, PTS16, 4, _banked(ms, PTS16, picks), picks, _odds(range(1, 17)))
    assert sum(v[2] for v in got.values()) >= 1.0 - 1e-9
    assert all(0.0 <= v[2] <= v[3] <= 1.0 + 1e-9 for v in got.values())


def test_a_locked_podium_is_a_certainty():
    """Whatever the odds say, a place nothing can take away reads 100%."""
    rng = random.Random(9)
    ms = _bracket(16, decided_r1=8, rng=rng)
    picks = {u: _random_picks(ms, 16, rng) for u in range(1, 8)}
    got = finish_range(ms, PTS16, 4, _banked(ms, PTS16, picks), picks, _odds(range(1, 17)))
    for u, (best, worst, pw, pp) in got.items():
        assert (pp == pytest.approx(1.0)) == (worst <= 3), u
        assert (pw == pytest.approx(1.0)) == (worst == 1), u
        assert (pw == pytest.approx(0.0)) == (best > 1), u


def test_certainty_is_exact_not_nearly():
    """A locked place must not print as ">99%" beside a Finish of "1-1"."""
    rng = random.Random(13)
    ms = _bracket(16, decided_r1=8, rng=rng)
    picks = {u: _random_picks(ms, 16, rng) for u in range(1, 9)}
    got = finish_range(ms, PTS16, 4, _banked(ms, PTS16, picks), picks, _odds(range(1, 17)))
    for best, worst, pw, pp in got.values():
        if worst == 1:
            assert pw == 1.0          # exactly, not 0.9999999999999999
        if best > 1:
            assert pw == 0.0
        if worst <= 3:
            assert pp == 1.0
        if best > 3:
            assert pp == 0.0


def test_decided_draw_is_ones_and_zeroes():
    ms = _bracket(4, decided_r1=2, rng=random.Random(1))
    by = {(m.round_number, m.match_number): m for m in ms}
    f = by[(2, 1)]
    f.player1_id, f.player2_id = by[(1, 1)].winner_id, by[(1, 2)].winner_id
    f.winner_id = f.player1_id
    pts = {1: 1, 2: 2}
    picks = {1: {m.id: m.winner_id for m in ms}, 2: {}, 3: {}}
    got = finish_range(ms, pts, 2, _banked(ms, pts, picks), picks, _odds(range(1, 5)))
    assert got == {1: (1, 1, 1.0, 1.0), 2: (2, 2, 0.0, 1.0), 3: (2, 2, 0.0, 1.0)}


def test_walkover_future_carries_no_weight():
    """A side nobody can fill makes two coins one future; only one may count."""
    ms = [NS(id=1, round_number=1, match_number=1, player1_id=1, player2_id=2,
             winner_id=None, is_bye=False, status="scheduled"),
          NS(id=2, round_number=1, match_number=2, player1_id=3, player2_id=None,
             winner_id=3, is_bye=True, status="completed"),
          NS(id=3, round_number=2, match_number=1, player1_id=None, player2_id=3,
             winner_id=None, is_bye=False, status="scheduled")]
    pts = {1: 1, 2: 2}
    picks = {1: {1: 1, 3: 1}, 2: {1: 2, 3: 3}}
    got = finish_range(ms, pts, 2, _banked(ms, pts, picks), picks, _odds(range(1, 4)))
    assert sum(v[2] for v in got.values()) >= 1.0 - 1e-9


def test_live_set_score_moves_the_odds():
    """Two sets down in the final is not the pre-match number any more."""
    ms = _bracket(4, decided_r1=2, rng=random.Random(1))
    by = {(m.round_number, m.match_number): m for m in ms}
    f = by[(2, 1)]
    a, b = by[(1, 1)].winner_id, by[(1, 2)].winner_id
    f.player1_id, f.player2_id = a, b
    pts = {1: 1, 2: 2}
    picks = {1: {f.id: a}, 2: {f.id: b}}
    banked = _banked(ms, pts, picks)
    flat = finish_range(ms, pts, 2, banked, picks, _odds(range(1, 5)))
    down = finish_range(ms, pts, 2, banked, picks,
                        _odds(range(1, 5), live={f.id: (a, b, LiveScore((0, 2), (0, 0), False))}))
    # Whoever backed `a` was better off before those two sets went the other way.
    assert down[1][2] < flat[1][2]
    assert down[2][2] > flat[2][2]
    assert down[1][2] + down[2][2] == pytest.approx(1.0)


def test_odds_source_reaches_the_cache_key():
    """Same bracket, different odds: two answers, not one cached twice."""
    from app.services.scoring import finish_range_cached
    ms = _bracket(8, decided_r1=4, rng=random.Random(4))
    pts = {1: 1, 2: 2, 3: 4}
    picks = {u: _random_picks(ms, 8, random.Random(u)) for u in range(1, 4)}
    banked = _banked(ms, pts, picks)
    one = finish_range_cached(901, ms, pts, 3, banked, picks, _odds(range(1, 9), best_of=3))
    two = finish_range_cached(901, ms, pts, 3, banked, picks, _odds(range(1, 9), best_of=5))
    assert one != two


def test_best_of_five_is_the_mens_slam_only():
    from app.services.win_chances import best_of
    assert best_of(NS(sofa_number_of_sets=None, gender="M", category="Grand Slam")) == 5
    assert best_of(NS(sofa_number_of_sets=None, gender="F", category="Grand Slam")) == 3
    assert best_of(NS(sofa_number_of_sets=None, gender="M", category="ATP 1000")) == 3
    # What the feed says beats the rule.
    assert best_of(NS(sofa_number_of_sets=3, gender="M", category="Grand Slam")) == 3


def test_best_of_five_favours_the_favourite():
    """More sets is more chances for the better player. The model must agree."""
    p3 = predict(elo_x=2050, elo_y=1900, best_of=3)["p"]
    p5 = predict(elo_x=2050, elo_y=1900, best_of=5)["p"]
    assert 0.5 < p3 < p5


def test_surface_elo_is_preferred_and_needs_both_sides():
    """A surface figure on both sides is the answer; on one side it is not used."""
    both = DrawOdds({1: (2000, 2050, 1), 2: (1900, 1850, 2)}, "Hard", 3, {}, ("s",))
    overall = DrawOdds({1: (2000, None, 1), 2: (1900, 1850, 2)}, "Hard", 3, {}, ("o",))
    assert both.pair_prob(1, 2) > overall.pair_prob(1, 2)     # the surface gap is wider here
    assert overall.pair_prob(1, 2) == DrawOdds({1: (2000, None, 1), 2: (1900, None, 2)}, "Hard", 3, {}, ("o2",)).pair_prob(1, 2)


def test_the_ranking_counts_beside_elo():
    """Same Elo gap, but the ranking says the second man is the better player."""
    o = DrawOdds({1: (2000, None, 40), 2: (1950, None, 5)}, "Hard", 3, {}, ("r",))
    flat = DrawOdds({1: (2000, None, None), 2: (1950, None, None)}, "Hard", 3, {}, ("r2",))
    assert o.pair_prob(1, 2) < flat.pair_prob(1, 2)
    assert o.pair_prob(1, 2) + o.pair_prob(2, 1) == pytest.approx(1.0)


def test_games_in_progress_move_the_live_number():
    """A set down but serving for the second is not the same as a set down."""
    base = {1: (2050, None, 3), 2: (1950, None, 9)}
    sets_only = DrawOdds(base, "Hard", 3, {9: (1, 2, LiveScore((0, 1), (0, 0), False))}, ("a",))
    serving_for_it = DrawOdds(base, "Hard", 3, {9: (1, 2, LiveScore((0, 1), (5, 2), False))}, ("b",))
    assert serving_for_it.pair_prob(1, 2, 9) > sets_only.pair_prob(1, 2, 9)
    # The pre-match figure is untouched for the same pair in a different match.
    assert serving_for_it.pair_prob(1, 2, 8) == DrawOdds(base, "Hard", 3, {}, ("c",)).pair_prob(1, 2)


def test_live_score_is_read_off_the_snapshot():
    """Sets won, the set in progress, and a tiebreak — from the poller's own shape."""
    from datetime import datetime, timezone
    from types import SimpleNamespace as NS
    from app.services.win_chances import _live_score
    now = datetime.now(timezone.utc).isoformat()
    m = NS(sofa_live_json={"sets": [[6, 3], [2, 5]], "point": ["15", "30"], "tiebreak": False,
                           "match_tiebreak": False, "serving": 1, "at": now}, winner_id=None)
    assert _live_score(m) == LiveScore((1, 0), (2, 5), False)
    m.sofa_live_json = {"sets": [[6, 3], [6, 6]], "point": ["3", "4"], "tiebreak": True,
                        "match_tiebreak": False, "serving": 2, "at": now}
    assert _live_score(m) == LiveScore((1, 0), (6, 6), True)
    # A finished last set is a set won, not a set in progress.
    m.sofa_live_json = {"sets": [[6, 3], [7, 5]], "point": None, "tiebreak": False, "match_tiebreak": False, "serving": None, "at": now}
    assert _live_score(m) == LiveScore((2, 0), (0, 0), False)
    # Nothing on court reads as nothing.
    m.sofa_live_json = None
    assert _live_score(m) is None
    # And a snapshot older than LIVE_MAX_AGE is not a scoreboard any more.
    m.sofa_live_json = {"sets": [[6, 3], [2, 5]], "point": None, "tiebreak": False, "match_tiebreak": False, "serving": None, "at": "2026-01-01T00:00:00+00:00"}
    assert _live_score(m) is None


def test_own_rating_leads_only_once_fitted(monkeypatch):
    """Our own Elo is preferred when both players carry one AND the model has
    been fitted; before that the Tennis Abstract path answers, unchanged."""
    from app.services.winprob import _params
    base = dict(_params._PARAMS)
    own = dict(base["own"]); own.update({"fitted": False, "surface_w": 0.5, "k_logit": 1.0, "k_rank": 0.0})
    monkeypatch.setitem(_params._PARAMS, "own", own)
    ta = DrawOdds({1: (2000, 2000, 1, (1600.0, 1600.0)), 2: (1900, 1900, 2, (1900.0, 1900.0))}, "Hard", 3, {}, ("u",))
    p_ta = ta.pair_prob(1, 2)
    assert p_ta > 0.5                                  # TA says 1 is better
    own["fitted"] = True
    ours = DrawOdds({1: (2000, 2000, 1, (1600.0, 1600.0)), 2: (1900, 1900, 2, (1900.0, 1900.0))}, "Hard", 3, {}, ("v",))
    assert ours.pair_prob(1, 2) < 0.5                  # our record says 2 is better, and it now leads
    assert ours.pair_prob(1, 2) + ours.pair_prob(2, 1) == pytest.approx(1.0)
    # One side without an own rating: the pair is answered in the scale both share.
    mixed = DrawOdds({1: (2000, 2000, 1, None), 2: (1900, 1900, 2, (1900.0, 1900.0))}, "Hard", 3, {}, ("w",))
    assert mixed.pair_prob(1, 2) == p_ta


def test_thin_ratings_are_shrunk_toward_the_mean(monkeypatch):
    """A rating with little behind it is pulled toward 1500; a deep one is not."""
    from app.services.winprob.elo import shrink_rating, own_params
    # No shrinkage configured: the rating is untouched whatever its depth.
    assert shrink_rating(1800.0, 20, 0) == 1800.0
    # With n0 = 100, a player with 100 matches keeps half their distance.
    assert shrink_rating(1800.0, 100, 100) == pytest.approx(1650.0)
    # A deep record barely moves; a thin one moves a lot.
    assert shrink_rating(1800.0, 900, 100) == pytest.approx(1770.0)
    assert shrink_rating(1800.0, 10, 100) == pytest.approx(1527.3, abs=0.1)
    # It pulls from both directions, and an unknown depth is left alone.
    assert shrink_rating(1200.0, 100, 100) == pytest.approx(1350.0)
    assert shrink_rating(1800.0, None, 100) == 1800.0


def test_each_tour_gets_its_own_fitted_parameters(monkeypatch):
    """The two records differ fivefold in depth, so the two fits differ too."""
    from app.services.winprob import _params
    from app.services.winprob.elo import own_params
    base = dict(_params._PARAMS["own"])
    base["by_tour"] = {"atp": {"k_rank": 0.05, "shrink_n0": 0}, "wta": {"k_rank": 0.14, "shrink_n0": 100}}
    monkeypatch.setitem(_params._PARAMS, "own", base)
    assert own_params("atp")["shrink_n0"] == 0
    assert own_params("wta")["shrink_n0"] == 100
    assert own_params("wta")["k_rank"] > own_params("atp")["k_rank"]
    # An unknown tour falls back to the shared defaults rather than failing.
    assert own_params(None)["k_logit"] == base["k_logit"]


def test_shrinkage_moves_a_thin_players_probability_toward_a_coin_toss(monkeypatch):
    from app.services.winprob import _params
    base = dict(_params._PARAMS["own"])
    base.update({"fitted": True, "surface_w": 0.5, "k_logit": 0.75, "k_rank": 0.0})
    base["by_tour"] = {"wta": {"shrink_n0": 100}, "atp": {"shrink_n0": 0}}
    monkeypatch.setitem(_params._PARAMS, "own", base)
    # The same two ratings, one pair deep and one pair thin.
    deep = {1: (None, None, None, (1900.0, 1900.0, 800)), 2: (None, None, None, (1600.0, 1600.0, 800))}
    thin = {1: (None, None, None, (1900.0, 1900.0, 15)), 2: (None, None, None, (1600.0, 1600.0, 15))}
    p_deep = DrawOdds(deep, "Hard", 3, {}, ("d",)); p_deep.tour = "wta"
    p_thin = DrawOdds(thin, "Hard", 3, {}, ("t",)); p_thin.tour = "wta"
    assert p_deep.pair_prob(1, 2) > p_thin.pair_prob(1, 2) > 0.5
    # On the men's side nothing is shrunk, so depth changes nothing.
    a = DrawOdds(deep, "Hard", 3, {}, ("a",)); a.tour = "atp"
    b = DrawOdds(thin, "Hard", 3, {}, ("b",)); b.tour = "atp"
    assert a.pair_prob(1, 2) == pytest.approx(b.pair_prob(1, 2))


def test_time_off_decays_a_rating_toward_the_mean():
    from app.services.winprob.elo import layoff_factor
    # Inside the grace period an absence costs nothing: an off-season is not an injury.
    assert layoff_factor(30, 90, 60) == 1.0
    assert layoff_factor(60, 90, 60) == 1.0
    # Beyond it the rating decays, and by tau days past grace it keeps 1/e.
    assert layoff_factor(150, 90, 60) == pytest.approx(1 / 2.71828, abs=1e-4)
    assert layoff_factor(400, 90, 60) == pytest.approx(0.0229, abs=1e-3)
    # Switched off, or unknown, changes nothing.
    assert layoff_factor(400, 0, 60) == 1.0
    assert layoff_factor(None, 90, 60) == 1.0


def test_a_returning_player_is_rated_more_cautiously(monkeypatch):
    from app.services.winprob import _params
    base = dict(_params._PARAMS["own"])
    base.update({"fitted": True, "layoff_grace": 60})
    base["by_tour"] = {"wta": {"surface_w": 0.5, "k_logit": 0.75, "k_rank": 0.0,
                               "shrink_n0": 0.0, "layoff_tau": 365.0}}
    monkeypatch.setitem(_params._PARAMS, "own", base)
    # (overall, surface, matches, days since last played)
    fresh = {1: (None, None, None, (1900.0, 1900.0, 500, 7)), 2: (None, None, None, (1600.0, 1600.0, 500, 7))}
    rusty = {1: (None, None, None, (1900.0, 1900.0, 500, 300)), 2: (None, None, None, (1600.0, 1600.0, 500, 7))}
    a = DrawOdds(fresh, "Hard", 3, {}, ("f",)); a.tour = "wta"
    b = DrawOdds(rusty, "Hard", 3, {}, ("r",)); b.tour = "wta"
    # The favourite has been away ten months: less of their rating survives,
    # but she is still the favourite — the decay doubts a rating, it does not
    # throw it away. That is why tau is 365 and not the 90 that fitted the
    # same: at 90 she would come back an underdog to a journeyman.
    assert 0.5 < b.pair_prob(1, 2) < a.pair_prob(1, 2)


def test_one_rating_pass_per_tour_with_its_own_k_schedule():
    from app.services.history.ratings import pass_config
    atp, wta = pass_config("atp"), pass_config("wta")
    assert atp["k0"] != wta["k0"] or atp["k_decay"] != wta["k_decay"]
    # An explicit cfg still wins, which is what the fitting script relies on.
    assert pass_config("atp", {"k0": 1.0})["k0"] == 1.0
    # An unknown tour gets the shared defaults rather than a KeyError.
    assert pass_config("doubles")["k0"] > 0


def test_sampling_reaches_where_enumeration_cannot(monkeypatch):
    """Past fifteen undecided matches the chances are sampled, and the range
    comes back empty rather than understated."""
    import random
    from app.services.scoring import (CHANCES_MAX_UNDECIDED, chances_available,
                                      chances_sampled, finish_range_available)
    from tests.test_finish_range import _bracket

    r32_done = _bracket(32, decided_r1=16)          # 15 undecided: both exact
    assert finish_range_available(r32_done) and chances_available(r32_done)
    assert not chances_sampled(r32_done)

    r64 = _bracket(64, decided_r1=0)                # 63 undecided: chances only
    assert not finish_range_available(r64)
    assert chances_available(r64) and chances_sampled(r64)

    rng = random.Random(2)
    ms = _bracket(32, decided_r1=8, rng=rng)        # 23 undecided
    picks = {u: _random_picks(ms, 32, rng) for u in range(1, 6)}
    banked = _banked(ms, {1: 1, 2: 2, 3: 4, 4: 8, 5: 12}, picks)
    pts = {1: 1, 2: 2, 3: 4, 4: 8, 5: 12}
    odds = _odds(range(1, 33))
    # Without sampling it refuses; with it, it answers.
    assert finish_range(ms, pts, 5, banked, picks, odds) is None
    out = finish_range(ms, pts, 5, banked, picks, odds, sample=True)
    assert out is not None and len(out) == 5
    for best, worst, pw, pp in out.values():
        assert best is None and worst is None        # an extreme is not sampled
        assert 0.0 <= pw <= pp <= 1.0
    assert sum(v[2] for v in out.values()) == pytest.approx(1.0, abs=0.02)
    # Deterministic: the same state gives the same number, every time.
    again = finish_range(ms, pts, 5, banked, picks, odds, sample=True)
    assert again == out
    # And sampling without odds has nothing to draw from.
    assert finish_range(ms, pts, 5, banked, picks, None, sample=True) is None


def test_a_sampled_chance_matches_the_exact_one():
    """Where both can be computed they must agree to within sampling error."""
    import random
    rng = random.Random(4)
    ms = _bracket(16, decided_r1=4, rng=rng)
    picks = {u: _random_picks(ms, 16, rng) for u in range(1, 8)}
    banked = _banked(ms, PTS16, picks)
    odds = _odds(range(1, 17))
    exact = finish_range(ms, PTS16, 4, banked, picks, odds)
    drawn = finish_range(ms, PTS16, 4, banked, picks, odds, sample=True)
    for u in exact:
        assert drawn[u][2] == pytest.approx(exact[u][2], abs=0.01)
        assert drawn[u][3] == pytest.approx(exact[u][3], abs=0.01)
