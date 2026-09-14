"""The published order of play dates day one; the calendar only guessed it.

2026 Guadalajara is the case these exist for: Wikipedia said Mon 14 Sep, the
first ball was Sun 13 Sep at 12:00, and the card advertised "Sep 14 – 19" with
seven minutes left on the clock.
"""
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

from app.services.tournament_schedule import (adopt_observed_start_date,
                                              sync_closing_time)


# RELATIVE TO TODAY, never a fixed September. adopt_observed_start_date refuses
# a day already past, so a hard-coded 2026-09-13 passed on the 13th and failed
# on the 14th — a test that rots overnight and reports a working guard as broken.
TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)


def draw(**kw):
    """Guadalajara's shape: the calendar says tomorrow, the first ball is today."""
    noon = datetime.combine(TODAY, time(18, 0))   # 12:00 in Mexico City
    d = dict(start_date=TOMORROW, year=TODAY.year, week=37, status="upcoming",
             picks_locked_at=None, venue_timezone="America/Mexico_City",
             first_match_at=noon, first_match_local_hour=12,
             first_match_local_minute=0, day1_start_hour=12, day1_start_minute=0,
             closing_time=noon)
    d.update(kw)
    return SimpleNamespace(**d)


def test_moves_start_date_onto_the_observed_day():
    d = draw()
    assert adopt_observed_start_date(d)
    assert d.start_date == TODAY
    assert not adopt_observed_start_date(d)


def test_refuses_once_picks_are_locked_or_play_began():
    assert not adopt_observed_start_date(draw(picks_locked_at=datetime.utcnow()))
    assert not adopt_observed_start_date(draw(status="active"))


def test_refuses_a_gap_wider_than_a_day():
    assert not adopt_observed_start_date(
        draw(first_match_at=datetime.combine(TODAY - timedelta(days=4), time(18, 0))))


def test_refuses_a_day_already_past():
    """Would read as "this began yesterday" and shut picks that are still open."""
    past = TODAY - timedelta(days=2)
    assert not adopt_observed_start_date(
        draw(start_date=past + timedelta(days=1),
             first_match_at=datetime.combine(past, time(18, 0))))


def test_sync_closing_time_stands_aside_for_evidence():
    d = draw()
    was = d.closing_time
    assert not sync_closing_time(d)
    assert d.closing_time == was


def test_sync_closing_time_still_re_derives_without_an_observation():
    d = draw(first_match_at=None,
             closing_time=datetime.combine(TODAY - timedelta(days=12), time(18, 0)))
    assert sync_closing_time(d)
    assert d.closing_time.date() == TOMORROW
