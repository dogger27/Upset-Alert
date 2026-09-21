"""A 5xx from Sofascore is their server failing, not them refusing us.

2026-09-21: one HTTP 503 on a doubles season page came back as
SofascoreBlocked, so the doubles sweep stood down for thirty minutes and logged
"Doubles sweep paused" to the owner — with the breaker never open.
"""
import asyncio

from app.services import sofascore, sofascore_doubles
from app.services.http_errors import is_transient_http_error


def _get_with_status(monkeypatch, status):
    monkeypatch.setattr(sofascore, "_fetch", lambda path, rotate=False: (status, None))
    monkeypatch.setattr(sofascore, "_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(sofascore, "_blocked_until", 0.0)
    monkeypatch.setattr(sofascore, "_consecutive_blocks", 0)

    async def go():
        try:
            await sofascore._get("/unique-tournament/2643/season/85585/events/last/0")
        except Exception as exc:        # noqa: BLE001 — the class is the assertion
            return exc, sofascore.blocked_for()
        return None, sofascore.blocked_for()
    return asyncio.run(go())


def test_503_is_unavailable_not_blocked(monkeypatch):
    exc, blocked = _get_with_status(monkeypatch, 503)
    assert isinstance(exc, sofascore.SofascoreUnavailable)
    assert not isinstance(exc, sofascore.SofascoreBlocked)
    assert blocked == 0.0
    assert sofascore._consecutive_blocks == 0
    assert is_transient_http_error(exc)


def test_cloudflare_52x_is_unavailable(monkeypatch):
    exc, _ = _get_with_status(monkeypatch, 522)
    assert isinstance(exc, sofascore.SofascoreUnavailable)


def test_429_is_still_a_refusal(monkeypatch):
    exc, _ = _get_with_status(monkeypatch, 429)
    assert isinstance(exc, sofascore.SofascoreBlocked)


def test_doubles_sweep_does_not_pause_or_alert_on_a_5xx(monkeypatch):
    logged = []

    async def fake_app_log(level, category, message, **kw):
        logged.append((level, category, message))

    mon = sofascore_doubles.SofascoreDoublesMonitor()
    waits = []

    async def fake_sweep(db):
        # The sweep's own request, answered with the 503 from the incident.
        mon._stop.set()
        await sofascore_doubles._get(
            "/unique-tournament/2643/season/85585/events/last/0")

    real_wait_for = asyncio.wait_for

    async def spy_wait_for(aw, timeout):
        waits.append(timeout)
        return await real_wait_for(aw, timeout)

    monkeypatch.setattr(sofascore, "_fetch", lambda path, rotate=False: (503, None))
    monkeypatch.setattr(sofascore, "_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(sofascore, "_blocked_until", 0.0)
    monkeypatch.setattr(sofascore_doubles, "sweep_once", fake_sweep)
    monkeypatch.setattr(sofascore_doubles, "app_log", fake_app_log)
    monkeypatch.setattr(sofascore_doubles.asyncio, "wait_for", spy_wait_for)

    asyncio.run(mon._run())

    assert logged == []
    assert waits == [sofascore_doubles.POLL_INTERVAL]
