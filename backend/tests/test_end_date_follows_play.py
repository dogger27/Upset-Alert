"""A postponed final moves the tournament's last day.

end_date comes from Wikipedia's calendar — a plan written months ahead — and
the order of play is what the tournament is actually doing. 2026 SP Open
advertised "Sep 15 - 20" with both finals sitting on the 21st after rain
(owner, 2026-09-21), which left computed_status retiring a draw whose final
had not been played.
"""
from datetime import date

import pytest

from app.services.tournament_schedule import adopt_scheduled_end_date


class D:
    """Just the one field the rule reads and writes."""

    def __init__(self, end):
        self.end_date = end


def test_a_final_pushed_to_the_next_day_moves_the_end_date():
    d = D(date(2026, 9, 20))
    assert adopt_scheduled_end_date(d, date(2026, 9, 21)) is True
    assert d.end_date == date(2026, 9, 21)


def test_a_rain_week_still_moves_it():
    """Two days of washout is a real tournament, not a data fault."""
    d = D(date(2026, 9, 20))
    assert adopt_scheduled_end_date(d, date(2026, 9, 22)) is True
    assert d.end_date == date(2026, 9, 22)


@pytest.mark.parametrize("day", [date(2026, 9, 20), date(2026, 9, 19), date(2026, 9, 1)])
def test_it_never_pulls_the_end_date_in(day):
    """A day with no sheet is not evidence that play has stopped.

    Shrinking the range would retire a live tournament, which is the failure
    this rule exists to prevent — so the calendar's date is a floor.
    """
    d = D(date(2026, 9, 20))
    assert adopt_scheduled_end_date(d, day) is False
    assert d.end_date == date(2026, 9, 20)


def test_a_row_a_fortnight_out_is_some_other_event():
    """Bounded to a week: past that it is a misparse, not a tournament."""
    d = D(date(2026, 9, 20))
    assert adopt_scheduled_end_date(d, date(2026, 10, 5)) is False
    assert d.end_date == date(2026, 9, 20)


def test_nothing_to_go_on_changes_nothing():
    d = D(date(2026, 9, 20))
    assert adopt_scheduled_end_date(d, None) is False
    assert adopt_scheduled_end_date(D(None), date(2026, 9, 21)) is False
