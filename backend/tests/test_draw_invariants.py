"""The draw-lifecycle law, tested against the faults it was written for.

Every case below is a real production state from the week of 2026-09-21, when
the owner asked to "stop babysitting these constant bugs where draws change
their status as we progress through the weeks". Each of those bugs was silent:
nothing raised, so nothing logged, so the self-heal watcher never saw one and
the owner was the only detector. These tests are the record of what each check
is for — change a threshold and the incident it stops catching should be
visible here.
"""
from datetime import date

import pytest

from app.services.draw_invariants import (
    ABSOLUTE_MAX_SPAN_DAYS,
    CATEGORY_SPAN_DAYS,
    UNFINISHED_GRACE_DAYS,
    completed_with_unplayed_final,
    dates_out_of_order,
    duration_outside_envelope,
    end_date_behind_play,
    entries_without_draw_rank,
    not_completed_after_its_end,
    row_holds_two_events,
    not_completed_after_its_end,
)


class D:
    """Only the fields the judgement reads."""

    def __init__(self, id, start, end=None):
        self.id = id
        self.start_date = start
        self.end_date = end


class E:
    """A draw entry, as far as the rank check is concerned."""

    def __init__(self, name, seed=None, ranking=None):
        self.name = name
        self.seed = seed
        self.ranking = ranking


# ── end_date_behind_play: SP Open's postponed final ───────────────────────

def test_a_final_played_after_the_calendars_last_day_is_a_fault():
    """"Why does it say SP Open ends Sept 20 if the final is scheduled for
    3pm on the 21st?" — owner, 2026-09-21."""
    why = end_date_behind_play(date(2026, 9, 20), date(2026, 9, 21))
    assert why and "after end_date" in why and "1d" in why


def test_play_on_the_last_day_is_lawful():
    assert end_date_behind_play(date(2026, 9, 21), date(2026, 9, 21)) is None


def test_play_before_the_last_day_is_lawful():
    assert end_date_behind_play(date(2026, 9, 21), date(2026, 9, 19)) is None


@pytest.mark.parametrize("end,play", [(None, date(2026, 9, 21)),
                                      (date(2026, 9, 21), None),
                                      (None, None)])
def test_nothing_to_compare_is_not_a_fault(end, play):
    """A draw with no order of play is the ordinary case, not a violation."""
    assert end_date_behind_play(end, play) is None


# ── dates_out_of_order ────────────────────────────────────────────────────

def test_ending_before_it_starts():
    why = dates_out_of_order(date(2026, 9, 21), date(2026, 9, 14))
    assert why and "precedes" in why


def test_a_single_day_event_is_lawful():
    d = date(2026, 9, 21)
    assert dates_out_of_order(d, d) is None


# ── duration_outside_envelope: China Open's 12-day ATP 500 ────────────────

def test_an_atp_500_cannot_run_twelve_days():
    """The infobox names a range per TOUR; the parser knew only "(men)" and
    "(women)", so the ATP 500 took the WTA 1000's end date (2026-09-21)."""
    why = duration_outside_envelope("ATP 500", date(2026, 9, 30), date(2026, 10, 11))
    assert why and "11d" in why and "ATP 500" in why


def test_the_wta_1000_half_of_that_same_event_is_lawful():
    """Twelve days in Beijing is real. The check must not call it a fault."""
    assert duration_outside_envelope(
        "WTA 1000", date(2026, 9, 30), date(2026, 10, 11)) is None


def test_every_real_span_in_production_is_lawful():
    """The envelopes were derived from the 111 draws that existed on
    2026-09-21 — the observed range per category, widened by a day at each
    end. Anything inside those observations must stay lawful, or the check
    will bury its own signal in false positives."""
    observed = {"ATP 250": (5, 7), "ATP 500": (5, 6), "ATP 1000": (6, 11),
                "WTA 250": (5, 6), "WTA 500": (5, 7), "WTA 1000": (5, 11),
                "Grand Slam": (7, 14)}
    for category, (lo, hi) in observed.items():
        for span in range(lo, hi + 1):
            start = date(2026, 3, 2)
            assert duration_outside_envelope(
                category, start, date.fromordinal(start.toordinal() + span)
            ) is None, f"{category} {span}d wrongly flagged"


def test_a_slams_fortnight_is_lawful_and_a_month_is_not():
    assert duration_outside_envelope(
        "Grand Slam", date(2026, 8, 30), date(2026, 9, 13)) is None
    assert duration_outside_envelope(
        "Grand Slam", date(2026, 8, 30), date(2026, 10, 13)) is not None


def test_an_unknown_category_still_has_a_ceiling():
    """No category we have never seen gets a free pass at any length."""
    start = date(2026, 3, 2)
    over = date.fromordinal(start.toordinal() + ABSOLUTE_MAX_SPAN_DAYS + 1)
    assert duration_outside_envelope("ATP 9000", start, over) is not None
    assert duration_outside_envelope(None, start, over) is not None


def test_no_dates_no_judgement():
    assert duration_outside_envelope("ATP 250", None, date(2026, 9, 21)) is None
    assert duration_outside_envelope("ATP 250", date(2026, 9, 21), None) is None


def test_the_envelopes_cover_every_category_in_the_table():
    """A category present in production but missing here silently falls back
    to 0..15, which is not a check."""
    for category in ("ATP 250", "ATP 500", "ATP 1000",
                     "WTA 250", "WTA 500", "WTA 1000", "Grand Slam"):
        assert category in CATEGORY_SPAN_DAYS


# ── not_completed_after_its_end ──────────────────────────────────────────

def test_a_draw_the_scrapers_never_finished():
    """Walked against the real computed_status: a status left at anything but
    'completed' reads 'active' until 14 days past START, which for a 6-day
    week is eight days after the final was played."""
    why = not_completed_after_its_end("active", date(2026, 9, 19), date(2026, 9, 22))
    assert why and "3d after end_date" in why


@pytest.mark.parametrize("status", ["active", "upcoming", "open", None])
def test_every_unfinished_status_counts_not_just_active(status):
    """The earlier check asked only about 'active' and so missed the identical
    eight phantom days in a draw abandoned at 'upcoming'."""
    assert not_completed_after_its_end(status, date(2026, 9, 1), date(2026, 9, 21))


def test_a_finished_draw_is_lawful():
    assert not_completed_after_its_end(
        "completed", date(2026, 9, 19), date(2026, 9, 30)) is None


def test_on_its_last_day_it_is_lawful():
    assert not_completed_after_its_end(
        "active", date(2026, 9, 21), date(2026, 9, 21)) is None


def test_a_late_result_gets_its_grace():
    """A result can land a day or two late; that is not an abandoned scrape."""
    inside = date(2026, 9, 21 + UNFINISHED_GRACE_DAYS)
    assert not_completed_after_its_end("active", date(2026, 9, 21), inside) is None


def test_no_end_date_no_judgement():
    assert not_completed_after_its_end("active", None, date(2026, 9, 21)) is None


# ── completed_with_unplayed_final ─────────────────────────────────────────

def test_retired_with_the_final_undecided():
    why = completed_with_unplayed_final("completed", False)
    assert why and "no winner" in why


def test_retired_properly_is_lawful():
    assert completed_with_unplayed_final("completed", True) is None


def test_a_draw_with_no_bracket_is_not_accused():
    """finals unknown (no last-round match row at all) is not a claim."""
    assert completed_with_unplayed_final("completed", None) is None


def test_an_active_draw_may_have_an_unplayed_final():
    assert completed_with_unplayed_final("active", False) is None


# ── row_holds_two_events: Hong Kong ──────────────────────────────────────

def test_one_row_holding_january_and_november():
    """"ATP Hong kong open is showing active as an atp draw with January
    dates. Isn't this a WTA event at the end of October? WTF is going on???"
    — owner, 2026-09-21."""
    why = row_holds_two_events([D(3, date(2026, 1, 5)), D(155, date(2026, 11, 2))])
    assert why and "2 events" in why


def test_a_real_combined_week_is_lawful():
    assert row_holds_two_events([D(1, date(2026, 9, 21)),
                                 D(2, date(2026, 9, 21))]) is None


def test_the_nearest_real_pair_still_reads_as_two():
    """Japan Open was the closest of the four: Tokyo 30 September against
    Osaka 19 October."""
    assert row_holds_two_events([D(149, date(2026, 9, 30)),
                                 D(153, date(2026, 10, 19))]) is not None


def test_a_lone_draw_is_lawful():
    assert row_holds_two_events([D(1, date(2026, 9, 21))]) is None


def test_an_undated_draw_is_not_evidence_of_conflation():
    assert row_holds_two_events([D(1, date(2026, 9, 21)), D(2, None)]) is None


# ── entries_without_draw_rank ────────────────────────────────────────────

def test_an_entry_with_neither_seed_nor_ranking():
    """"Several players are still missing their inferred draw rank."
    — owner, 2026-09-21. The badge is the rank WITHIN the draw: seeds keep
    their seed, everyone else is ordered by world ranking. Neither means no
    badge at all."""
    why = entries_without_draw_rank([E("A Seed", seed=1, ranking=4),
                                     E("Ranked Player", ranking=88),
                                     E("Nobody Knows")])
    assert why and "1 entry" in why and "Nobody Knows" in why


def test_a_seed_with_no_world_ranking_is_lawful():
    """A seed number is a rank in this draw on its own."""
    assert entries_without_draw_rank([E("Qualifier Seed", seed=5)]) is None


def test_a_ranking_with_no_seed_is_lawful():
    assert entries_without_draw_rank([E("Unseeded", ranking=120)]) is None


def test_byes_are_not_players():
    assert entries_without_draw_rank([E("Bye"), E("bye"), E("")]) is None


def test_the_detail_names_at_most_six_and_says_there_are_more():
    why = entries_without_draw_rank([E(f"Player {i}") for i in range(9)])
    assert why and "9 entries" in why and why.endswith("…")


def test_a_full_draw_of_ranked_players_is_lawful():
    assert entries_without_draw_rank(
        [E(f"Player {i}", ranking=i + 1) for i in range(32)]) is None
