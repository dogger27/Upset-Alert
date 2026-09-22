"""When answers stop describing the final they were given for.

The tiebreak questions are about two named players — how many aces THE
CHAMPION hits, how long the final lasts — so changing a pick that reaches the
final invalidates the answers. Nothing said so: the reader's numbers silently
stopped describing their own bracket (owner, 2026-09-22).

The guess now records the final it answered, and this is the rule the clients
colour their way in with. It is deliberately reluctant: a false positive is a
warning on somebody's screen about work they have already done.
"""
from app.models.final_guess import answers_are_stale


class G:
    """Only the two fields the rule reads."""

    def __init__(self, a, b):
        self.final_a_entry_id, self.final_b_entry_id = a, b


def test_the_same_final_is_not_stale():
    assert answers_are_stale(G(7, 9), 7, 9, locked=False) is False


def test_a_different_finalist_is_stale():
    assert answers_are_stale(G(7, 9), 7, 12, locked=False) is True
    assert answers_are_stale(G(7, 9), 3, 9, locked=False) is True
    assert answers_are_stale(G(7, 9), 3, 12, locked=False) is True


def test_swapping_who_WINS_the_final_is_stale():
    """The same two players, the other way round. The aces question is about
    the CHAMPION, so this is a different question — order is part of the fact,
    and comparing the pair as a set would miss it."""
    assert answers_are_stale(G(7, 9), 9, 7, locked=False) is True


def test_no_guess_is_never_stale():
    assert answers_are_stale(None, 7, 9, locked=False) is False


def test_a_row_from_before_the_columns_existed_is_not_stale():
    """Nullable on purpose: every guess saved before 2026-09-22 has no answer
    here. We do not know what it answered, and reddening every legacy row is
    crying wolf on rows nobody has touched."""
    assert answers_are_stale(G(None, None), 7, 9, locked=False) is False


def test_a_locked_draw_is_never_stale():
    """Nothing can be done about it once picks are locked, so saying so is
    only noise — and the answers still scored the final they were given for."""
    assert answers_are_stale(G(7, 9), 3, 12, locked=True) is False


def test_an_unpickable_final_is_answered_against_nothing():
    """predicted_finalists returns None either side until the bracket reaches
    that far. Going from a known finalist to none IS a change — the answers
    were given about somebody."""
    assert answers_are_stale(G(7, 9), None, None, locked=False) is True
    # And a guess stamped with no finalists (the bracket was empty when it was
    # saved) is not stale until one is known.
    assert answers_are_stale(G(None, 9), 7, 9, locked=False) is False
