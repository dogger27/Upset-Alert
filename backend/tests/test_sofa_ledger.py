"""Every Sofascore request recorded; a block leaves the record behind."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import sofa_ledger as L  # noqa: E402


def test_requests_are_written_with_their_caller_and_summarised(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "DIR", str(tmp_path))
    L._recent.clear()
    tok = L.CALLER.set("sofascore_doubles.sweep_once")
    L.record("/unique-tournament/24725/season/85662/events/last/0", "direct", 200, 120.4, 900)
    L.record("/unique-tournament/24725/season/85662/events/next/0", "direct", 404, 80, 0)
    L.CALLER.reset(tok)
    L.record("/sport/tennis/events/live", "direct", 403, 50)
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    rows = [json.loads(x) for x in files[0].read_text().splitlines()]
    assert rows[0]["caller"] == "sofascore_doubles.sweep_once" and rows[0]["status"] == 200
    s = L.summary(60)
    assert s["requests"] == 3
    assert s["by_path"]["/unique-tournament/N/season/N/events/last/N"] == 1
    assert s["by_status"] == {"200": 1, "404": 1, "403": 1}


def test_a_block_snapshot_holds_the_requests_before_it(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "DIR", str(tmp_path))
    for i in range(5):
        L.record(f"/event/{i}", "direct", 200, 10)
    p = L.snapshot("403 on /sport/tennis/events/live")
    lines = Path(p).read_text().splitlines()
    head = json.loads(lines[0])
    assert head["reason"].startswith("403") and head["summary_1h"]["requests"] == 5
    assert len(lines) == 6


def test_the_watch_warns_over_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "DIR", str(tmp_path))
    said = []

    async def fake_log(level, cat, msg, detail=None, **kw):
        said.append((level, msg))
    import app.services.system_log as sl
    monkeypatch.setattr(sl, "app_log", fake_log)
    tok = L.CALLER.set("sofascore_doubles.sweep_once")
    for i in range(L.CALLER_WARN_DEFAULT + 1):
        L.record(f"/event/{i}", "direct", 200, 1)
    L.CALLER.reset(tok)
    asyncio.run(L.check())
    assert said and said[0][0] == "warning" and "sofascore_doubles.sweep_once" in said[0][1]


def test_caller_is_the_first_frame_outside_the_client():
    def poller():
        return L.caller_of()
    # caller_of skips two frames (itself and sofascore._get); called from a
    # nested helper here, it lands on this test module.
    def wrapper():
        return poller()
    assert wrapper().startswith("test_sofa_ledger.")


def test_the_series_buckets_every_minute_and_counts_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "DIR", str(tmp_path))
    tok = L.CALLER.set("sofascore_live.poll_once")
    L.record("/sport/tennis/events/live", "direct", 200, 10)
    L.record("/sport/tennis/events/live", "direct", 403, 10)
    L.record("/sport/tennis/events/live", "direct", None, 10)
    L.CALLER.reset(tok)
    rows = L._read_since(L.datetime.now(L.timezone.utc) - L.timedelta(minutes=60))
    ser = L.series(rows, 60, L.bucket_minutes(60))
    assert 60 <= len(ser) <= 62                      # empty minutes included
    last = ser[-1]
    assert last["n"] == 3 and last["blocked"] == 1 and last["failed"] == 1
    assert last["by_caller"] == {"sofascore_live.poll_once": 3}
    assert L.bucket_minutes(7 * 24 * 60) == 60


def test_last_outcomes_and_snapshots_are_found(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "DIR", str(tmp_path))
    L.record("/a", "direct", 200, 10)
    L.record("/b", "direct", 403, 10)
    last = L.last_outcomes()
    assert last["ok"]["path"] == "/a" and last["blocked"]["path"] == "/b"
    L.snapshot("403 on /b")
    snaps = L.snapshots()
    assert len(snaps) == 1 and snaps[0]["reason"] == "403 on /b" and snaps[0]["requests_1h"] == 2
