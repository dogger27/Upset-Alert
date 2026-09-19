"""A pass that did not look at a draw has no verdict on it.

2026-09-19, Korea Open 2026: its tournament id (2604) was known and its
Sofascore cuptree was thirty disabled R16P slots, two days before play — the
ordinary "bracket without names" state the coverage check already excuses. The
00:47 pass looked, saw placeholders, and stayed quiet. The 01:47 pass fell
inside the six-hour retry floor, did not look, and so the draw was missing
from that pass's "unnamed" set — which the check read as "named, and nobody
matched", and warned.
"""
import asyncio
import importlib
import pkgutil
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.tournament import Draw, DrawEntry
from app.services import sofa_resolver, sofascore
from app.services.sofascore import _is_placeholder, field_is_unnamed

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")

PLACEHOLDERS = [{"id": 393276 + i, "name": f"R16P{i + 1}", "disabled": True}
                for i in range(30)]


async def _db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _korea(db, *, tid=2604, resolved_ago=None, stamped=0):
    now = datetime.now(timezone.utc)
    d = Draw(name="Korea Open", year=2026, gender="F", draw_size=32,
             wiki_page_title="2026 Korea Open – Singles",
             num_rounds=5, status="upcoming",
             start_date=date.today() + timedelta(days=2),
             end_date=date.today() + timedelta(days=8),
             sofa_tournament_id=tid, sofa_season_id=85584 if tid else None,
             sofa_resolved_at=(now - resolved_ago) if resolved_ago else None)
    db.add(d)
    await db.flush()
    for i, name in enumerate(["Liudmila Samsonova", "Katie Boulter", ""]):
        db.add(DrawEntry(draw_id=d.id, name=name, bracket_position=i + 1,
                         sofa_player_id=(9000 + i) if i < stamped else None))
    await db.commit()
    return d


def _warnings(monkeypatch):
    said = []

    async def _log(level, category, message, *a, **k):
        said.append((level, message))
    monkeypatch.setattr(sofa_resolver, "app_log", _log)
    monkeypatch.setattr(sofascore, "app_log", _log)
    return said


# ------------------------------------------------------------ COVERAGE CHECK

def test_a_pass_that_skipped_the_draw_does_not_warn(monkeypatch):
    """The 01:47 pass: looked at forty minutes ago, not on this pass."""
    async def go():
        engine, Session = await _db()
        said = _warnings(monkeypatch)
        async with Session() as db:
            await _korea(db, resolved_ago=timedelta(minutes=40))
            await sofa_resolver._coverage_check(db, {})
        await engine.dispose()
        return said
    assert asyncio.run(go()) == []


def test_a_draw_nobody_has_looked_at_for_hours_still_warns(monkeypatch):
    """The deferral is one pass, not forever: a last look older than the dark
    cadence means the resolver has stopped looking, which IS the fault."""
    async def go():
        engine, Session = await _db()
        said = _warnings(monkeypatch)
        async with Session() as db:
            await _korea(db, resolved_ago=timedelta(hours=5))
            await sofa_resolver._coverage_check(db, {})
        await engine.dispose()
        return said
    said = asyncio.run(go())
    assert len(said) == 1 and "not one player resolved" in said[0][1]


def test_looked_at_and_named_but_nobody_matched_warns(monkeypatch):
    async def go():
        engine, Session = await _db()
        said = _warnings(monkeypatch)
        async with Session() as db:
            d = await _korea(db, resolved_ago=timedelta(seconds=5))
            await sofa_resolver._coverage_check(db, {d.id: False})
        await engine.dispose()
        return said
    assert len(asyncio.run(go())) == 1


def test_looked_at_and_unnamed_is_quiet(monkeypatch):
    async def go():
        engine, Session = await _db()
        said = _warnings(monkeypatch)
        async with Session() as db:
            d = await _korea(db, resolved_ago=timedelta(seconds=5))
            await sofa_resolver._coverage_check(db, {d.id: True})
        await engine.dispose()
        return said
    assert asyncio.run(go()) == []


def test_no_information_at_all_still_warns(monkeypatch):
    async def go():
        engine, Session = await _db()
        said = _warnings(monkeypatch)
        async with Session() as db:
            await _korea(db, resolved_ago=timedelta(minutes=5))
            await sofa_resolver._coverage_check(db, None)
        await engine.dispose()
        return said
    assert len(asyncio.run(go())) == 1


# ------------------------------------------------------------ RETRY CADENCE

def _record_resolves(monkeypatch):
    looked = []

    async def _resolve(db, draw, *, force=False):
        looked.append(draw.id)
        return {"draw_id": draw.id, "field_unnamed": True}
    monkeypatch.setattr(sofascore, "resolve_draw", _resolve)
    return looked


def test_a_known_id_with_nobody_stamped_is_looked_at_hourly(monkeypatch):
    async def go():
        engine, Session = await _db()
        looked = _record_resolves(monkeypatch)
        async with Session() as db:
            d = await _korea(db, resolved_ago=timedelta(minutes=70))
            await sofascore.resolve_pending_draws(
                db, retry_hours=sofascore.RESOLVE_RETRY_HOURS)
        await engine.dispose()
        return looked, d.id
    looked, did = asyncio.run(go())
    assert looked == [did]


def test_a_partly_stamped_draw_keeps_the_six_hour_floor(monkeypatch):
    """Names Sofascore does not carry do not change hour to hour."""
    async def go():
        engine, Session = await _db()
        looked = _record_resolves(monkeypatch)
        async with Session() as db:
            await _korea(db, resolved_ago=timedelta(minutes=70), stamped=1)
            await sofascore.resolve_pending_draws(
                db, retry_hours=sofascore.RESOLVE_RETRY_HOURS)
        await engine.dispose()
        return looked
    assert asyncio.run(go()) == []


def test_a_dark_draw_looked_at_this_hour_is_left_alone(monkeypatch):
    async def go():
        engine, Session = await _db()
        looked = _record_resolves(monkeypatch)
        async with Session() as db:
            await _korea(db, resolved_ago=timedelta(minutes=20))
            await sofascore.resolve_pending_draws(
                db, retry_hours=sofascore.RESOLVE_RETRY_HOURS)
        await engine.dispose()
        return looked
    assert asyncio.run(go()) == []


# --------------------------------------------------- THE PASS THAT TAKES THE ID

def test_an_id_taken_on_name_alone_reports_the_tree_it_saw(monkeypatch):
    """The name-alone fallback handed back [] for the field, so the very pass
    that took the id called the tree "empty" rather than "unnamed", and the
    coverage check warned on it."""
    async def cands(draw):
        return [{"id": 2604, "name": "Korea Open"}]

    async def season(uid, year):
        return {"id": 85584}

    async def field(uid, season_id):
        return PLACEHOLDERS
    monkeypatch.setattr(sofascore, "_candidate_tournaments", cands)
    monkeypatch.setattr(sofascore, "_season_for", season)
    monkeypatch.setattr(sofascore, "_field_of", field)

    async def go():
        engine, Session = await _db()
        _warnings(monkeypatch)
        async with Session() as db:
            d = await _korea(db, tid=None)
            report = await sofascore.resolve_draw(db, d)
        await engine.dispose()
        return report, d
    report, d = asyncio.run(go())
    assert d.sofa_tournament_id == 2604
    assert report.get("field_unnamed") is True


# ------------------------------------------------------- ONE IDEA OF A SLOT

def test_every_slot_shape_the_tree_resolver_knows_is_a_placeholder():
    """_resolve_against_field calls a tree unpublished by _PLACEHOLDER_SLOT;
    field_is_unnamed must agree, or the tree it took an id on turns into "a
    field nobody matched" on the next pass."""
    for name in ("Qf1", "Qf8", "WQF1", "WSF2", "QFP3", "R16P1"):
        assert _is_placeholder({"name": name}), name
    assert field_is_unnamed([{"name": "Qf1"}, {"name": "WSF2"}])
    assert not _is_placeholder({"name": "Qinwen Zheng"})
    assert not _is_placeholder({"name": "F. Auger-Aliassime"})
