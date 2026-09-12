"""A placeholder timestamp is not a published order of play.

ESPN fills a scheduled-but-unpublished match with a constant instant. The old
test for that was "midnight local", which only works where the constant IS
midnight: Guadalajara 2026 arrived as twelve day-1 matches at 04:00 UTC —
22:00 in Mexico City, 01:00 in Sao Paulo — and set the pick deadline to ten in
the evening the day BEFORE the main draw, against a real first ball of 10:00
the next morning (Sofascore: Sun 13 Sep 16:00 UTC).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.espn_monitor import (SESSION_EARLIEST_HOUR,   # noqa: E402
                                       SESSION_LATEST_HOUR)


def plausible(hour):
    return SESSION_EARLIEST_HOUR <= hour <= SESSION_LATEST_HOUR


def test_the_two_placeholders_seen_in_the_wild():
    assert not plausible(22)      # Guadalajara: 04:00 UTC in Mexico City
    assert not plausible(1)       # SP Open: the same instant in Sao Paulo
    assert not plausible(0)       # the midnight case the old test caught


def test_real_session_starts_pass():
    for hour in (10, 11, 12, 14, 17, 19, 20):   # day and night sessions
        assert plausible(hour), hour


def test_the_bounds_are_where_they_are_for_a_reason():
    """Tightening these would reject a real session; loosening them lets the
    placeholder back in. 22:00 is the placeholder, 21:00 is a late night
    session, 08:00 is earlier than any tour session actually begins."""
    assert plausible(SESSION_LATEST_HOUR) and not plausible(SESSION_LATEST_HOUR + 1)
    assert plausible(SESSION_EARLIEST_HOUR) and not plausible(SESSION_EARLIEST_HOUR - 1)
