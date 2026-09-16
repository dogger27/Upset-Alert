"""A walkover declared ahead of its slot — Guadalajara 2026-09-16.

Townsend withdrew at 18:24 UTC from a 23:00 match against Kostyuk. Sofascore
marked event 17066558 finished (code 91, winnerCode 1) but kept it on
`events/next`, because its startTimestamp was still in the future, so the
results sweep — which read only `events/last` — could not see it. Wikipedia
showed the walkover and the scraper warned two minutes later.
"""
import asyncio
from types import SimpleNamespace

from app.routers import tournaments as tr
from app.services import sofascore_results as sr

# events/next/0 for season 85638 as served at 21:50 UTC, trimmed.
NEXT_PAGE = {"events": [
    {"id": 17066558, "startTimestamp": 1789599600, "winnerCode": 1,
     "status": {"code": 91, "description": "Walkover", "type": "finished"},
     "homeTeam": {"id": 230056}, "awayTeam": {"id": 51387},
     "homeScore": {}, "awayScore": {}},
    {"id": 17066568, "startTimestamp": 1789602000,
     "status": {"code": 0, "description": "Not started", "type": "notstarted"},
     "homeTeam": {"id": 1}, "awayTeam": {"id": 2}},
], "hasNextPage": False}


def test_the_walkover_is_taken_from_the_next_page():
    assert [ev["id"] for ev in sr.decided_ahead_of_slot(NEXT_PAGE)] == [17066558]


def test_an_empty_next_page_is_nothing():
    assert sr.decided_ahead_of_slot({}) == []
    assert sr.decided_ahead_of_slot(None) == []


def test_the_walkover_scores_as_stored():
    ev = NEXT_PAGE["events"][0]
    assert sr._final_scores(ev["homeScore"], ev["awayScore"], 91, 1) == [["w/o"], [""]]


class _Result:
    def first(self):
        return (5373,)                      # a match still waiting on Sofascore

    def scalars(self):
        return SimpleNamespace(all=lambda: [])


class _DB:
    async def execute(self, *_a, **_k):
        return _Result()

    async def commit(self):
        pass


def _sweep(monkeypatch, fetched, recorded):
    async def tracked(_db):
        return {(16559, 85638): 142}, {230056: 5907, 51387: 5896}

    async def get(path):
        fetched.append(path)
        if path.endswith("/events/next/0"):
            return NEXT_PAGE
        return {"events": []}               # `last` holds nothing new

    async def record(_db, ev, draw_id, _by_player, _now):
        recorded.append((ev["id"], draw_id))
        return "written"

    monkeypatch.setattr(sr, "_tracked", tracked)
    monkeypatch.setattr(sr, "_get", get)
    monkeypatch.setattr(sr, "_record", record)
    from app.services import broadcaster, chances_warm

    async def publish(*_a, **_k):
        pass
    monkeypatch.setattr(broadcaster, "publish", publish)
    monkeypatch.setattr(chances_warm, "warm_soon", lambda *_a, **_k: None)
    return asyncio.new_event_loop().run_until_complete(sr.sweep_once(_DB()))


def test_the_sweep_records_it_and_reads_next_at_its_own_pace(monkeypatch):
    monkeypatch.setattr(sr, "_next_checked", {})
    fetched, recorded = [], []
    report = _sweep(monkeypatch, fetched, recorded)
    assert recorded == [(17066558, 142)]
    assert report["written"] == 1
    assert sum(p.endswith("/events/next/0") for p in fetched) == 1

    # Three minutes later: `last` again, but `next` waits for NEXT_INTERVAL.
    fetched.clear()
    _sweep(monkeypatch, fetched, recorded)
    assert fetched and not any(p.endswith("/events/next/0") for p in fetched)


def test_a_wikipedia_claim_warns_only_once_it_outlasts_the_grace(monkeypatch):
    monkeypatch.setattr(tr, "_wiki_claim_seen", {})
    t0 = 1000.0
    assert tr._wiki_claim_overdue(5373, now=t0) is False
    assert tr._wiki_claim_overdue(5373, now=t0 + tr.WIKI_CLAIM_GRACE - 1) is False
    assert tr._wiki_claim_overdue(5373, now=t0 + tr.WIKI_CLAIM_GRACE) is True
    # Sofascore catches up and the claim is dropped: a later one starts afresh.
    tr._wiki_claim_seen.pop(5373)
    assert tr._wiki_claim_overdue(5373, now=t0 + 10 * tr.WIKI_CLAIM_GRACE) is False
