"""The game-level live model: it must reduce to the set model, stay
antisymmetric, and move the way a scoreboard moves."""
import pytest

from app.services.winprob import live_win_prob, live_win_prob_games
from app.services.winprob.games import game_prob_from_set_prob, set_win_prob_from_games
from app.services.winprob.sets import set_prob_from_match_prob


@pytest.mark.parametrize("p", [0.5, 0.62, 0.81, 0.95])
@pytest.mark.parametrize("best_of", [3, 5])
def test_no_games_played_is_the_set_model(p, best_of):
    for sx, sy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        assert live_win_prob_games(p, sx, sy, 0, 0, best_of=best_of) == pytest.approx(
            live_win_prob(p_match=p, sets_x=sx, sets_y=sy, best_of=best_of), abs=1e-9)


def test_pre_match_number_survives_the_round_trip():
    # p_match -> p_set -> p_game -> set from 0-0 -> match from 0-0 == p_match
    for p in (0.55, 0.7, 0.9):
        assert live_win_prob_games(p, 0, 0, 0, 0) == pytest.approx(p, abs=1e-9)
        p_set = set_prob_from_match_prob(p, 3)
        g = game_prob_from_set_prob(p_set)
        assert set_win_prob_from_games(g, 0, 0, p_set) == pytest.approx(p_set, abs=1e-9)


def test_antisymmetric_from_any_scoreboard():
    for p, sx, sy, gx, gy, tb in ((0.65, 0, 1, 5, 2, False), (0.4, 1, 1, 6, 6, True), (0.8, 1, 0, 2, 5, False)):
        a = live_win_prob_games(p, sx, sy, gx, gy, tb)
        b = live_win_prob_games(1 - p, sy, sx, gy, gx, tb)
        assert a + b == pytest.approx(1.0, abs=1e-9)


def test_games_move_it_the_right_way():
    p = 0.6
    up = live_win_prob_games(p, 0, 0, 5, 2)
    level = live_win_prob_games(p, 0, 0, 3, 3)
    down = live_win_prob_games(p, 0, 0, 2, 5)
    assert down < level < up
    assert level == pytest.approx(p, abs=0.03)          # 3-3 is nearly a fresh set
    # A set down but serving for the second is roughly back to level terms.
    assert 0.45 < live_win_prob_games(p, 0, 1, 5, 2) < 0.7
    # Match point converted is not a probability any more.
    assert live_win_prob_games(p, 1, 0, 6, 4) == pytest.approx(1.0)
    assert live_win_prob_games(p, 2, 1, 0, 0, best_of=5) < 1.0
    assert live_win_prob_games(p, 3, 1, 0, 0, best_of=5) == 1.0


def test_tiebreak_is_the_set_probability():
    p = 0.7
    p_set = set_prob_from_match_prob(p, 3)
    p_tb = live_win_prob_games(p, 0, 0, 6, 6, in_tiebreak=True)
    # From 0-0 sets, winning this set at p_set then needing one more...
    expected = p_set * live_win_prob(p_match=p, sets_x=1) + (1 - p_set) * live_win_prob(p_match=p, sets_y=1)
    assert p_tb == pytest.approx(expected, abs=1e-9)


def test_finished_set_reads_one_or_zero():
    g = 0.55
    assert set_win_prob_from_games(g, 6, 4, 0.5) == 1.0
    assert set_win_prob_from_games(g, 4, 6, 0.5) == 0.0
    assert set_win_prob_from_games(g, 7, 6, 0.5) == 1.0
    assert set_win_prob_from_games(g, 7, 5, 0.5) == 1.0
    assert 0.0 < set_win_prob_from_games(g, 6, 5, 0.5) < 1.0     # 6-5 is still a set
