"""protennislive and Tennis Explorer requests are recorded by the transport
every fetch site builds its client with (services/request_ledger)."""
import asyncio
import json

import httpx

from app.services import request_ledger as RL
from app.services import sofa_ledger as SL


def _fake(status):
    async def handler(request):
        return httpx.Response(status, headers={"content-length": "4"}, content=b"%PDF")
    return httpx.MockTransport(handler)


def _rows(tmp_path, source):
    out = []
    for p in (tmp_path / source).glob("????-??-??.jsonl"):
        out += [json.loads(line) for line in p.read_text().splitlines()]
    return out


async def fetch_the_sheet(client, url):
    return await client.get(url)


def test_a_protennislive_request_is_recorded_with_its_caller(tmp_path, monkeypatch):
    monkeypatch.setattr(RL, "ROOT", str(tmp_path))

    async def go():
        async with httpx.AsyncClient(transport=RL._LedgerTransport(_fake(200))) as c:
            await fetch_the_sheet(c, "https://www.protennislive.com/posting/2026/329/mds.pdf")
            await c.get("https://example.org/not-recorded")
    asyncio.run(go())
    rows = _rows(tmp_path, "protennislive")
    assert len(rows) == 1
    assert rows[0]["path"] == "/posting/2026/329/mds.pdf"
    assert rows[0]["status"] == 200 and rows[0]["bytes"] == 4
    assert rows[0]["caller"] == "test_request_ledger.fetch_the_sheet"
    assert not (tmp_path / "tennisexplorer").exists()


def test_a_refusal_writes_one_snapshot_an_hour(tmp_path, monkeypatch):
    monkeypatch.setattr(RL, "ROOT", str(tmp_path))
    monkeypatch.setattr(RL, "_last_snapshot", {})

    async def go():
        async with httpx.AsyncClient(transport=RL._LedgerTransport(_fake(429))) as c:
            for _ in range(3):
                await c.get("https://www.tennisexplorer.com/mutual/a/b/")
    asyncio.run(go())
    assert len(_rows(tmp_path, "tennisexplorer")) == 3
    snaps = list((tmp_path / "tennisexplorer").glob("block-*.jsonl"))
    assert len(snaps) == 1


def test_the_view_reads_a_source_and_measures_its_busiest_window(tmp_path, monkeypatch):
    monkeypatch.setattr(RL, "ROOT", str(tmp_path))
    d = RL.dir_for("protennislive")
    for st in (200,) * 11 + (429,):
        SL.record("/posting/2026/1/op.pdf", "direct", st, 5, dir_=d, caller="order_of_play.x")
    v = RL.view("protennislive", 60, 5)
    assert v["summary"]["requests"] == 12
    assert v["summary"]["busiest_window"] == 12
    assert v["budgets"]["window"] == {"minutes": 10, "limit": 9}
    assert v["last"]["blocked"]["status"] == 429
    assert len(v["recent"]) == 5
    assert {s["key"] for s in v["sources"]} == {"sofascore", "protennislive", "tennisexplorer"}


def test_modules_that_fetch_only_these_hosts_use_the_recording_client():
    """A client for either host built with plain httpx would go unrecorded.
    order_of_play and rankings also fetch other hosts (WTA, Wikipedia, USO,
    Tennis Abstract) with plain clients, so they are checked by count: each
    has exactly the recording clients it had when this was written."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for p in root.rglob("*.py"):
        rel = str(p.relative_to(root))
        src = p.read_text()
        if rel in ("services/request_ledger.py", "services/order_of_play.py", "services/rankings.py"):
            continue
        if re.search(r"https://www\.(protennislive|tennisexplorer)\.com", src) and "httpx.AsyncClient(" in src:
            offenders.append(rel)
    assert not offenders, offenders
    count = lambda rel: (root / rel).read_text().count("request_ledger.client(")
    assert count("services/order_of_play.py") == 1
    assert count("services/rankings.py") == 4
