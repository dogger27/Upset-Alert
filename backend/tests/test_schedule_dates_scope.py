"""/schedule/dates scoped to SEVERAL tournaments at once.

The app's schedule tab shows every tournament its chooser has ticked, and its
date stepper has to walk exactly those tournaments' days. One id was enough
for the page pinned to a single event; with two boxes ticked the tab asked
for no id at all, got every date on record, and let the reader step back to
a Cincinnati Friday that neither ticked tournament played (owner,
2026-09-17). `tournament_id` now repeats, and the unscoped answer — how the
chooser learns which tournaments are on the sheets at all — is unchanged.

No HTTP client: the handler is a plain coroutine, called with an in-memory
session. The engine sits on a StaticPool so the session's connection is the
one create_all built the tables on — a pooled in-memory SQLite is a fresh,
empty database per connection.
"""
import asyncio
import importlib
import pkgutil
from datetime import date

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models
from app.database import Base
from app.models.schedule import ScheduleEntry
from app.routers.schedule import schedule_dates

# Every model, so every foreign-key target is a table create_all knows.
for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")

# Cincinnati (1) played in August; Guadalajara (2) and the SP Open (3) share
# the mid-September week, and share a day.
ROWS = [
    (1, date(2026, 8, 21)),
    (2, date(2026, 9, 13)),
    (2, date(2026, 9, 15)),
    (3, date(2026, 9, 15)),
    (3, date(2026, 9, 16)),
]


async def _dates(ids):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        db.add_all(ScheduleEntry(tournament_id=t, play_date=d, pairing_key=f"{t}:{d}:{i}")
                   for i, (t, d) in enumerate(ROWS))
        await db.commit()
        out = await schedule_dates(tournament_id=ids, db=db)
    await engine.dispose()
    return out


def test_two_ids_answer_with_their_days_only():
    out = asyncio.run(_dates([2, 3]))
    assert out["dates"] == ["2026-09-13", "2026-09-15", "2026-09-16"]
    assert sorted(out["tournaments"]) == [2, 3]
    # The shared day counts both tournaments' matches, nothing else's.
    assert out["open_counts"]["2026-09-15"] == 2


def test_one_id_is_still_one_tournament():
    out = asyncio.run(_dates([2]))
    assert out["dates"] == ["2026-09-13", "2026-09-15"]
    assert out["tournaments"] == [2]
    assert out["open_counts"]["2026-09-15"] == 1


def test_unscoped_is_every_date_on_record():
    out = asyncio.run(_dates(None))
    assert out["dates"] == ["2026-08-21", "2026-09-13", "2026-09-15", "2026-09-16"]
    assert sorted(out["tournaments"]) == [1, 2, 3]
