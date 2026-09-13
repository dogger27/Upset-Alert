"""The published order of play dates day one; the calendar only guessed it.

2026 Guadalajara is the case these exist for: Wikipedia said Mon 14 Sep, the
first ball was Sun 13 Sep at 12:00, and the card advertised "Sep 14 – 19" with
seven minutes left on the clock.
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.services.tournament_schedule import (adopt_observed_start_date,
                                              sync_closing_time)


def draw(**kw):
    d = dict(start_date=date(2026, 9, 14), year=2026, week=37, status="upcoming",
             picks_locked_at=None, venue_timezone="America/Mexico_City",
             first_match_at=datetime(2026, 9, 13, 18, 0), first_match_local_hour=12,
             first_match_local_minute=0, day1_start_hour=12, day1_start_minute=0,
             closing_time=datetime(2026, 9, 13, 18, 0))
    d.update(kw)
    return SimpleNamespace(**d)


def test_moves_start_date_onto_the_observed_day():
    d = draw()
    assert adopt_observed_start_date(d)
    assert d.start_date == date(2026, 9, 13)
    # A Sunday start already belongs to the week ahead, so the week holds.
    assert d.week == 37
    assert not adopt_observed_start_date(d)


def test_refuses_once_picks_are_locked_or_play_began():
    assert not adopt_observed_start_date(draw(picks_locked_at=datetime.utcnow()))
    assert not adopt_observed_start_date(draw(status="active"))


def test_refuses_a_gap_wider_than_a_day():
    assert not adopt_observed_start_date(draw(first_match_at=datetime(2026, 9, 10, 18, 0)))


def test_refuses_a_day_already_past():
    """Would read as "this began yesterday" and shut picks that are still open."""
    past = date.today() - timedelta(days=2)
    assert not adopt_observed_start_date(
        draw(start_date=past + timedelta(days=1),
             first_match_at=datetime(past.year, past.month, past.day, 18, 0)))


def test_sync_closing_time_stands_aside_for_evidence():
    d = draw()
    assert not sync_closing_time(d)
    assert d.closing_time == datetime(2026, 9, 13, 18, 0)


def test_sync_closing_time_still_re_derives_without_an_observation():
    d = draw(first_match_at=None, closing_time=datetime(2026, 9, 1, 18, 0))
    assert sync_closing_time(d)
    assert d.closing_time.date() == date(2026, 9, 14)
