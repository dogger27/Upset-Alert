"""One tournament, two spellings: the WTA's "UniCredit Iasi Open" in "IASI"
against our "Iași Open" in "Iași".

2026-09-21: the WTA season list's first production run logged "Ambiguous
tournament match — 'UniCredit Iasi Open' 2026 skipped". find_existing_match
compared names and cities with lower(), which keeps the ș, so four WTA 250s
that week all disagreed and it reported a tie — and then wta_season's city
fallback matched the draw a line later. The alarm was about a match that
succeeded. Names and cities now fold, and a tie the caller's fallback breaks
is never reported.
"""
import asyncio
import importlib
import pkgutil
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
import app.services.system_log as system_log
from app.database import Base
from app.models.tournament import Draw
from app.services.discovery import DiscoveredTournament
from app.services.tournament_sync import _find_duplicates, find_existing_match, fold

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")

WEEK = (("Iași Open", "Iași", date(2026, 7, 13)), ("Athens Open", "Athens", date(2026, 7, 13)),
        ("Prague Open", "Prague", date(2026, 7, 20)), ("Hamburg Open", "Hamburg", date(2026, 7, 20)))


@pytest.fixture
def logged(monkeypatch):
    rows = []

    async def _log(level, category, message, *a, **k):
        rows.append((level, category, message))
    monkeypatch.setattr(system_log, "app_log", _log)
    return rows


async def _db(draws=WEEK):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        for name, city, start in draws:
            db.add(Draw(name=name, year=2026, gender="F", draw_size=32, num_rounds=5, category="WTA 250",
                        wiki_page_title=f"2026 {name} – Women's singles", start_date=start,
                        end_date=start + timedelta(days=6), city=city))
        await db.commit()
    return engine, Session


def _discovered(name="UniCredit Iasi Open", city="Iasi"):
    return DiscoveredTournament(name=name, year=2026, gender="F", surface="Clay", category="WTA 250",
                                draw_size=32, wiki_page_title=f"2026 {name} – Singles",
                                start_date=date(2026, 7, 13), end_date=date(2026, 7, 19), city=city)


@pytest.mark.parametrize("a,b", [("Iași", "IASI"), ("Iași", "Iasi"), ("Bogotá", "BOGOTA"),
                                 ("São Paulo", "Sao  Paulo"), ("Łódź", "Łodz")])
def test_fold_reads_two_spellings_of_one_place_as_one(a, b):
    assert fold(a) == fold(b)


def test_the_sponsored_ascii_spelling_finds_our_draw_without_a_tie(logged):
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            d = await find_existing_match(db, _discovered(), 2026)
            assert d is not None and d.name == "Iași Open"
        await engine.dispose()
    asyncio.run(go())
    assert logged == []


@pytest.mark.parametrize("name,city", [("UniCredit Iasi Open", None),      # the name alone, folded
                                       ("Some Sponsor Cup", "IASI")])      # the city alone, folded
def test_either_the_name_or_the_city_is_enough_once_folded(logged, name, city):
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            d = await find_existing_match(db, _discovered(name, city), 2026)
            assert d is not None and d.name == "Iași Open"
        await engine.dispose()
    asyncio.run(go())
    assert logged == []


def test_a_tie_the_callers_fallback_breaks_is_not_reported(logged):
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            iasi = next(d for d in (await db.execute(Draw.__table__.select())).all() if d.name == "Iași Open")

            async def by_hand(db, d, year):
                return await db.get(Draw, iasi.id)
            d = await find_existing_match(db, _discovered("Some Sponsor Cup", "Elsewhere"), 2026, fallback=by_hand)
            assert d is not None and d.name == "Iași Open"
        await engine.dispose()
    asyncio.run(go())
    assert logged == []


def test_a_tie_nothing_breaks_is_still_reported(logged):
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            async def nothing(db, d, year):
                return None
            assert await find_existing_match(db, _discovered("Some Sponsor Cup", "Elsewhere"), 2026,
                                             fallback=nothing) is None
        await engine.dispose()
    asyncio.run(go())
    assert [(lv, cat) for lv, cat, _ in logged] == [("warning", "discovery")]
    assert "Ambiguous tournament match" in logged[0][2]


def test_the_wta_list_run_that_raised_the_alarm_is_now_silent(logged):
    """The production case end to end: sync_wta_season on the four-250 week."""
    from app.models.tournament import Tournament
    from app.services import wta_season

    async def go():
        engine, Session = await _db(draws=())
        async with Session() as db:
            for name, city, start in WEEK:
                t = Tournament(name=name, year=2026); db.add(t); await db.flush()
                db.add(Draw(name=name, year=2026, gender="F", draw_size=32, num_rounds=5, category="WTA 250",
                            wiki_page_title=f"2026 {name} – Women's singles", start_date=start,
                            end_date=start + timedelta(days=6), city=city, tournament_id=t.id))
            await db.commit()
            ev = {"title": "UniCredit Iasi Open - Iasi, ROU", "tournamentGroup": {"name": "IASI"},
                  "level": "WTA 250", "startDate": "2026-07-13", "endDate": "2026-07-19", "city": "IASI",
                  "country": "ROU", "surface": "Clay", "singlesDrawSize": 32, "liveScoringId": "2063", "year": 2026}
            r = await wta_season.sync_wta_season(db, 2026, events=[ev], today=date(2026, 9, 21))
            assert r["created"] == 0 and r["keyed"] == 1
        await engine.dispose()
    asyncio.run(go())
    assert logged == []


def test_a_duplicate_spelled_two_ways_is_still_a_duplicate():
    async def go():
        engine, Session = await _db(draws=WEEK + (("UniCredit Iasi Open", "Iasi", date(2026, 7, 13)),))
        async with Session() as db:
            dups = await _find_duplicates(db, 2026)
            assert ("WTA 250", "F", date(2026, 7, 13), 2) in [tuple(d) for d in dups]
        await engine.dispose()
    asyncio.run(go())
