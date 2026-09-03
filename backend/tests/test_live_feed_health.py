"""One scoring source at a time: the standby predicate."""
import asyncio
from app.services import sofascore_live as sl


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_never_polled_is_not_healthy():
    async def go():
        sl._last_ok = 0.0
        return sl.live_feed_healthy()
    assert _run(go()) is False


def test_fresh_cycle_is_healthy_and_a_stale_one_is_not():
    async def go():
        sl._mark_ok()
        fresh = sl.live_feed_healthy()
        sl._last_ok = asyncio.get_running_loop().time() - sl.FEED_STALE_AFTER - 1
        return fresh, sl.live_feed_healthy()
    assert _run(go()) == (True, False)


def test_open_breaker_is_not_healthy(monkeypatch=None):
    from app.services import sofascore
    async def go():
        sl._mark_ok()
        old = sofascore._blocked_until
        sofascore._blocked_until = asyncio.get_running_loop().time() + 600
        try:
            return sl.live_feed_healthy()
        finally:
            sofascore._blocked_until = old
    assert _run(go()) is False


def test_outside_a_loop_is_not_healthy():
    assert sl.live_feed_healthy() is False
