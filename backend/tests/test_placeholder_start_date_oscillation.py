"""A start date nobody confirmed must neither be rewritten nor accused on.

2026-09-21, 00:12:39 UTC: `_alert_missing_oop` reported 'Chengdu Open' and
'Hangzhou Open' as having started with no published order of play, and
`_alert_missing_schedule` warned that a sheet was being fetched or parsed
wrong. Neither tournament starts until the 23rd — both ATP 250s were moved to
a Wednesday main draw to work around the Laver Cup.

Two faults, one date:

1. THE CORRECTION NEVER STUCK. `_refresh_dates_from_event_page` read the event
   page and moved both draws 21 → 23 September on 16, 17, 18, 19 and 20
   September — the same correction, every day, because `_apply_update` wrote
   the season page's week-Monday straight back over it on the next daily sync.
   It writes only on a change, so five identical corrections in five days IS
   the proof it was being undone. The evidence left in the row was a
   closing_time of 2026-09-23 03:00 sitting beside a start_date of 09-21: the
   deadline derived from a date the row no longer held.

2. THE ALARMS JUDGED ON IT ANYWAY. `_check_draw_health` and `sofa_resolver`
   learned to ask the event page before accusing (2df1fa3d); these two
   order-of-play checks are the rest of that class and had no such guard.

Fixing either alone would have silenced the night. Both are fixed, because
either one recurring puts the same false alarm back in the owner's mail — and
a start_date left in the past does worse than alarm: it reads as "active" the
moment the draw is released, which locks picks days early.
"""
import asyncio
import importlib
import pkgutil
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
import app.services.order_of_play as oop
import app.services.scraper as scraper
import app.services.tournament_sync as tsync
from app.database import Base
from app.models.tournament import Draw, Tournament
from app.services.discovery import DiscoveredTournament

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")


TODAY = date.today()


async def _db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# --- 1. The season page may not undo the event page -------------------------

# A fixed week, so the test says what it means whatever day it runs on.
MONDAY = date(2026, 9, 21)
WEDNESDAY = date(2026, 9, 23)
SUNDAY = date(2026, 9, 27)


def _discovered(start, end):
    """What discovery reads off the season page: a week label, snapped to its
    Monday, for every event in that week."""
    return DiscoveredTournament(
        name="Chengdu Open", year=2026, gender="M", surface="Hard",
        category="ATP 250", draw_size=32,
        wiki_page_title="2026 Chengdu Open – Singles",
        start_date=start, end_date=end, city="Chengdu", country="China")


def _apply(stored_start, stored_end, season_start, season_end):
    """One `_apply_update` over a draw carrying *stored_start*; returns the row."""
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            d = Draw(name="Chengdu Open", year=2026, gender="M", draw_size=32,
                     num_rounds=5, category="ATP 250", status="upcoming",
                     wiki_page_title="2026 Chengdu Open – Singles",
                     start_date=stored_start, end_date=stored_end)
            db.add(d)
            await db.flush()
            await tsync._apply_update(d, _discovered(season_start, season_end), db)
            await db.commit()
            await engine.dispose()
            return d
    return asyncio.run(go())


def test_the_season_page_does_not_pull_a_refined_date_back_to_the_monday():
    """Chengdu exactly: the event page moved it to Wednesday, and the next
    sync must leave it there. This is the write that fired every day for five
    days, and the one that left start_date in the past on the 21st."""
    d = _apply(WEDNESDAY, SUNDAY, MONDAY, SUNDAY)
    assert d.start_date == WEDNESDAY
    assert d.end_date == SUNDAY


def test_a_rescheduled_event_still_moves():
    """The guard is "same week", not "never" — a season page that moves an
    event to a different week is telling us something we do not otherwise
    know, and it must still be applied."""
    d = _apply(WEDNESDAY, SUNDAY, MONDAY + timedelta(days=7), SUNDAY + timedelta(days=7))
    assert d.start_date == MONDAY + timedelta(days=7)
    assert d.end_date == SUNDAY + timedelta(days=7)


def test_a_draw_with_no_date_yet_takes_the_season_page_date():
    """Nothing stored is not a refinement to protect."""
    d = _apply(None, None, MONDAY, SUNDAY)
    assert d.start_date == MONDAY
    assert d.end_date == SUNDAY


def test_the_release_estimate_follows_the_date_that_won():
    """draw_release_direct hangs off start_date, so deriving it from the date
    we just declined to store would leave the row internally inconsistent —
    which is exactly the state 145/122 were in on the 21st."""
    d = _apply(WEDNESDAY, SUNDAY, MONDAY, SUNDAY)
    assert d.draw_release_direct == date(2026, 9, 21)     # two days before the 23rd
    # 09-19 is what the Monday produces, and it is what draw 145 was carrying
    # in production on the morning it alarmed — a release date for a start the
    # row had already been corrected away from.
    assert d.draw_release_direct != date(2026, 9, 19)


# --- 2. The two order-of-play alarms ask the page before accusing -----------

def _venue(draw_start, *, page_start, stored_entries=False):
    """One pass of BOTH order-of-play alarms; returns every app_log they made."""
    said = []

    async def _log(level, category, message, detail=None, **kw):
        said.append((level, message, detail or {}))

    async def _event_dates(title, year, gender=""):
        return page_start, (page_start + timedelta(days=6) if page_start else None)

    async def go(monkey):
        engine, Session = await _db()
        monkey(Session)
        async with Session() as db:
            t = Tournament(name="Chengdu Open", year=TODAY.year)
            db.add(t)
            await db.flush()
            d = Draw(tournament_id=t.id, name="Chengdu Open", year=TODAY.year,
                     gender="M", draw_size=32, num_rounds=5, category="ATP 250",
                     status="upcoming",
                     wiki_page_title=f"{TODAY.year} Chengdu Open – Singles",
                     wiki_page_id=None, venue_timezone="Asia/Shanghai",
                     start_date=draw_start,
                     end_date=draw_start + timedelta(days=8))
            db.add(d)
            await db.commit()
        await oop._alert_missing_oop()
        await oop._alert_missing_schedule()
        await engine.dispose()

    return said, go, _log, _event_dates


def _run_alarms(monkeypatch, draw_start, page_start):
    said, go, _log, _event_dates = _venue(draw_start, page_start=page_start)
    monkeypatch.setattr(oop, "app_log", _log, raising=False)
    monkeypatch.setattr("app.services.system_log.app_log", _log)
    monkeypatch.setattr(scraper, "fetch_event_dates", _event_dates)
    asyncio.run(go(lambda S: monkeypatch.setattr(oop, "AsyncSessionLocal", S)))
    return said


def test_neither_alarm_fires_on_a_date_the_event_page_contradicts(monkeypatch):
    """Chengdu's night: stored start is today at the venue, the event page says
    play begins in two days. One error and one warning became two info lines."""
    said = _run_alarms(monkeypatch, oop._venue_today("Asia/Shanghai"),
                       oop._venue_today("Asia/Shanghai") + timedelta(days=2))
    assert not [m for lvl, m, _ in said if lvl in ("error", "warning")], said
    stood_down = [d for lvl, m, d in said if lvl == "info" and "on schedule" in m]
    assert len(stood_down) == 2, said


def test_both_alarms_keep_their_teeth_when_the_page_agrees(monkeypatch):
    """The point of these checks is a tournament on court with no sheet. When
    the event page confirms play has started, both must still say so."""
    started = oop._venue_today("Asia/Shanghai")
    said = _run_alarms(monkeypatch, started, started)
    assert [m for lvl, m, _ in said if lvl == "error"], said
    assert [m for lvl, m, _ in said if lvl == "warning"], said


def test_an_unreadable_event_page_is_not_a_reason_to_go_quiet(monkeypatch):
    """No page, no answer, stored date stands — silence would be the worse
    failure, and these checks exist because silence was the failure."""
    started = oop._venue_today("Asia/Shanghai")
    said = _run_alarms(monkeypatch, started, None)
    assert [m for lvl, m, _ in said if lvl == "error"], said
    assert [m for lvl, m, _ in said if lvl == "warning"], said


def test_the_event_page_is_not_asked_about_a_draw_that_has_not_started(monkeypatch):
    """The confirmation is a network round trip, so it happens only on the
    branch that is about to accuse — never on the ordinary pass over the
    ordinary upcoming draw, of which there are dozens every day."""
    def _boom(*a, **k):
        raise AssertionError("the event page must not be fetched before the start date")
    monkeypatch.setattr(scraper, "fetch_event_dates", _boom)
    said = []

    async def _log(level, category, message, detail=None, **kw):
        said.append((level, message))
    monkeypatch.setattr(oop, "app_log", _log, raising=False)
    monkeypatch.setattr("app.services.system_log.app_log", _log)

    _, go, _, _ = _venue(oop._venue_today("Asia/Shanghai") + timedelta(days=10),
                         page_start=None)
    asyncio.run(go(lambda S: monkeypatch.setattr(oop, "AsyncSessionLocal", S)))
    assert said == []


def test_a_resolved_wiki_page_is_never_second_guessed(monkeypatch):
    """Once the singles infobox has been read, start_date IS the date — asking
    the general event page again would be slower and no better informed."""
    def _boom(*a, **k):
        raise AssertionError("a draw with a resolved page must not be re-confirmed")
    monkeypatch.setattr(scraper, "fetch_event_dates", _boom)

    class _Draw:
        wiki_page_id = 12345
        wiki_page_title = "2026 Chengdu Open – Singles"
        year, gender, id = 2026, "M", 1

    assert asyncio.run(oop._confirmed_start(_Draw(), WEDNESDAY)) == WEDNESDAY
