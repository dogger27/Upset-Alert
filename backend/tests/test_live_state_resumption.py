"""resumed_at is stamped only when a REAL stop ends — see live_state.MIN_STOP."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import live_state
from app.services.live_state import note_resumption

PLAYING = [["3"], ["2"], 1, [None]]
STOPPED = [["3"], ["2"], None, [None], "suspended"]


def _match(live=None, suspended_at=None, resumed_at=None):
    return SimpleNamespace(live_scores_json=live, suspended_at=suspended_at, resumed_at=resumed_at)


def test_playing_to_suspended_stamps_the_stop_not_a_resumption():
    m = _match(PLAYING)
    assert note_resumption(m, STOPPED) is None
    assert m.suspended_at is not None and m.resumed_at is None


def test_a_flap_between_writers_is_not_a_resumption():
    now = datetime.now(timezone.utc)
    m = _match(STOPPED, suspended_at=now - timedelta(seconds=40))
    assert note_resumption(m, PLAYING) is None
    assert m.resumed_at is None


def test_a_set_break_is_not_a_resumption():
    now = datetime.now(timezone.utc)
    m = _match(STOPPED, suspended_at=now - timedelta(minutes=5))
    assert note_resumption(m, PLAYING) is None


def test_a_rain_delay_is_a_resumption():
    now = datetime.now(timezone.utc)
    m = _match(STOPPED, suspended_at=now - live_state.MIN_STOP - timedelta(minutes=1))
    stamped = note_resumption(m, PLAYING)
    assert stamped is not None and m.resumed_at == stamped


def test_overnight_carry_over_is_a_resumption_even_with_a_naive_stamp():
    # SQLite hands back naive datetimes; the comparison must not blow up.
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=14)
    m = _match(STOPPED, suspended_at=since)
    assert note_resumption(m, PLAYING) is not None


def test_a_stop_whose_start_was_never_seen_is_not_trusted():
    m = _match(STOPPED, suspended_at=None)
    assert note_resumption(m, PLAYING) is None


def test_playing_to_playing_and_stopped_to_stopped_do_nothing():
    m = _match(PLAYING)
    assert note_resumption(m, PLAYING) is None and m.suspended_at is None
    m2 = _match(STOPPED, suspended_at=datetime.now(timezone.utc))
    assert note_resumption(m2, STOPPED) is None and m2.resumed_at is None
