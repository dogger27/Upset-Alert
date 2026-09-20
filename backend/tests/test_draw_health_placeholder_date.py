"""The draw-health check must not accuse a draw on a date no page confirmed.

2026-09-20, 00:12:36 UTC: `_check_draw_health` reported "Wiki page never
resolved" for 2026 Chengdu Open and 2026 Hangzhou Open. Six seconds later, at
00:12:42, `_refresh_dates_from_event_page` — a completely separate job — moved
both start dates from 21 September to the real 23 September, which put the
release deadline two days in the future and the alarm firmly in the wrong.

The two jobs run on 60- and 30-minute intervals, both registered at startup, so
their ticks coincide every hour for the life of the process; the health check
is a fast DB-only loop and wins that race every time. But the ordering is only
the trigger. The fault is that Check 2's own precondition — wiki_page_id is
None, i.e. no page has ever been parsed — GUARANTEES start_date is still
discovery's week-Monday placeholder, so the one date the check judges on is the
one date it knows nobody has confirmed. (2026 Cincinnati fired the identical
signature on 2026-08-09, three times, for the same reason.)

So the check asks the event page itself before it accuses the title.
"""
import asyncio
import importlib
import pkgutil
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
import app.services.scheduler as sched
import app.services.scraper as scraper
from app.database import Base
from app.models.tournament import Draw, Tournament
from app.services.draw_dates import release_deadline

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")


TODAY = date.today()


async def _db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _chengdu(db, *, start_date, wiki_page_id=None):
    """Chengdu's shape on the morning it alarmed: no page, release date passed,
    and a start_date that is whatever the caller says discovery left behind."""
    t = Tournament(name="Chengdu Open", year=TODAY.year)
    db.add(t)
    await db.flush()
    d = Draw(tournament_id=t.id, name="Chengdu Open", year=TODAY.year, gender="M",
             draw_size=32, num_rounds=5, category="ATP 250", status="upcoming",
             wiki_page_title=f"{TODAY.year} Chengdu Open – Singles",
             wiki_page_id=wiki_page_id,
             start_date=start_date, end_date=start_date + timedelta(days=6),
             draw_release_direct=TODAY - timedelta(days=1))
    db.add(d)
    await db.commit()
    return d


def _run(monkeypatch, *, stored_start, event_page_start):
    """One _check_draw_health pass; returns every app_log call it made."""
    said = []

    async def _log(level, category, message, detail=None, **kw):
        said.append((level, message, detail or {}))

    async def _event_dates(title, year, gender=""):
        return event_page_start, (event_page_start + timedelta(days=6)
                                  if event_page_start else None)

    monkeypatch.setattr(sched, "app_log", _log, raising=False)
    monkeypatch.setattr("app.services.system_log.app_log", _log)
    monkeypatch.setattr(scraper, "fetch_event_dates", _event_dates)

    async def go():
        engine, Session = await _db()
        monkeypatch.setattr(sched, "AsyncSessionLocal", Session)
        async with Session() as db:
            await _chengdu(db, start_date=stored_start)
        await sched._check_draw_health()
        await engine.dispose()
    asyncio.run(go())
    return said


def test_the_placeholder_start_date_is_not_grounds_for_an_alarm(monkeypatch):
    """Chengdu exactly: stored 21 Sep (deadline today), event page says 23 Sep."""
    said = _run(monkeypatch,
                stored_start=TODAY + timedelta(days=1),
                event_page_start=TODAY + timedelta(days=3))
    assert not [m for lvl, m, _ in said if lvl in ("error", "warning")], said
    stood_down = [d for lvl, m, d in said
                  if lvl == "info" and "on schedule" in m]
    assert len(stood_down) == 1
    assert stood_down[0]["event_page_start_date"] == str(TODAY + timedelta(days=3))


def test_a_genuinely_dead_title_still_gets_reported(monkeypatch):
    """The check keeps its teeth: the event page agrees play starts tomorrow,
    the draw was due yesterday, and no page has ever resolved — Iași Open's
    case, which is the whole reason Check 2 exists."""
    said = _run(monkeypatch,
                stored_start=TODAY + timedelta(days=1),
                event_page_start=TODAY + timedelta(days=1))
    errors = [m for lvl, m, _ in said if lvl == "error"]
    assert len(errors) == 1 and "never resolved" in errors[0]


def test_an_unreadable_event_page_is_not_a_reason_to_go_quiet(monkeypatch):
    """A title so wrong the event page cannot be fetched either is the strongest
    evidence there is. Falling back to the stored date must still alarm."""
    said = _run(monkeypatch,
                stored_start=TODAY + timedelta(days=1),
                event_page_start=None)
    errors = [m for lvl, m, _ in said if lvl == "error"]
    assert len(errors) == 1 and "never resolved" in errors[0]


def test_nothing_is_said_before_the_draw_is_due(monkeypatch):
    """No fetch, no info line, no error — the ordinary state of every upcoming
    draw, and it must stay free of both alarms and chatter."""
    def _boom(*a, **k):
        raise AssertionError("the event page must not be fetched before the deadline")
    monkeypatch.setattr(scraper, "fetch_event_dates", _boom)
    said = []

    async def _log(level, category, message, detail=None, **kw):
        said.append((level, message))
    monkeypatch.setattr(sched, "app_log", _log, raising=False)
    monkeypatch.setattr("app.services.system_log.app_log", _log)

    async def go():
        engine, Session = await _db()
        monkeypatch.setattr(sched, "AsyncSessionLocal", Session)
        async with Session() as db:
            await _chengdu(db, start_date=TODAY + timedelta(days=10))
        await sched._check_draw_health()
        await engine.dispose()
    asyncio.run(go())
    assert said == []


def test_confirm_start_date_prefers_the_page_and_falls_back_to_the_row(monkeypatch):
    stored = TODAY + timedelta(days=1)
    page = TODAY + timedelta(days=3)

    async def _found(title, year, gender=""):
        return page, page + timedelta(days=6)

    async def _nothing(title, year, gender=""):
        return None, None

    monkeypatch.setattr(scraper, "fetch_event_dates", _found)
    assert asyncio.run(scraper.confirm_start_date("t", TODAY.year, "M", stored)) == page
    monkeypatch.setattr(scraper, "fetch_event_dates", _nothing)
    assert asyncio.run(scraper.confirm_start_date("t", TODAY.year, "M", stored)) == stored


def test_the_deadline_the_two_dates_produce_is_what_divided_them():
    """The arithmetic the alarm turned on, stated plainly: one day's difference
    in start_date is the difference between due yesterday and due in two days."""
    released = TODAY - timedelta(days=1)
    assert release_deadline(TODAY + timedelta(days=1), released) == TODAY
    assert release_deadline(TODAY + timedelta(days=3), released) == TODAY + timedelta(days=2)
