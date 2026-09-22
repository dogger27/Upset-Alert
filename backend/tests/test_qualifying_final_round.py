"""Which Qn the qualifying final is.

Sofascore numbers the early qualifying rounds and then calls the last one
"Qualification Final" — with `round: 250`, a sentinel rather than a number,
where "Qualification Round 1" carries `round: 1`. So every qualifying final
reached the schedule as a bare "Q" (owner, 2026-09-22: "It needs to show which
round of qualifying it is").

The number is one past the highest numbered round the season has. That is
counted from the whole season's events, because a day's document holds only
that day and the Final's day has nothing to count from — the round it follows
was played yesterday.
"""
from app.services.sofa_schedule import (
    qualifying_final_round, round_token,
)


def ev(slug):
    return {"roundInfo": {"slug": slug, "name": slug.replace("-", " ").title()}}


def test_a_tour_event_runs_one_round_then_the_final():
    """Chengdu, 2026: eight Qualification Round 1 matches, then four in the
    Final. The Final is Q2."""
    evs = [ev("qualification-round-1")] * 8 + [ev("qualification-final")] * 4
    assert qualifying_final_round(evs) == 2


def test_a_slam_runs_two_then_the_final():
    evs = ([ev("qualification-round-1")] * 32 + [ev("qualification-round-2")] * 16
           + [ev("qualification-final")] * 8)
    assert qualifying_final_round(evs) == 3


def test_the_main_draw_does_not_count():
    evs = [ev("round-of-32"), ev("quarterfinal"), ev("final"),
           ev("qualification-round-1"), ev("qualification-final")]
    assert qualifying_final_round(evs) == 2


def test_no_final_means_nothing_to_number():
    assert qualifying_final_round([ev("qualification-round-1")]) is None
    assert qualifying_final_round([ev("round-of-32")]) is None
    assert qualifying_final_round([]) is None
    assert qualifying_final_round(None) is None


def test_a_final_with_nothing_to_count_from_stays_unnumbered():
    """A fetch that caught only the last day. Guessing "Q2" here would name a
    round that was never played at a Slam — a wrong number is worse than a
    vague one, so the generic Q stands."""
    assert qualifying_final_round([ev("qualification-final")]) is None


def test_events_with_no_round_info_are_ignored():
    assert qualifying_final_round([{}, {"roundInfo": None},
                                   ev("qualification-round-1"),
                                   ev("qualification-final")]) == 2


# ── the token the number becomes ─────────────────────────────────────────

def test_a_numbered_qualifying_round_reads_as_Qn():
    assert round_token("Qualification Round 1") == "Q1"
    assert round_token("Qualification Round 2") == "Q2"
    # Read rather than listed, so the map cannot run out at Q3.
    assert round_token("Qualification Round 4") == "Q4"


def test_the_main_draw_tokens_are_unchanged():
    assert round_token("Final") == "F"
    assert round_token("Round of 128") == "R128"
    assert round_token("Quarterfinal") == "QF"


def test_an_unnumbered_final_is_still_generic():
    assert round_token("Qualification Final") == "Q"
    assert round_token("Qualification") == "Q"


def test_nothing_known_is_nothing_claimed():
    assert round_token(None) is None
    assert round_token("") is None
    assert round_token("Some round nobody has heard of") is None
