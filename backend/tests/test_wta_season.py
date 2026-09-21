"""The WTA's own season list as discovery and date authority for the women's tour.

The fixture is the real September–November 2026 window captured 2026-09-21,
trimmed to its fields, with one ITF row kept so the level filter is exercised.
Expected names and dates are what production held, built from Wikipedia — so
each assertion is agreement between the tour and the page it replaces.
"""
import asyncio
import importlib
import json
import pkgutil
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.tournament import Draw, Tournament
from app.services import wta_season
from app.services.discovery import DiscoveredTournament
from app.services.tournament_sync import _apply_update, official_dates

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")

FIX = json.loads((Path(__file__).parent / "fixtures" / "wta_season_2026_sep_nov.json").read_text(encoding="utf-8"))
EVENTS = FIX["content"]


# ── names ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,group,expected", [
    ("Korea Open - Seoul, KOR", "SEOUL", "Korea Open"),
    ("China Open - Beijing, CHN", "BEIJING", "China Open"),
    ("SP Open - Sao Paulo, BRA", "SAO PAULO", "SP Open"),
    ("Guadalajara Open presentado por Santander - Guadalajara, MEX", "GUADALAJARA 500", "Guadalajara Open"),
    ("Singapore Tennis Open presented by BNP Paribas - Singapore, SIN", "SINGAPORE", "Singapore Tennis Open"),
    ("Kinoshita Group Japan Open - Osaka, JPN", "OSAKA", "Kinoshita Group Japan Open"),   # a leading sponsor stays
    ("", "HONG KONG", "Hong Kong"),                                                        # no title: the group, cased
])
def test_the_name_is_the_title_without_its_location_or_trailing_sponsor(title, group, expected):
    assert wta_season.clean_name(title, group) == expected


# ── the list ──────────────────────────────────────────────────────────────

def test_fetch_season_pages_until_a_short_page_and_keeps_only_the_tour():
    pages = {0: {"content": [dict(e, year=2026) for e in EVENTS]}}      # a short page: stops
    asked = []
    def fake(url):
        asked.append(url); return pages.get(len(asked) - 1, {"content": []})
    got = wta_season.fetch_season(2026, fetch=fake)
    assert len(asked) == 1
    assert all(i["level"] in wta_season.TOUR_LEVELS for i in got)
    assert len(got) == len(EVENTS) - 1                                   # the ITF row is gone


def test_fetch_season_keeps_paging_through_full_pages():
    full = [dict(EVENTS[0], year=2026) for _ in range(wta_season.PAGE)]
    seq = [{"content": full}, {"content": full}, {"content": [dict(EVENTS[1], year=2026)]}]
    got = wta_season.fetch_season(2026, fetch=lambda url: seq.pop(0))
    assert len(got) == 2 * wta_season.PAGE + 1


def test_to_discovered_carries_every_field_discovery_used_to_read_off_wikipedia():
    korea = next(e for e in EVENTS if "Korea Open" in (e.get("title") or ""))
    d = wta_season.to_discovered(korea)
    assert (d.name, d.gender, d.year) == ("Korea Open", "F", 2026)
    assert d.category == "WTA 250" and d.draw_size == 32
    assert (d.start_date, d.end_date) == (date(2026, 9, 21), date(2026, 9, 27))
    assert d.city == "Seoul" and d.country == "KOR" and d.surface == "Hard"
    assert d.wta_id == 1024 and d.title_is_guess
    assert d.wiki_page_title == "2026 Korea Open – Singles"


def test_an_event_without_an_id_cannot_be_keyed():
    e = dict(EVENTS[0]); e["liveScoringId"] = ""
    assert wta_season.to_discovered(e) is None


def test_the_official_dates_are_our_main_draw_dates():
    """Guadalajara, Seoul, Singapore, Beijing — the dates production held."""
    by = {wta_season.to_discovered(e).wta_id: wta_season.to_discovered(e)
          for e in EVENTS if e["level"] in wta_season.TOUR_LEVELS}
    assert (by[2075].start_date, by[2075].end_date) == (date(2026, 9, 13), date(2026, 9, 19))
    assert (by[1024].start_date, by[1024].end_date) == (date(2026, 9, 21), date(2026, 9, 27))
    assert (by[1152].start_date, by[1152].end_date) == (date(2026, 9, 21), date(2026, 9, 27))
    assert (by[1020].start_date, by[1020].end_date) == (date(2026, 9, 30), date(2026, 10, 11))


# ── the sync, on a real database ─────────────────────────────────────────

async def _db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _event(lsid):
    return next(e for e in EVENTS if str(e.get("liveScoringId")) == str(lsid))


def test_a_draw_we_do_not_hold_is_created_and_keyed():
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            r = await wta_season.sync_wta_season(db, 2026, events=[_event(1024)], today=date(2026, 9, 1))
            await db.commit()
            assert r["created"] == 1 and r["seen"] == 1
            d = (await db.execute(select(Draw).where(Draw.name == "Korea Open"))).scalar_one()
            assert (d.gender, d.category, d.draw_size) == ("F", "WTA 250", 32)
            assert d.start_date == date(2026, 9, 21) and d.city == "Seoul"
            t = await db.get(Tournament, d.tournament_id)
            assert t.wta_live_scoring_id == 1024
            assert await official_dates(db, d)
        await engine.dispose()
    asyncio.run(go())


def test_a_draw_we_hold_by_name_is_keyed_and_dated_but_keeps_its_name_and_title():
    """Sponsors: the API says 'Singapore Tennis Open presented by BNP Paribas';
    we hold 'Singapore Open' under a resolved Wikipedia title. Both stay."""
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            t = Tournament(name="Singapore Open", year=2026)
            db.add(t); await db.flush()
            d = Draw(name="Singapore Open", year=2026, gender="F", draw_size=28, num_rounds=5,
                     category="WTA 500", wiki_page_title="2026 Singapore Tennis Open – Singles",
                     start_date=date(2026, 9, 22), end_date=date(2026, 9, 27), tournament_id=t.id)
            db.add(d); await db.commit()
            r = await wta_season.sync_wta_season(db, 2026, events=[_event(1152)], today=date(2026, 9, 1))
            await db.commit()
            d = await db.get(Draw, d.id)
            assert r["keyed"] == 1 and r["created"] == 0
            assert (await db.get(Tournament, t.id)).wta_live_scoring_id == 1152
            assert d.name == "Singapore Open"
            assert d.wiki_page_title == "2026 Singapore Tennis Open – Singles"
            assert d.start_date == date(2026, 9, 21), "the official Monday replaces our Tuesday"
        await engine.dispose()
    asyncio.run(go())


def test_a_released_draws_start_never_moves_earlier_to_a_day_already_reached():
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            t = Tournament(name="Korea Open", year=2026, wta_live_scoring_id=1024)
            db.add(t); await db.flush()
            d = Draw(name="Korea Open", year=2026, gender="F", draw_size=32, num_rounds=5,
                     category="WTA 250", wiki_page_title="2026 Korea Open – Singles",
                     start_date=date(2026, 9, 22), end_date=date(2026, 9, 27), tournament_id=t.id,
                     draw_released_direct_at=date(2026, 9, 19))
            db.add(d); await db.commit()
            await wta_season.sync_wta_season(db, 2026, events=[_event(1024)], today=date(2026, 9, 21))
            assert (await db.get(Draw, d.id)).start_date == date(2026, 9, 22), "would have locked picks"
        await engine.dispose()
    asyncio.run(go())


def test_an_end_date_never_moves_backwards_past_observed_play():
    """SP Open: the list said 20 September; the rain-delayed final was on the 21st."""
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            t = Tournament(name="SP Open", year=2026, wta_live_scoring_id=1139)
            db.add(t); await db.flush()
            d = Draw(name="SP Open", year=2026, gender="F", draw_size=32, num_rounds=5,
                     category="WTA 250", wiki_page_title="2026 SP Open – Singles",
                     start_date=date(2026, 9, 14), end_date=date(2026, 9, 21), tournament_id=t.id)
            db.add(d); await db.commit()
            await wta_season.sync_wta_season(db, 2026, events=[_event(1139)], today=date(2026, 9, 21))
            assert (await db.get(Draw, d.id)).end_date == date(2026, 9, 21)
        await engine.dispose()
    asyncio.run(go())


def test_an_active_draws_dates_are_frozen():
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            t = Tournament(name="Korea Open", year=2026, wta_live_scoring_id=1024)
            db.add(t); await db.flush()
            d = Draw(name="Korea Open", year=2026, gender="F", draw_size=32, num_rounds=5,
                     category="WTA 250", wiki_page_title="2026 Korea Open – Singles", status="active",
                     start_date=date(2026, 9, 22), end_date=date(2026, 9, 28), tournament_id=t.id)
            db.add(d); await db.commit()
            await wta_season.sync_wta_season(db, 2026, events=[_event(1024)], today=date(2026, 9, 23))
            fresh = await db.get(Draw, d.id)
            assert fresh.start_date == date(2026, 9, 22)
        await engine.dispose()
    asyncio.run(go())


def test_wikipedias_season_sync_no_longer_moves_dates_the_tour_owns():
    """_apply_update, on a draw whose tournament carries a WTA id, leaves the
    dates alone even when Wikipedia's page says otherwise."""
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            t = Tournament(name="Korea Open", year=2026, wta_live_scoring_id=1024)
            db.add(t); await db.flush()
            d = Draw(name="Korea Open", year=2026, gender="F", draw_size=32, num_rounds=5,
                     category="WTA 250", wiki_page_title="2026 Korea Open – Singles",
                     start_date=date(2026, 9, 21), end_date=date(2026, 9, 27), tournament_id=t.id)
            db.add(d); await db.commit()
            wiki = DiscoveredTournament(name="Korea Open", year=2026, gender="F", surface="Hard",
                                        category="WTA 250", draw_size=32,
                                        wiki_page_title="2026 Korea Open – Singles",
                                        start_date=date(2026, 10, 5), end_date=date(2026, 10, 11))
            await _apply_update(d, wiki, db)
            assert d.start_date == date(2026, 9, 21) and d.end_date == date(2026, 9, 27)
        await engine.dispose()
    asyncio.run(go())


def test_a_team_event_is_not_a_draw_whatever_its_size_says():
    """United Cup sits at WTA 500 in the list with singlesDrawSize 0; the dry
    run against production would have created it as a draw."""
    e = dict(EVENTS[0]); e.update(title="United Cup - Perth, AUS", tournamentGroup={"name": "UNITED CUP"},
                                  singlesDrawSize=0, liveScoringId="9999")
    assert wta_season.to_discovered(e) is None


def test_a_missing_size_is_not_a_team_event():
    """The tour lists Eastbourne 2026 with both draw sizes 0 — a data gap, and
    the one women's draw left unkeyed after the first production run because
    the size filter threw it away. Kept, keyed, never resized, never created."""
    e = dict(EVENTS[0]); e.update(title="Lexus Eastbourne Open - Eastbourne, GBR", tournamentGroup={"name": "EASTBOURNE"},
                                  level="WTA 250", startDate="2026-06-22", endDate="2026-06-27", city="EASTBOURNE",
                                  singlesDrawSize=0, doublesDrawSize=0, liveScoringId="710", year=2026)
    d = wta_season.to_discovered(e)
    assert d is not None and d.wta_id == 710 and d.draw_size == 0

    async def go():
        engine, Session = await _db()
        async with Session() as db:
            t = Tournament(name="Eastbourne Open", year=2026); db.add(t); await db.flush()
            db.add(Draw(name="Eastbourne Open", year=2026, gender="F", draw_size=32, num_rounds=5, category="WTA 250",
                        wiki_page_title="2026 Eastbourne Open – Women's singles", start_date=date(2026, 6, 22),
                        end_date=date(2026, 6, 27), city="Eastbourne", tournament_id=t.id))
            await db.commit()
            r = await wta_season.sync_wta_season(db, 2026, events=[e], today=date(2026, 6, 1)); await db.commit()
            d = (await db.execute(select(Draw).where(Draw.name == "Eastbourne Open"))).scalar_one()
            assert r["keyed"] == 1 and r["created"] == 0
            assert (await db.get(Tournament, t.id)).wta_live_scoring_id == 710
            assert d.draw_size == 32, "a 0 from the list must not shrink the draw"
        async with Session() as db:          # and with no draw to match, nothing is created
            # A different city and week, so neither the name nor the city
            # tie-break can find the Eastbourne draw created above.
            stranger = dict(e, title="Nowhere Open - Nowhere, XXX", tournamentGroup={"name": "NOWHERE"},
                            city="NOWHERE", startDate="2026-08-03", endDate="2026-08-09", liveScoringId="711")
            r = await wta_season.sync_wta_season(db, 2026, events=[stranger], today=date(2026, 6, 1))
            assert r["created"] == 0 and r.get("unsized") == 1
        await engine.dispose()
    asyncio.run(go())


def test_a_sponsored_name_still_finds_our_draw_by_city_that_week():
    """'UniCredit Iasi Open' against our 'Iași Open': the name fails, four WTA
    250s share the week, and the tour's city — diacritics folded — decides."""
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            for name, city, start in (("Iași Open", "Iași", date(2026, 7, 13)), ("Athens Open", "Athens", date(2026, 7, 13)),
                                      ("Prague Open", "Prague", date(2026, 7, 20)), ("Hamburg Open", "Hamburg", date(2026, 7, 20))):
                t = Tournament(name=name, year=2026); db.add(t); await db.flush()
                db.add(Draw(name=name, year=2026, gender="F", draw_size=32, num_rounds=5, category="WTA 250",
                            wiki_page_title=f"2026 {name} – Singles", start_date=start,
                            end_date=start + (date(2026, 7, 19) - date(2026, 7, 13)), city=city, tournament_id=t.id))
            await db.commit()
            ev = dict(EVENTS[0]); ev.update(title="UniCredit Iasi Open - Iasi, ROU", tournamentGroup={"name": "IASI"},
                                            level="WTA 250", startDate="2026-07-13", endDate="2026-07-19",
                                            city="IASI", country="ROU", singlesDrawSize=32, liveScoringId="2101", year=2026)
            r = await wta_season.sync_wta_season(db, 2026, events=[ev], today=date(2026, 6, 1))
            await db.commit()
            assert r["created"] == 0 and r["keyed"] == 1
            d = (await db.execute(select(Draw).where(Draw.name == "Iași Open"))).scalar_one()
            assert (await db.get(Tournament, d.tournament_id)).wta_live_scoring_id == 2101
        await engine.dispose()
    asyncio.run(go())
