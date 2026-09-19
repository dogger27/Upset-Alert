"""THE TIEBREAK IS THE FINAL (owner, 2026-09-18; sets added 2026-09-19):
points, then closest on how many SETS the final went, then on the champion's
aces, then on minutes; no answer sorts last on that key among level brackets;
before the final is played, level is level.

A guess is (sets, aces, minutes) throughout. Sets can be None on its own — a
guess stored before that question existed — and must not read as a perfect
answer.
"""
from types import SimpleNamespace as NS

from app.services.final_tiebreak import apply, diffs_for
from app.services.scoring import UserScore, rank_users


def _s(uid, pts):
    return UserScore(user_id=uid, total_points=pts, correct_count=0)


def test_diffs_are_absolute_and_none_without_a_guess_or_a_final():
    assert diffs_for((2, 12, 130), 15, 120, 3) == (1, 3, 10)
    assert diffs_for(None, 15, 120, 3) == (None, None, None)
    assert diffs_for((2, 12, 130), None, None, None) == (None, None, None)


def test_a_guess_older_than_the_sets_question_has_no_sets_gap():
    # Stored before 2026-09-19, so its sets answer is null. It must sort last
    # on that key rather than looking like a perfect call.
    assert diffs_for((None, 12, 130), 15, 120, 3) == (None, 3, 10)


def test_level_brackets_are_ordered_by_aces_then_minutes_then_no_answer_last():
    # Every bracket here called the sets right, so the tie falls through to
    # aces and then to minutes exactly as it did before sets existed.
    draw = NS(final_winner_aces=15, final_duration_min=120, final_sets=3)
    scores = {1: _s(1, 27), 2: _s(2, 27), 3: _s(3, 27), 4: _s(4, 26), 5: _s(5, 27)}
    guesses = {1: (3, 10, 120), 2: (3, 14, 200), 3: (3, 16, 110), 5: (3, 14, 121)}   # 4 never answered
    apply(scores, draw, guesses)
    order = [s.user_id for s in rank_users(list(scores.values()), 5)]
    assert scores[5].tie_aces_diff == 1 and scores[5].tie_minutes_diff == 1
    assert scores[3].tie_aces_diff == 1 and scores[3].tie_minutes_diff == 10
    assert scores[2].tie_aces_diff == 1 and scores[2].tie_minutes_diff == 80
    assert order == [5, 3, 2, 1, 4]        # 1 is 5 aces off; 4 has fewer points


def test_SETS_is_asked_first_and_settles_the_tie_before_aces():
    """The owner's order (2026-09-19). A bracket that called a straight-sets
    final beats one that was nearer on aces but wrong about the sets."""
    draw = NS(final_winner_aces=15, final_duration_min=120, final_sets=2)
    scores = {1: _s(1, 27), 2: _s(2, 27)}
    #        sets  aces  minutes          sets gap   aces gap
    guesses = {1: (2, 4, 200),     # right on sets, 11 aces out
               2: (3, 15, 120)}    # wrong on sets, perfect on the other two
    apply(scores, draw, guesses)
    assert (scores[1].tie_sets_diff, scores[1].tie_aces_diff) == (0, 11)
    assert (scores[2].tie_sets_diff, scores[2].tie_aces_diff) == (1, 0)
    assert [x.user_id for x in rank_users(list(scores.values()), 5)] == [1, 2]


def test_before_the_final_nothing_is_stamped_and_points_alone_order():
    draw = NS(final_winner_aces=None, final_duration_min=None, final_sets=None)
    scores = {1: _s(1, 27), 2: _s(2, 27)}
    apply(scores, draw, {1: (2, 10, 120), 2: (3, 15, 120)})
    assert scores[1].tie_aces_diff is None and scores[2].tie_aces_diff is None
    assert scores[1].tiebreak_key() == scores[2].tiebreak_key()


def test_a_bracket_that_never_answered_holds_the_default():
    # Owner, 2026-09-18: no click means you chose last year's average, so you
    # are separable like everyone else rather than sorted last.
    draw = NS(final_winner_aces=8, final_duration_min=100, final_sets=2)
    scores = {1: _s(1, 27), 2: _s(2, 27), 3: _s(3, 27)}
    apply(scores, draw, {1: (2, 8, 100), 3: (3, 20, 200)}, default=(2, 6, 95))
    assert (scores[1].tie_aces_diff, scores[1].tie_minutes_diff) == (0, 0)     # exact
    assert (scores[2].tie_aces_diff, scores[2].tie_minutes_diff) == (2, 5)     # the default
    assert scores[2].tie_sets_diff == 0                                        # …including its sets
    assert (scores[3].tie_aces_diff, scores[3].tie_minutes_diff) == (12, 100)  # a bad guess
    assert [x.user_id for x in rank_users(list(scores.values()), 5)] == [1, 2, 3]


def test_without_a_default_a_silent_bracket_still_sorts_last():
    draw = NS(final_winner_aces=8, final_duration_min=100, final_sets=2)
    scores = {1: _s(1, 27), 2: _s(2, 27)}
    apply(scores, draw, {1: (2, 20, 200)}, default=None)
    assert scores[2].tie_sets_diff is None and scores[2].tie_aces_diff is None
    assert [x.user_id for x in rank_users(list(scores.values()), 5)] == [1, 2]
