"""Identifying a draw with no field, without earning a block.

NOT GETTING BLOCKED IS THE FIRST REQUIREMENT (owner, 2026-09-21). The identity
path is the easiest place in this project to earn one: it is reached from the
WikiPageNotFound branch of _refresh_active_tournaments, which fires every 30
minutes for every draw with no article, for the whole polling window. So the
request count is a tested property here, not a hope — the counter below is the
point of the suite.
"""
import asyncio
import json

import pytest

from app.services import sofascore as sf
from app.services.sofa_draw_shape import main_draw_start


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sf, "_SOFA_CACHE_DIR", str(tmp_path / "sofa"))
    return tmp_path


@pytest.fixture
def counted(monkeypatch):
    """Replace the network with a counter, so traffic is measurable."""
    calls: list = []

    def install(responses: dict):
        async def fake(path):
            calls.append(path)
            if path not in responses:
                raise sf.SofascoreNotFound(f"404 on {path}")
            return responses[path]
        monkeypatch.setattr(sf, "_get", fake)
        return calls
    return install


# ── the cache ─────────────────────────────────────────────────────────────

def test_a_second_read_inside_the_ttl_makes_no_request(cache_dir, counted):
    calls = counted({"/x": {"ok": 1}})

    async def go():
        a = await sf._get_cached("/x", 3600)
        b = await sf._get_cached("/x", 3600)
        return a, b

    a, b = asyncio.run(go())
    assert a == b == {"ok": 1}
    assert len(calls) == 1, calls


def test_an_expired_entry_is_refetched(cache_dir, counted):
    calls = counted({"/x": {"ok": 1}})

    async def go():
        await sf._get_cached("/x", 3600)
        await sf._get_cached("/x", 0)        # nothing is fresh at ttl 0
    asyncio.run(go())
    assert len(calls) == 2


def test_a_404_is_remembered_and_re_raised_without_asking_again(cache_dir, counted):
    """The answer we get MOST often is "no cup tree yet". Re-asking every pass
    is what would earn the block."""
    calls = counted({})

    async def go():
        for _ in range(5):
            with pytest.raises(sf.SofascoreNotFound):
                await sf._get_cached("/missing", 3600)
    asyncio.run(go())
    assert len(calls) == 1, calls


def test_a_cached_404_is_indistinguishable_from_a_live_one(cache_dir, counted):
    counted({})

    async def go():
        with pytest.raises(sf.SofascoreNotFound):
            await sf._get_cached("/missing", 3600)
        with pytest.raises(sf.SofascoreNotFound):
            await sf._get_cached("/missing", 3600)
    asyncio.run(go())


def test_a_404_stops_being_remembered_after_its_own_shorter_ttl(cache_dir, counted, monkeypatch):
    """A negative entry must expire faster than a positive one: it is the only
    thing standing between us and noticing a draw was published."""
    monkeypatch.setattr(sf, "CACHE_TTL_NOT_FOUND", 0.0)
    calls = counted({})

    async def go():
        for _ in range(3):
            with pytest.raises(sf.SofascoreNotFound):
                await sf._get_cached("/missing", 86400)
    asyncio.run(go())
    assert len(calls) == 3


def test_an_unwritable_cache_is_not_a_failure(counted, monkeypatch):
    monkeypatch.setattr(sf, "_SOFA_CACHE_DIR", "/proc/definitely/not/writable")
    calls = counted({"/x": {"ok": 1}})

    async def go():
        return await sf._get_cached("/x", 3600)

    assert asyncio.run(go()) == {"ok": 1}
    assert len(calls) == 1


def test_different_paths_do_not_share_an_entry(cache_dir, counted):
    calls = counted({"/a": {"v": "a"}, "/b": {"v": "b"}})

    async def go():
        return await sf._get_cached("/a", 3600), await sf._get_cached("/b", 3600)

    a, b = asyncio.run(go())
    assert a["v"] == "a" and b["v"] == "b"
    assert len(calls) == 2


def test_the_negative_ttl_is_the_shortest_of_the_three():
    """Ordering is the whole design: remember a miss briefly, a hit for longer."""
    assert sf.CACHE_TTL_NOT_FOUND < sf.CACHE_TTL_CUPTREE
    assert sf.CACHE_TTL_CUPTREE < sf.CACHE_TTL_SEARCH
    assert sf.CACHE_TTL_SEASONS >= sf.CACHE_TTL_CUPTREE


# ── the geometry check that stands in for the field ───────────────────────

@pytest.mark.parametrize("n,expected", [
    (28, 32), (32, 32), (30, 32), (48, 64), (56, 64), (96, 128), (128, 128),
    (8, 8), (1, 1),
])
def test_the_bracket_a_field_plays_in(n, expected):
    assert sf._next_power_of_two(n) == expected


def test_geometry_agrees_for_both_meanings_of_draw_size():
    """draws.draw_size is recorded both ways in practice — discovery stores the
    entrant count (28) and a scrape normalises it to the bracket (32) — so
    rounding both to the next power of two has to accept either."""
    assert sf._geometry_agrees(28, 32) is True
    assert sf._geometry_agrees(32, 32) is True
    assert sf._geometry_agrees(96, 128) is True
    assert sf._geometry_agrees(128, 128) is True


def test_geometry_separates_a_250_from_a_1000():
    assert sf._geometry_agrees(28, 128) is False
    assert sf._geometry_agrees(96, 32) is False


@pytest.mark.parametrize("a,b", [(0, 32), (28, 0), (None, 32), (28, None)])
def test_geometry_refuses_to_judge_on_nothing(a, b):
    assert sf._geometry_agrees(a, b) is False


# ── the date the cup tree states ─────────────────────────────────────────

def test_the_start_date_comes_from_the_cup_trees_own_timestamps():
    """/events/next 404s on a finished tournament, which is how the date check
    first failed — against Guadalajara. The cup tree carries the dates."""
    payload = {"cupTrees": [{"name": "2026 Somewhere", "rounds": [{"blocks": [
        {"seriesStartDateTimestamp": 1789419600},
        {"seriesStartDateTimestamp": 1789326300},     # the earliest
        {"matchesInRound": 0},
    ]}]}]}
    from datetime import datetime, timezone
    assert main_draw_start(payload) == datetime.fromtimestamp(
        1789326300, tz=timezone.utc).date()


def test_no_timestamps_is_no_date_rather_than_a_wrong_one():
    payload = {"cupTrees": [{"name": "X", "rounds": [{"blocks": [{"order": 1}]}]}]}
    assert main_draw_start(payload) is None
    assert main_draw_start({"cupTrees": []}) is None


def test_the_qualifying_tree_does_not_supply_the_main_draws_date():
    payload = {"cupTrees": [
        {"name": "2026 X, Qualifying", "rounds": [
            {"blocks": [{"seriesStartDateTimestamp": 1}]}]},
        {"name": "2026 X", "rounds": [
            {"blocks": [{"seriesStartDateTimestamp": 1789326300}]}]},
    ]}
    from datetime import datetime, timezone
    assert main_draw_start(payload) == datetime.fromtimestamp(
        1789326300, tz=timezone.utc).date()


# ── the budget, measured end to end ──────────────────────────────────────

@pytest.fixture
def guadalajara(monkeypatch, cache_dir):
    """The real captured cup tree, plus the search and season responses that
    lead to it — so a whole identity attempt can be counted."""
    import pathlib
    from datetime import date
    from app.models.tournament import Draw

    fixture = json.loads(
        (pathlib.Path(__file__).parent / "fixtures"
         / "cuptree_guadalajara_2026.json").read_text(encoding="utf-8"))
    # The fixture was trimmed of timestamps; identity needs one date.
    fixture["cupTrees"][0]["rounds"][0]["blocks"][0]["seriesStartDateTimestamp"] = 1789326300

    responses = {
        "/search/unique-tournaments?q=Guadalajara%20Open": {"results": [
            {"entity": {"id": 16559, "name": "Guadalajara",
                        "category": {"name": "WTA"}, "userCount": 1,
                        "slug": "guadalajara"}}]},
        "/search/unique-tournaments?q=Guadalajara": {"results": []},
        "/unique-tournament/16559/seasons": {"seasons": [
            {"id": 85638, "name": "WTA Guadalajara 2026", "year": "2026"}]},
        "/unique-tournament/16559/season/85638/cuptrees": fixture,
    }
    calls: list = []

    async def fake(path):
        calls.append(path)
        if path not in responses:
            raise sf.SofascoreNotFound(f"404 on {path}")
        return responses[path]

    monkeypatch.setattr(sf, "_get", fake)
    draw = Draw(id=142, name="Guadalajara Open", year=2026, gender="F",
                draw_size=28, num_rounds=5, wiki_page_title="x",
                start_date=date(2026, 9, 13), end_date=date(2026, 9, 19),
                city="Guadalajara")
    return draw, calls


def test_identity_resolves_from_the_cup_tree_alone(guadalajara):
    draw, _ = guadalajara
    found = asyncio.run(sf.resolve_without_field(draw))
    assert found is not None
    uid, season_id, shape = found
    assert (uid, season_id) == (16559, 85638)
    assert shape.bracket_size == 32 and shape.entrant_count == 28
    assert shape.byes == [2, 10, 24, 32]


def test_a_whole_identity_attempt_costs_four_requests(guadalajara):
    draw, calls = guadalajara
    asyncio.run(sf.resolve_without_field(draw))
    assert len(calls) == 4, calls


def test_every_repeat_attempt_inside_the_ttl_costs_NOTHING(guadalajara):
    """THE PROPERTY THAT KEEPS US UNBLOCKED. This is reached every 30 minutes
    for the whole polling window; un-cached that is ~192 requests a day to
    answer a question whose answer changes once."""
    draw, calls = guadalajara
    asyncio.run(sf.resolve_without_field(draw))
    calls.clear()

    async def again():
        for _ in range(10):
            await sf.resolve_without_field(draw)

    asyncio.run(again())
    assert calls == [], calls


def test_a_draw_with_nothing_to_corroborate_asks_nothing_at_all(guadalajara):
    """No dates or no draw_size means no evidence, so it must not even search."""
    draw, calls = guadalajara
    draw.start_date = None
    assert asyncio.run(sf.resolve_without_field(draw)) is None
    assert calls == []
    draw.start_date, draw.draw_size = __import__("datetime").date(2026, 9, 13), 0
    assert asyncio.run(sf.resolve_without_field(draw)) is None
    assert calls == []


def test_a_wrong_sized_bracket_is_refused(guadalajara):
    """The geometry check is what stands in for the field. A 96-entrant draw
    cannot be this 32 bracket, however well the name matches."""
    draw, _ = guadalajara
    draw.draw_size = 96
    assert asyncio.run(sf.resolve_without_field(draw)) is None


def test_a_date_far_from_ours_is_refused(guadalajara):
    """Two events sharing a city's name in one year were 25 to 307 days apart;
    this is the check that keeps January's Hong Kong out of November's slot."""
    draw, _ = guadalajara
    draw.start_date = __import__("datetime").date(2026, 11, 2)
    assert asyncio.run(sf.resolve_without_field(draw)) is None


def test_the_cache_lives_where_a_container_recreate_cannot_wipe_it():
    """/tmp is the container's writable layer and deploy.sh runs `up` on every
    backend push, which discards it — so a cache there would be cold again
    within minutes. /data is a host bind mount."""
    import app.services.sofascore as live
    assert live._SOFA_CACHE_DIR.startswith("/data/"), live._SOFA_CACHE_DIR
