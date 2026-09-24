"""A failed on-demand Sofascore read is not repeated by every poll."""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import sofascore as sf                       # noqa: E402
from app.services import sofascore_backoff as B                # noqa: E402
from app.services import sofascore_points as P                 # noqa: E402
from app.services import sofascore_stats as ST                 # noqa: E402

T0 = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)


def test_not_found_holds_longer_than_an_error():
    B._FAILED.clear()
    B.note_failure("points", 1, sf.SofascoreNotFound("404"), now=T0)
    B.note_failure("points", 2, RuntimeError("503"), now=T0)
    later = T0 + timedelta(minutes=5)
    assert B.held_off("points", 1, now=later)
    assert not B.held_off("points", 2, now=later)
    assert not B.held_off("stats", 1, now=later)      # kinds are separate


def _counting(monkeypatch, exc):
    calls = []

    async def fake_get(path):
        calls.append(path)
        await asyncio.sleep(0.01)
        raise exc
    monkeypatch.setattr(sf, "_get", fake_get)
    return calls


def test_points_404_is_asked_once_across_many_polls(monkeypatch):
    B._FAILED.clear(); P._CACHE.clear(); P._INFLIGHT.clear()
    calls = _counting(monkeypatch, sf.SofascoreNotFound("404"))

    async def polls():
        for _ in range(5):
            assert await P.points_for(99, finished=True) == {}
    asyncio.run(polls())
    assert len(calls) == 1


def test_stats_share_one_request_and_remember_the_failure(monkeypatch):
    B._FAILED.clear(); ST._CACHE.clear(); ST._INFLIGHT.clear()
    calls = _counting(monkeypatch, RuntimeError("503"))

    async def readers():
        await asyncio.gather(*(ST.stats_for(77, finished=False) for _ in range(4)))
        await ST.stats_for(77, finished=False)
    asyncio.run(readers())
    assert len(calls) == 1
