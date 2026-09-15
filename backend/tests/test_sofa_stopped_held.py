"""A stopped Sofascore event keeps its score and says so — SP Open 2026-09-15.

Rain stopped three R32 singles matches; Sofascore marked them "interrupted"
and took them off its live list, and the singles poller erased their scores.
"""
from datetime import datetime, timedelta, timezone

from app.services import live_state
from app.services.live_state import is_suspended, stop_began, stop_reads_suspended
from app.services.sofascore_live import _as_espn_shape

NOW = datetime(2026, 9, 15, 21, 40, tzinfo=timezone.utc)
# Brace/Sierra's event as Sofascore served it during the delay.
RAIN = {"status": {"type": "interrupted"},
        "changes": {"changes": ["status.code", "status.description", "status.type"],
                    "changeTimestamp": 1789495915}}


def test_a_status_change_dates_the_stop():
    assert stop_began(RAIN, None, NOW) == datetime.fromtimestamp(1789495915, tz=timezone.utc)


def test_a_held_onset_is_carried_not_restamped():
    prev = {"stopped_since": "2026-09-15T18:00:00+00:00"}
    assert stop_began(RAIN, prev, NOW) == datetime(2026, 9, 15, 18, tzinfo=timezone.utc)


def test_a_score_change_does_not_date_a_stop():
    ev = {"changes": {"changes": ["homeScore.point"], "changeTimestamp": 1}}
    assert stop_began(ev, None, NOW) == NOW


def test_a_medical_timeout_is_not_suspended():
    assert not stop_reads_suspended("interrupted", NOW - timedelta(minutes=3), NOW)


def test_a_rain_delay_is_suspended():
    assert stop_reads_suspended("interrupted", NOW - timedelta(hours=3), NOW)


def test_the_suspended_words_need_no_clock():
    for status in live_state.SOFA_SUSPENDED:
        assert stop_reads_suspended(status, None, NOW)


def test_playing_is_never_suspended():
    assert not stop_reads_suspended("inprogress", NOW - timedelta(hours=3), NOW)


def test_the_espn_shape_carries_the_stop():
    live = _as_espn_shape({"sets": [[4, 4]], "serving": None, "suspended": True})
    assert is_suspended(live) and live[:2] == [["4"], ["4"]]


def test_a_playing_espn_shape_has_no_fifth_slot():
    assert len(_as_espn_shape({"sets": [[4, 4]], "serving": 2})) == 4


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
