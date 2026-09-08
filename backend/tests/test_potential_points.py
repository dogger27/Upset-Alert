"""potential_points: the best case still open to a bracket."""
from types import SimpleNamespace as NS

from app.services.scoring import potential_points


def _m(id, r, k, p1=None, p2=None, winner=None, bye=False, status=None):
    return NS(id=id, round_number=r, match_number=k, player1_id=p1, player2_id=p2,
              winner_id=winner, is_bye=bye,
              status=status or ("completed" if winner is not None else "scheduled"))


# An 8-draw: lines 1..8, R1 matches 1-4, R2 1-2, F 1. Points 1/2/4.
PTS = {1: 1, 2: 2, 3: 4}
POS = {n: n for n in range(1, 9)}


def test_alive_pick_in_its_half_pays_every_undecided_round():
    ms = [_m(1, 1, 1, 1, 2), _m(2, 1, 2, 3, 4), _m(3, 1, 3, 5, 6), _m(4, 1, 4, 7, 8),
          _m(5, 2, 1), _m(6, 2, 2), _m(7, 3, 1)]
    picks = {1: 1, 2: 3, 3: 5, 4: 7, 5: 1, 6: 5, 7: 1}
    assert potential_points(picks, ms, POS, PTS) == 4 * 1 + 2 * 2 + 4


def test_eliminated_player_pays_nothing_downstream():
    ms = [_m(1, 1, 1, 1, 2, winner=2), _m(2, 1, 2, 3, 4), _m(3, 1, 3, 5, 6), _m(4, 1, 4, 7, 8),
          _m(5, 2, 1), _m(6, 2, 2), _m(7, 3, 1)]
    picks = {1: 1, 2: 3, 3: 5, 4: 7, 5: 1, 6: 5, 7: 1}
    # Line 1 lost R1: its R2 and final picks are dead; the rest stand.
    assert potential_points(picks, ms, POS, PTS) == 3 * 1 + 2


def test_pick_outside_the_matchs_half_is_impossible():
    ms = [_m(5, 2, 1), _m(6, 2, 2), _m(7, 3, 1)]
    # Line 7 cannot reach R2 match 1 (lines 1-4); it can reach the final.
    assert potential_points({5: 7, 7: 7}, ms, POS, PTS) == 4


def test_decided_and_bye_matches_never_count():
    ms = [_m(1, 1, 1, 1, 2, winner=1), _m(2, 1, 2, 3, bye=True), _m(5, 2, 1, status="completed")]
    assert potential_points({1: 1, 2: 3, 5: 1}, ms, POS, PTS) == 0


def test_unknown_line_is_worth_nothing():
    ms = [_m(7, 3, 1)]
    assert potential_points({7: 99}, ms, POS, PTS) == 0
