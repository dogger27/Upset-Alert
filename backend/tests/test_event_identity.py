"""A name and a year are not an event. A week is.

The migration that created the tournaments table grouped draws on name and
year alone, and two different tournaments can share a city's name in one
year. Four did in 2026 — Hong Kong (January ATP, November WTA), Hamburg,
Stuttgart, Tokyo — and the January Hong Kong event reappeared under ACTIVE
in September because it shared a row with a November draw (owner,
2026-09-21).
"""
from datetime import date

from app.services.events import SAME_EVENT_DAYS, _plays_together, split_plan


class D:
    """Only the fields the judgement reads."""

    def __init__(self, id, start, end=None):
        self.id = id
        self.start_date = start
        self.end_date = end or (start + date.resolution * 6 if start else None)


def test_a_combined_week_is_one_event():
    """The men's and women's halves start together or a day apart."""
    assert _plays_together(D(1, date(2026, 9, 21)), D(2, date(2026, 9, 21))) is True
    assert _plays_together(D(1, date(2026, 9, 21)), D(2, date(2026, 9, 22))) is True


def test_a_slam_qualifying_lead_is_still_one_event():
    """Ten days absorbs a draw dated from its qualifying week."""
    assert _plays_together(D(1, date(2026, 5, 24)), D(2, date(2026, 5, 18))) is True


def test_two_months_apart_is_two_events():
    assert _plays_together(D(1, date(2026, 1, 5)), D(2, date(2026, 11, 2))) is False
    assert _plays_together(D(1, date(2026, 5, 18)), D(2, date(2026, 7, 20))) is False


def test_the_nearest_real_pair_still_splits():
    """Tokyo was the closest of the four: 30 September against 19 October."""
    assert _plays_together(D(1, date(2026, 9, 30)), D(2, date(2026, 10, 19))) is False


def test_nothing_to_compare_is_not_togetherness():
    """A draw with no dates is not evidence that it belongs with another."""
    assert _plays_together(D(1, None), D(2, date(2026, 9, 21))) is False


# ── the split the migration performs ──────────────────────────────────────

def test_hong_kong_splits_into_two_events():
    jan, nov = D(3, date(2026, 1, 5)), D(155, date(2026, 11, 2))
    groups = split_plan([nov, jan])            # order should not matter
    assert [[d.id for d in g] for g in groups] == [[3], [155]]


def test_a_real_combined_event_is_left_alone():
    groups = split_plan([D(1, date(2026, 9, 21)), D(2, date(2026, 9, 21))])
    assert len(groups) == 1
    assert sorted(d.id for d in groups[0]) == [1, 2]


def test_three_events_in_one_row_come_out_as_three():
    groups = split_plan([D(1, date(2026, 1, 5)), D(2, date(2026, 6, 1)), D(3, date(2026, 11, 2))])
    assert [[d.id for d in g] for g in groups] == [[1], [2], [3]]


def test_an_undated_draw_stays_with_the_original_row():
    """It cannot be placed, and inventing a place for it is worse."""
    groups = split_plan([D(1, date(2026, 1, 5)), D(2, None), D(3, date(2026, 11, 2))])
    assert [d.id for d in groups[0]] == [1, 2]
    assert [d.id for d in groups[1]] == [3]


def test_nothing_in_nothing_out():
    assert split_plan([]) == []
    assert split_plan([D(1, None)]) == [[]] or [d.id for d in split_plan([D(1, None)])[0]] == [1]


def test_the_window_is_the_one_the_service_publishes():
    """The migration script inlines this number; they must not drift."""
    assert SAME_EVENT_DAYS == 10
