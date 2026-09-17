"""A court's display name, set by an admin, everywhere the schedule is served.

"Quadra Central Maria Esther Bueno" is "Central" to everyone who reads the
site (owner, 2026-09-17). The sheet's name stays the key on every row; only
the outgoing `court` changes, so the site and the app agree without either
knowing about aliases.
"""
import asyncio
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.routers.schedule import CourtAliasIn, display_court, list_court_aliases, set_court_alias

import importlib
import pkgutil
for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")

ADMIN = SimpleNamespace(id=1, is_admin=True)
READER = SimpleNamespace(id=2, is_admin=False)


def test_display_court_prefers_the_alias_for_that_tournament_only():
    aliases = {(97, "QUADRA CENTRAL MARIA ESTHER BUENO"): "Central"}
    assert display_court(aliases, 97, "QUADRA CENTRAL MARIA ESTHER BUENO") == "Central"
    assert display_court(aliases, 97, "QUADRA 2") == "QUADRA 2"
    assert display_court(aliases, 35, "QUADRA CENTRAL MARIA ESTHER BUENO") == "QUADRA CENTRAL MARIA ESTHER BUENO"
    assert display_court(aliases, 97, None) is None
    assert display_court({}, 97, "") == ""


async def _session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _flow():
    engine, Session = await _session()
    async with Session() as db:
        # A reader cannot rename.
        try:
            await set_court_alias(CourtAliasIn(tournament_id=97, court="QUADRA 2", display_name="Two"), db, READER)
            raise AssertionError("a reader renamed a court")
        except HTTPException as e:
            assert e.status_code == 403
        # An admin can; the alias is listed; a second save replaces it.
        out = await set_court_alias(CourtAliasIn(tournament_id=97, court="QUADRA CENTRAL MARIA ESTHER BUENO",
                                                 display_name="  Central  "), db, ADMIN)
        assert out["display_name"] == "Central"
        await set_court_alias(CourtAliasIn(tournament_id=97, court="QUADRA CENTRAL MARIA ESTHER BUENO",
                                           display_name="Centre Court"), db, ADMIN)
        rows = await list_court_aliases(97, db)
        assert rows == [{"tournament_id": 97, "court": "QUADRA CENTRAL MARIA ESTHER BUENO", "display_name": "Centre Court"}]
        # Another tournament's identical court name is untouched.
        assert await list_court_aliases(35, db) == []
        # An empty name — or the sheet's own — clears it.
        out = await set_court_alias(CourtAliasIn(tournament_id=97, court="QUADRA CENTRAL MARIA ESTHER BUENO",
                                                 display_name=""), db, ADMIN)
        assert out["display_name"] is None
        assert await list_court_aliases(97, db) == []
    await engine.dispose()


def test_admin_sets_replaces_and_clears_an_alias():
    asyncio.run(_flow())
