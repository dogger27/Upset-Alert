"""The 403 breaker survives a restart, and a handled refusal is not a warning.

2026-09-25: one Sofascore refusal at 10:07 UTC, then two deploys. Each fresh
process started with the breaker closed and consecutive_blocks at 0, asked
/events/live at once, was refused again and warned again (10:13, 10:17) —
three warnings for one ban, and two more pokes at the host the cooldown
exists to leave alone.
"""
import asyncio
import json
import time

from app.services import settings as st
from app.services import sofascore
from tests.conftest import REAL_SAVE_BREAKER


class _FakeStore:
    def __init__(self):
        self.rows = {}

    def install(self, monkeypatch):
        async def get_setting(db, key):
            return self.rows.get(key, "")

        async def set_setting(db, key, value):
            self.rows[key] = value
        monkeypatch.setattr(st, "get_setting", get_setting)
        monkeypatch.setattr(st, "set_setting", set_setting)

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def commit(self):
                pass
        import app.database as dbmod
        monkeypatch.setattr(dbmod, "AsyncSessionLocal", _Session)


def _wire(monkeypatch, status, logged):
    fetched = []

    def fake_fetch(path, rotate=False):
        fetched.append(path)
        return status, {}
    monkeypatch.delenv("SOFASCORE_PROXY", raising=False)
    monkeypatch.setattr(sofascore, "_egress_direct", True)
    monkeypatch.setattr(sofascore, "_fetch", fake_fetch)
    monkeypatch.setattr(sofascore, "_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(sofascore, "_blocked_until", 0.0)
    monkeypatch.setattr(sofascore, "_consecutive_blocks", 0)

    async def fake_app_log(level, category, message, **kw):
        logged.append((level, message))
    monkeypatch.setattr(sofascore, "app_log", fake_app_log)
    return fetched


def test_restart_adopts_an_open_breaker(monkeypatch):
    store = _FakeStore()
    store.install(monkeypatch)
    monkeypatch.setattr(sofascore, "_save_breaker", REAL_SAVE_BREAKER)
    logged = []
    fetched = _wire(monkeypatch, 403, logged)

    async def first_process():
        try:
            await sofascore._get("/sport/tennis/events/live")
        except sofascore.SofascoreBlocked:
            pass
    asyncio.run(first_process())
    assert len(fetched) == 1
    saved = json.loads(store.rows[st.SOFA_BREAKER])
    assert saved["blocks"] == 1 and saved["until"] > time.time() + 1700

    # The deploy: a new process, breaker closed in memory, not yet loaded.
    monkeypatch.setattr(sofascore, "_blocked_until", 0.0)
    monkeypatch.setattr(sofascore, "_consecutive_blocks", 0)
    monkeypatch.setattr(sofascore, "_breaker_loaded", False)

    async def second_process():
        try:
            await sofascore._get("/sport/tennis/events/live")
        except sofascore.SofascoreBlocked as e:
            return e
    assert isinstance(asyncio.run(second_process()), sofascore.SofascoreBlocked)
    assert len(fetched) == 1                  # never asked the refusing host
    assert sofascore._consecutive_blocks == 1
    assert len(logged) == 1                   # and said nothing new


def test_success_clears_the_stored_breaker(monkeypatch):
    store = _FakeStore()
    store.install(monkeypatch)
    monkeypatch.setattr(sofascore, "_save_breaker", REAL_SAVE_BREAKER)
    _wire(monkeypatch, 200, [])
    monkeypatch.setattr(sofascore, "_consecutive_blocks", 2)
    asyncio.run(sofascore._get("/sport/tennis/events/live"))
    saved = json.loads(store.rows[st.SOFA_BREAKER])
    assert saved["blocks"] == 0 and saved["until"] <= time.time() + 1


def test_a_ban_warns_once_however_long_it_lasts(monkeypatch):
    """2026-09-25: the ban that tripped at 10:07 warned again at 11:24 on its
    third trip — the "persistent" escalation was the same alarm, later. One
    ban is ONE warning, at its start (the owner must hear of every ban), and
    the breaker's later trips are info."""
    logged = []
    _wire(monkeypatch, 403, logged)

    async def trip():
        monkeypatch.setattr(sofascore, "_blocked_until", 0.0)   # cooldown over
        try:
            await sofascore._get("/sport/tennis/events/live")
        except sofascore.SofascoreBlocked:
            pass
    for _ in range(6):
        asyncio.run(trip())
    assert sofascore._consecutive_blocks == 6
    assert [lv for lv, _ in logged if lv == "warning"] == ["warning"]


def test_the_queue_behind_a_refusal_does_not_walk_into_the_ban(monkeypatch):
    """11:24:21 logged trip 3; by 11:24:25 the stored breaker said 5. The
    requests queued at the pacing gate had passed the breaker check before the
    first was refused, and each went on to ask the banned host itself."""
    logged = []
    fetched = _wire(monkeypatch, 403, logged)
    monkeypatch.setattr(sofascore, "_MIN_INTERVAL", 0.05)
    monkeypatch.setattr(sofascore, "_last_request_at", 0.0)

    async def burst():
        async def one():
            try:
                await sofascore._get("/sport/tennis/events/live")
            except sofascore.SofascoreBlocked:
                pass
        await asyncio.gather(*(one() for _ in range(4)))
    asyncio.run(burst())
    assert len(fetched) == 1
    assert sofascore._consecutive_blocks == 1
