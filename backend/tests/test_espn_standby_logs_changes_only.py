"""A restart is not a handover: the admin log hears only real changes of who
writes scores (owner, 2026-09-26 — 224 "standing by" rows, one per boot)."""
import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import espn_monitor as E  # noqa: E402


def test_first_reading_is_quiet_and_a_real_change_is_logged(monkeypatch):
    said = []

    async def _log(level, cat, msg, *a, **k):
        said.append(msg)

    @asynccontextmanager
    async def _session():
        yield None

    async def _load(db):
        return True

    healthy = {"v": True}
    monkeypatch.setattr(E, "app_log", _log)
    monkeypatch.setattr(E, "AsyncSessionLocal", _session)
    monkeypatch.setattr(E, "load_sofa_authoritative", _load)
    monkeypatch.setattr(E, "sofa_authoritative", lambda: True)
    monkeypatch.setattr(E, "live_feed_healthy", lambda: healthy["v"])

    m = E.ESPNMonitor()
    assert asyncio.run(m._scoring_active()) is False
    assert said == []                                  # boot: nothing logged
    assert asyncio.run(m._scoring_active()) is False
    assert said == []                                  # no change: nothing
    healthy["v"] = False
    import app.services.sofascore as S
    monkeypatch.setattr(S, "blocked_for", lambda: 0)
    assert asyncio.run(m._scoring_active()) is True
    assert len(said) == 1 and "ACTIVE" in said[0]      # a real handover
