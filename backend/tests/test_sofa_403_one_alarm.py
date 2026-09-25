"""One Sofascore refusal is one alarm, and what it knocks over is handled.

2026-09-25 10:07 UTC: a single 403 on Chengdu's doubles season page. The
client warned once ("Sofascore returned 403 — all requests paused"), then the
same refusal came back as six more warnings: a "switched to the residential
proxy" with no proxy configured, "Doubles sweep paused", "Live polling
paused", "Results sweep paused", "ESPN scoring ACTIVE", and Chengdu's next day
reported as "no feed had a schedule". The same pass served a settled Chengdu
doubles side as one player called "[4] GALLOWAY USA / GORANSSON SWE".
"""
import asyncio
from datetime import date
from types import SimpleNamespace

from app.services import (schedule_feeds, schedule_shadow, sofascore,
                          sofascore_doubles, sofascore_live, sofascore_results)
from app.services.schedule import settle_from_result_rows, settled_sides_index


# --- the consumers stand down quietly --------------------------------------

def _run_blocked(monkeypatch, module, monitor):
    logged = []

    async def fake_app_log(level, category, message, **kw):
        logged.append(level)

    async def blocked_sweep(*_a, **_k):
        monitor._stop.set()
        raise sofascore.SofascoreBlocked("403 on /x")

    monkeypatch.setattr(module, "sweep_once", blocked_sweep, raising=False)
    monkeypatch.setattr(module, "poll_once", blocked_sweep, raising=False)
    monkeypatch.setattr(module, "app_log", fake_app_log)
    monkeypatch.setattr(sofascore, "_blocked_until", 0.0)

    async def no_wait(aw, timeout):
        aw.close()

    monkeypatch.setattr(module.asyncio, "wait_for", no_wait)
    asyncio.run(monitor._run())
    return logged


def test_doubles_pause_is_info(monkeypatch):
    got = _run_blocked(monkeypatch, sofascore_doubles,
                       sofascore_doubles.SofascoreDoublesMonitor())
    assert got == ["info"]


def test_results_pause_is_info(monkeypatch):
    mod = sofascore_results
    cls = next(v for k, v in vars(mod).items()
               if isinstance(v, type) and k.endswith("Monitor"))
    assert _run_blocked(monkeypatch, mod, cls()) == ["info"]


def test_no_consumer_warns_on_a_refusal():
    """The live poller's loop takes more wiring to drive; its pause line and
    the ESPN failover are held to the same level at the source."""
    import inspect
    from app.services import espn_monitor
    live = inspect.getsource(sofascore_live)
    assert '"warning", "sofascore_live",\n' not in live
    assert '"info", "sofascore_live",' in live
    espn = inspect.getsource(espn_monitor.ESPNMonitor._scoring_active)
    assert '"warning"' not in espn


# --- no proxy, no "switched to the proxy" ----------------------------------

def test_no_proxy_means_no_switch(monkeypatch):
    logged = []

    async def fake_app_log(*a, **kw):
        logged.append(a)

    monkeypatch.delenv("SOFASCORE_PROXY", raising=False)
    monkeypatch.setattr(sofascore, "app_log", fake_app_log)
    monkeypatch.setattr(sofascore, "_egress_direct", True)
    asyncio.run(sofascore._record_direct_block())
    assert logged == []
    assert sofascore._egress_direct is True


# --- a refused feed day is not a schedule gap -------------------------------

def test_a_refused_feed_is_not_a_feed_that_had_nothing(monkeypatch):
    async def no_event_id(*_a, **_k):
        return None

    async def refused(*_a, **_k):
        raise sofascore.SofascoreBlocked("circuit open for another 3598s")

    monkeypatch.setattr(schedule_shadow, "wta_event_id", no_event_id)
    monkeypatch.setattr(schedule_feeds, "_sofa_parts", refused)
    draw = SimpleNamespace(gender="M", sofa_tournament_id=100, sofa_season_id=200,
                           sofa_doubles_tournament_id=None, sofa_doubles_season_id=None)
    t = SimpleNamespace(id=17, name="Chengdu Open")
    fd = asyncio.run(schedule_feeds.build_day_document(
        None, t, [draw], date(2026, 9, 26), 2026, "Asia/Shanghai"))
    assert "refused" in fd

    from app.services.order_of_play import _pdf_fallback_note
    day = date(2026, 9, 26)
    level, msg, key = _pdf_fallback_note(t, day, {}, {}, {}, {day: fd["refused"]})
    assert (level, key) == ("info", "pdf_refused_17")
    assert "no feed had a schedule" not in msg


# --- a settled team alternative is served as two people ---------------------

class _P:
    def __init__(self, side, position, raw_name, draw_entry_id=None):
        self.side, self.position, self.raw_name = side, position, raw_name
        self.nationality, self.draw_entry_id = None, draw_entry_id


class _Row:
    def __init__(self, a, b, winner_side):
        self.players = ([_P("a", i, n, 100 + i) for i, n in enumerate(a, 1)]
                        + [_P("b", i, n, 200 + i) for i, n in enumerate(b, 1)])
        self.winner_side = winner_side


def test_feed_form_result_still_splits_the_sheet_team():
    """Entry 1545 (feed form) settled entry 1567's side a (sheet form)."""
    idx = settled_sides_index([_Row(["R Galloway", "A Goransson"],
                                    ["A Mannarino", "A Muller"], "a")])
    side = [_P("a", 1, "[4] GALLOWAY USA / GORANSSON SWE"),
            _P("a", 2, "MANNARINO FRA / MULLER FRA")]
    got, ok = settle_from_result_rows(side, idx)
    assert ok
    assert [p.raw_name for p in got] == ["[4] GALLOWAY USA", "GORANSSON SWE"]
    assert [p.draw_entry_id for p in got] == [101, 102]


def test_both_sides_of_a_chinese_wildcard_pair():
    idx = settled_sides_index([_Row(["J Hu", "H Lu"], ["A Wang", "Y Zhou"], "b")])
    side = [_P("b", 1, "[WC] HU CHN / LU CHN"), _P("b", 2, "[WC] WANG CHN / ZHOU CHN")]
    got, ok = settle_from_result_rows(side, idx)
    assert ok and [p.raw_name for p in got] == ["[WC] WANG CHN", "ZHOU CHN"]
