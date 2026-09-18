"""THE TIEBREAK IS THE FINAL (owner, 2026-09-18): points, then closest on the
champion's aces, then closest on minutes; no answer sorts last among level
brackets; before the final is played, level is level.
"""
from types import SimpleNamespace as NS

from app.services.final_tiebreak import apply, diffs_for
from app.services.scoring import UserScore, rank_users


def _s(uid, pts):
    return UserScore(user_id=uid, total_points=pts, correct_count=0)


def test_diffs_are_absolute_and_none_without_a_guess_or_a_final():
    assert diffs_for((12, 130), 15, 120) == (3, 10)
    assert diffs_for(None, 15, 120) == (None, None)
    assert diffs_for((12, 130), None, None) == (None, None)


def test_level_brackets_are_ordered_by_aces_then_minutes_then_no_answer_last():
    draw = NS(final_winner_aces=15, final_duration_min=120)
    scores = {1: _s(1, 27), 2: _s(2, 27), 3: _s(3, 27), 4: _s(4, 26), 5: _s(5, 27)}
    guesses = {1: (10, 120), 2: (14, 200), 3: (16, 110), 5: (14, 121)}   # 4 never answered
    apply(scores, draw, guesses)
    order = [s.user_id for s in rank_users(list(scores.values()), 5)]
    # 27-pointers: 5 (off by 1 ace, 1 min) beats 2 (1 ace, 80 min); then 3 (1 ace... no: 3 is off by 1 too)
    assert order[0] in (5, 3, 2)
    assert scores[5].tie_aces_diff == 1 and scores[5].tie_minutes_diff == 1
    assert scores[3].tie_aces_diff == 1 and scores[3].tie_minutes_diff == 10
    assert scores[2].tie_aces_diff == 1 and scores[2].tie_minutes_diff == 80
    assert order == [5, 3, 2, 1, 4]        # 1 is 5 aces off; 4 has fewer points


def test_before_the_final_nothing_is_stamped_and_points_alone_order():
    draw = NS(final_winner_aces=None, final_duration_min=None)
    scores = {1: _s(1, 27), 2: _s(2, 27)}
    apply(scores, draw, {1: (10, 120), 2: (15, 120)})
    assert scores[1].tie_aces_diff is None and scores[2].tie_aces_diff is None
    assert scores[1].tiebreak_key() == scores[2].tiebreak_key()


def test_a_bracket_that_never_answered_holds_the_default():
    # Owner, 2026-09-18: no click means you chose last year's average, so you
    # are separable like everyone else rather than sorted last.
    draw = NS(final_winner_aces=8, final_duration_min=100)
    scores = {1: _s(1, 27), 2: _s(2, 27), 3: _s(3, 27)}
    apply(scores, draw, {1: (8, 100), 3: (20, 200)}, default=(6, 95))
    assert (scores[1].tie_aces_diff, scores[1].tie_minutes_diff) == (0, 0)     # exact
    assert (scores[2].tie_aces_diff, scores[2].tie_minutes_diff) == (2, 5)     # the default
    assert (scores[3].tie_aces_diff, scores[3].tie_minutes_diff) == (12, 100)  # a bad guess
    assert [x.user_id for x in rank_users(list(scores.values()), 5)] == [1, 2, 3]


def test_without_a_default_a_silent_bracket_still_sorts_last():
    draw = NS(final_winner_aces=8, final_duration_min=100)
    scores = {1: _s(1, 27), 2: _s(2, 27)}
    apply(scores, draw, {1: (20, 200)}, default=None)
    assert scores[2].tie_aces_diff is None
    assert [x.user_id for x in rank_users(list(scores.values()), 5)] == [1, 2]
