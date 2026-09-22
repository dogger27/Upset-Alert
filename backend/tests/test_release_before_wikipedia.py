"""The tour's own sheet can RELEASE a draw, not only dress one already released.

The follow-up brief of 2026-09-22 measured four releases — Korea, Chengdu,
Hangzhou, and Korea's four qualifiers — and found the WTA's sheet and Tennis
Explorer publishing inside the same hour as Wikipedia, never later than an
hour behind. What kept Wikipedia the author was not timing but reach: the
bootstrap ran only from the branch where WIKIPEDIA HAS NO PAGE, and
refresh_shape runs only on a draw that already has a field. A draw with a
page and no field — every draw in the days before its release — therefore went
to Wikipedia, and Wikipedia stamped the release.

Two things had to be true before that gap could be closed, and both are
pinned here: a draw with no field has nothing for the agreement floor to
judge, so the source that finds an event BY NAME must be corroborated some
other way; and the release itself — the stamp, the cooldown the email waits
on, and the start date the pick lock reads — must be the writer's, identical
whichever source handed it the field.
"""
import asyncio
import importlib
import pkgutil
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.tournament import Draw, DrawEntry
from app.routers.tournaments import _do_scrape, bootstrap_draw, refresh_shape
from app.services.sofa_draw_shape import DrawShape, ShapeEntrant, shape_to_parsed
from app.services.sofascore import _geometry_agrees

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")


async def _db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _no_rankings(monkeypatch):
    """The writer's release stamp calls assign_rankings, which on an empty
    database scrapes twelve Tennis Explorer pages. Not what these test."""
    import app.routers.tournaments as router
    import app.services.rankings as rankings

    async def nothing(*a, **k):
        return None
    for mod in (router, rankings):
        for name in ("assign_rankings", "assign_rankings_for_draw", "ensure_rankings"):
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, nothing)


def _shape(n=28, bracket=32):
    """A complete bracket: n players and the rest byes."""
    return DrawShape(
        bracket_size=bracket, num_rounds=5,
        entrants=[ShapeEntrant(bracket_position=i + 1, name=f"Player {i + 1}")
                  for i in range(n)],
        byes=list(range(n + 1, bracket + 1)))


# ── the decline that means "another door may open" ───────────────────────

def test_a_draw_with_no_field_asks_for_a_bootstrap_by_name():
    """The refresh loop acts on this, so it is a flag and not a sentence."""
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            d = Draw(name="Empty Open", year=2026, wiki_page_title="Empty Open", gender="M", draw_size=28,
                     num_rounds=5, status="upcoming")
            db.add(d); await db.commit()
            report = await refresh_shape(d, db)
            assert report["refreshed"] is False
            assert report["needs_bootstrap"] is True
        await engine.dispose()
    asyncio.run(go())


def test_a_draw_with_a_field_does_not():
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            d = Draw(name="Full Open", year=2026, wiki_page_title="Full Open", gender="M", draw_size=4,
                     num_rounds=2, status="upcoming")
            db.add(d); await db.flush()
            db.add_all([DrawEntry(draw_id=d.id, name=f"P{i}", bracket_position=i)
                        for i in range(1, 5)])
            await db.commit()
            report = await refresh_shape(d, db)
            assert report.get("needs_bootstrap") is None
        await engine.dispose()
    asyncio.run(go())


# ── what stands in for the agreement floor when there is no field ────────

def test_the_geometry_a_field_of_this_size_plays_in():
    assert _geometry_agrees(28, 32) is True       # a 28-player draw is a 32 bracket
    assert _geometry_agrees(32, 32) is True
    assert _geometry_agrees(96, 128) is True
    assert _geometry_agrees(28, 128) is False     # the wrong event entirely
    assert _geometry_agrees(28, 16) is False


def test_tennis_explorer_must_match_the_bracket_our_draw_size_plays_in(monkeypatch):
    """TE identifies an event by its city or its name, and a name is not an
    identity. With no field to agree with, the bracket's own geometry is the
    corroboration — the same test Sofascore's field-less identity uses."""
    _no_rankings(monkeypatch)

    async def go():
        engine, Session = await _db()
        async with Session() as db:
            d = Draw(name="Somewhere Open", year=2026, wiki_page_title="Somewhere Open", gender="M", draw_size=28,
                     num_rounds=5, status="upcoming", start_date=date(2026, 9, 23))
            db.add(d); await db.commit()

            import app.routers.tournaments as router

            async def wrong_event(*a, **k):
                return _shape(n=96, bracket=128), "tennisexplorer", {}
            monkeypatch.setattr(router, "_shape_from_sources", wrong_event)
            report = await bootstrap_draw(d, db)
            assert report["bootstrapped"] is False
            assert "not the one a 28-player draw plays in" in report["error"]
            assert (await db.execute(select(DrawEntry))).scalars().all() == []

            async def right_event(*a, **k):
                return _shape(n=28, bracket=32), "tennisexplorer", {}
            monkeypatch.setattr(router, "_shape_from_sources", right_event)
            report = await bootstrap_draw(d, db)
            assert report["bootstrapped"] is True, report.get("error")
        await engine.dispose()
    asyncio.run(go())


def test_the_wta_sheet_is_keyed_by_the_tours_own_id_and_is_not_second_guessed(monkeypatch):
    """A disagreement there means OUR draw_size is stale, and a stale size of
    ours must not hold up a release the tour has published."""
    _no_rankings(monkeypatch)

    async def go():
        engine, Session = await _db()
        async with Session() as db:
            d = Draw(name="Sheet Open", year=2026, wiki_page_title="Sheet Open", gender="F", draw_size=28,
                     num_rounds=5, status="upcoming", start_date=date(2026, 9, 23))
            db.add(d); await db.commit()
            import app.routers.tournaments as router

            async def sheet(*a, **k):
                return _shape(n=56, bracket=64), "wta_official", {}
            monkeypatch.setattr(router, "_shape_from_sources", sheet)
            report = await bootstrap_draw(d, db)
            assert report["bootstrapped"] is True, report.get("error")
        await engine.dispose()
    asyncio.run(go())


# ── the release is the writer's, whoever handed it the field ─────────────

def test_a_draw_built_from_a_shape_is_released_and_starts_the_email_clock(monkeypatch):
    """_notify_pending_draw_releases selects on released_at + detected_at and
    fires once the cooldown has held. A draw released this way has to be
    eligible for that query on exactly the same terms as a Wikipedia one."""
    _no_rankings(monkeypatch)

    async def go():
        engine, Session = await _db()
        async with Session() as db:
            d = Draw(name="Release Open", year=2026, wiki_page_title="Release Open", gender="M", draw_size=28,
                     num_rounds=5, status="upcoming", start_date=date(2026, 9, 23))
            db.add(d); await db.commit()
            await _do_scrape(d, db, parsed=shape_to_parsed(_shape()))
            await db.commit()

            fresh = await db.get(Draw, d.id)
            assert fresh.draw_released_direct_at == date.today()
            assert fresh.draw_release_detected_at is not None, "the cooldown clock never started"
            assert fresh.draw_release_notified_at is None, "the email is the notifier's to send"

            # The notifier's own query, run against this draw.
            cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)
            ready = (await db.execute(select(Draw).where(
                Draw.draw_released_direct_at.isnot(None),
                Draw.draw_release_notified_at.is_(None),
                Draw.draw_release_detected_at.isnot(None),
                Draw.draw_release_detected_at <= cutoff))).scalars().all()
            assert [x.id for x in ready] == [d.id]
        await engine.dispose()
    asyncio.run(go())


def test_a_shape_release_cannot_move_the_start_date_under_the_pick_lock(monkeypatch):
    """A start_date that moves EARLIER flips computed_status to active and
    locks picks (feedback_start_date_backwards_locks_picks). A shape source
    states no dates, and the draw it releases must keep the one it has —
    including a Wednesday start, which is the shape that got snapped to Monday
    before carries_dates existed."""
    _no_rankings(monkeypatch)

    async def go():
        engine, Session = await _db()
        async with Session() as db:
            d = Draw(name="Wednesday Open", year=2026, wiki_page_title="Wednesday Open", gender="M", draw_size=28,
                     num_rounds=5, status="upcoming",
                     start_date=date(2026, 9, 23), end_date=date(2026, 9, 29))
            db.add(d); await db.commit()
            parsed = shape_to_parsed(_shape())
            assert parsed.carries_dates is False
            await _do_scrape(d, db, parsed=parsed)
            await db.commit()

            fresh = await db.get(Draw, d.id)
            assert fresh.start_date == date(2026, 9, 23), "the Wednesday start moved"
            assert fresh.end_date == date(2026, 9, 29)
            assert fresh.status == "upcoming", "a released draw is not a started one"
        await engine.dispose()
    asyncio.run(go())


def test_an_incomplete_bracket_never_reaches_the_writer():
    """The brief measured a quarter of each draw blank in Sofascore's tree
    until qualifying ended — and a half-filled bracket written and stamped
    released is worse than no bracket, because the bootstrap never revisits
    one. `_shape_from_sources` is where that gate sits: a source's shape is
    only ever returned from it once complete, so a partial one cannot reach
    the writer through either door."""
    from app.services.sofa_draw_shape import bracket_is_complete

    partial = DrawShape(bracket_size=32, num_rounds=5, entrants=[
        ShapeEntrant(bracket_position=i + 1, name=f"Player {i + 1}")
        for i in range(20)], byes=[])
    assert bracket_is_complete(partial) is False
    assert bracket_is_complete(_shape()) is True
