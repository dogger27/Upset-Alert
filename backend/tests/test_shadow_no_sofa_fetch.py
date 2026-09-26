"""The shadow learns court names from the ingest's pages and asks Sofascore
nothing itself (owner, 2026-09-26)."""
import asyncio
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import schedule_shadow, sofa_schedule  # noqa: E402


def _draw():
    return SimpleNamespace(gender="M", venue_timezone="Asia/Seoul", sofa_tournament_id=1,
                           sofa_season_id=2, sofa_doubles_tournament_id=None,
                           sofa_doubles_season_id=None)


def test_the_shadow_never_fetches_from_sofascore(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("the shadow asked Sofascore")

    async def no_event(*a, **k):
        return None

    monkeypatch.setattr(sofa_schedule, "fetch_events", boom)
    monkeypatch.setattr(schedule_shadow, "wta_event_id", no_event)
    schedule_shadow._OFFERED.clear()
    t = SimpleNamespace(id=9, name="Korea Open")
    out, sources = asyncio.run(schedule_shadow._structured(None, t, [_draw()], date(2026, 9, 26)))
    assert out == [] and sources == ""


def test_it_reads_what_the_ingest_offered(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("the shadow asked Sofascore")

    async def no_event(*a, **k):
        return None

    monkeypatch.setattr(sofa_schedule, "fetch_events", boom)
    monkeypatch.setattr(schedule_shadow, "wta_event_id", no_event)
    schedule_shadow.offer_events(1, 2, [])
    t = SimpleNamespace(id=9, name="Korea Open")
    _out, sources = asyncio.run(schedule_shadow._structured(None, t, [_draw()], date(2026, 9, 26)))
    assert sources == "sofa:1"


def test_learning_never_raises_into_the_order_of_play_job(monkeypatch):
    async def broken(*a, **k):
        raise RuntimeError("feed down")

    monkeypatch.setattr(schedule_shadow, "compare_day", broken)
    t = SimpleNamespace(id=9, name="Korea Open")
    asyncio.run(schedule_shadow.learn_from_sheet(t, [_draw()], date(2026, 9, 26)))
