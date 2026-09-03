"""One scoring source at a time: the standby predicate."""
import asyncio
import time
from app.services import sofascore_live as sl


def test_healthy_from_process_start_then_stale():
    sl._last_ok = time.monotonic()
    assert sl.live_feed_healthy() is True
    sl._last_ok = time.monotonic() - sl.FEED_STALE_AFTER - 1
    assert sl.live_feed_healthy() is False


def test_a_marked_cycle_restores_health():
    sl._last_ok = 0.0
    assert sl.live_feed_healthy() is False
    sl._mark_ok()
    assert sl.live_feed_healthy() is True


def test_open_breaker_is_not_healthy():
    from app.services import sofascore
    async def go():
        sl._mark_ok()
        old = sofascore._blocked_until
        sofascore._blocked_until = asyncio.get_running_loop().time() + 600
        try:
            return sl.live_feed_healthy()
        finally:
            sofascore._blocked_until = old
    assert asyncio.get_event_loop().run_until_complete(go()) is False
