"""Who the reader's own bracket sends to the final.

The tiebreak questions are about the champion and the runner-up, and they were
read straight off the row for the final: `picks[final_match]`. A reader who
changed an earlier pick — sending their old champion out in the quarters —
still had that player named as the champion, because the final's row still said
so (owner, 2026-09-22). It could even name a champion who appears in NEITHER
semi-final, which is not a bracket anyone picked.

The semis are the authority on who the final is; the final's pick only decides
which of those two lifts the trophy.
"""
from app.routers.tournaments import predicted_finalists

NUM_ROUNDS = 5          # a 32 draw: semis are round 4, the final round 5


class M:
    def __init__(self, id, round_number, match_number, is_bye=False):
        self.id, self.round_number, self.match_number = id, round_number, match_number
        self.is_bye = is_bye


MATCHES = [M(41, 4, 1), M(42, 4, 2), M(50, 5, 1)]


def test_a_coherent_bracket_answers_both():
    picks = {41: 7, 42: 9, 50: 7}
    assert predicted_finalists(picks, MATCHES, NUM_ROUNDS) == (7, 9)
    # The other way round: the runner-up is whichever semi winner is not the
    # champion, not whichever semi came first.
    assert predicted_finalists({41: 7, 42: 9, 50: 9}, MATCHES, NUM_ROUNDS) == (9, 7)


def test_a_champion_who_no_longer_reaches_the_final_is_not_the_champion():
    """THE BUG. The reader moved a quarter-final pick, so 7 never gets to the
    semi — but the row for the final still names 7."""
    picks = {41: 3, 42: 9, 50: 7}
    assert predicted_finalists(picks, MATCHES, NUM_ROUNDS) == (None, None)


def test_no_final_pick_yet_is_no_champion():
    assert predicted_finalists({41: 7, 42: 9}, MATCHES, NUM_ROUNDS) == (None, None)


def test_one_semi_picked_is_not_a_final():
    """Half a final is not a final: with one slot unknown there is no pair to
    ask two questions about."""
    assert predicted_finalists({41: 7, 50: 7}, MATCHES, NUM_ROUNDS) == (7, None)
    assert predicted_finalists({42: 9, 50: 9}, MATCHES, NUM_ROUNDS) == (9, None)


def test_an_empty_bracket_answers_nothing():
    assert predicted_finalists({}, MATCHES, NUM_ROUNDS) == (None, None)
    assert predicted_finalists({}, [], NUM_ROUNDS) == (None, None)


def test_byes_are_not_the_final():
    """A bye carries a match_number too, and taking one for the final would
    read the wrong row."""
    with_bye = [M(41, 4, 1), M(42, 4, 2), M(99, 5, 1, is_bye=True), M(50, 5, 1)]
    assert predicted_finalists({41: 7, 42: 9, 50: 7}, with_bye, NUM_ROUNDS) == (7, 9)


def test_both_semis_picked_the_same_player():
    """Not a bracket that can happen, but it must not answer with a final
    between somebody and themselves."""
    assert predicted_finalists({41: 7, 42: 7, 50: 7}, MATCHES, NUM_ROUNDS) == (7, None)
