"""The shape comparison runs AFTER resolution, and joins on the player id.

2026-09-23 10:01:20, Chengdu Open (draw 145). The cup tree slotted "Martin
Damm Jr" where our draw holds "Martin Damm"; `resolve_draw` compared the two
BEFORE stamping anything, matched 27 of 28 and warned "Draw shape disagrees
with Wikipedia … 1 in sofascore only; 1 in ours only". Moments later, in the
same call, the resolver stamped him `sofa_player_id` 51345 and `sofa_name`
"Martin Damm Jr" — and re-running that identical comparison against that
identical tree afterwards matches 28 and says nothing.

That is the whole fault: the comparison's two strongest keys are the ones
resolution establishes, so the one pass where Sofascore FIRST slots a
differently-spelled player is exactly the pass that has neither. Every such
player bought one false alarm and then agreed forever. The 2026-09-21 fix
(an unfilled slot is pending, not a disagreement) was a different state and
left this one untouched, which is why the alarm came back.

Two changes, tested here:
  * the comparison happens at the END of resolve_draw;
  * it joins on `sofa_player_id` first — Sofascore stating the identity — so
    the generational suffix the module refuses to fold away (Damm Sr is a real
    player) is settled by evidence instead of by a rule about names.
"""
import asyncio
import importlib
import pkgutil
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.tournament import Draw, DrawEntry
from app.services import sofascore
from app.services.sofa_draw_shape import (compare_to_entries,
                                          disagreement_summary, draw_shape)

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")

# Chengdu's first two R32 pairs, in a 4 bracket: the shape is what matters.
FIELD = [(51345, "Martin Damm Jr"), (298795, "Shintaro Mochizuki"),
         (157808, "Lloyd Harris"), (187608, "Aleksandar Kovačević")]
OURS = ["Martin Damm", "Shintaro Mochizuki", "Lloyd Harris",
        "Aleksandar Kovacevic"]


def _payload():
    blocks = [
        {"order": 1, "matchesInRound": 1, "participants": [
            {"order": 1, "team": {"id": FIELD[0][0], "name": FIELD[0][1]}},
            {"order": 2, "team": {"id": FIELD[1][0], "name": FIELD[1][1]}}]},
        {"order": 2, "matchesInRound": 1, "participants": [
            {"order": 1, "team": {"id": FIELD[2][0], "name": FIELD[2][1]}},
            {"order": 2, "team": {"id": FIELD[3][0], "name": FIELD[3][1]}}]},
    ]
    final = [{"order": 1, "matchesInRound": 1, "participants": []}]
    return {"cupTrees": [{"name": "Chengdu Open, Singles",
                          "rounds": [{"blocks": blocks}, {"blocks": final}]}]}


class E:
    """A draw entry, as much of one as the comparison reads."""

    def __init__(self, name, bracket_position, sofa_player_id=None,
                 sofa_name=None):
        self.name = name
        self.bracket_position = bracket_position
        self.sofa_player_id = sofa_player_id
        self.sofa_name = sofa_name
        self.seed = None
        self.entry_type = None


# ── the join ──────────────────────────────────────────────────────────────

def test_the_player_id_settles_a_generational_suffix():
    """No name key can meet "Martin Damm Jr" and "Martin Damm" — and none
    should, since Damm Sr is a real player. The id can, and does."""
    shape = draw_shape(_payload())
    ours = [E(n, i + 1, sofa_player_id=FIELD[i][0]) for i, n in enumerate(OURS)]
    cmp = compare_to_entries(shape, ours)
    assert cmp["matched"] == 4
    assert disagreement_summary(cmp) is None


def test_a_different_id_at_the_same_slot_is_still_a_disagreement():
    """The id is a key, not an amnesty: a slot both sources state, filled by
    two different people, must still be reported."""
    shape = draw_shape(_payload())
    ours = [E(n, i + 1, sofa_player_id=FIELD[i][0]) for i, n in enumerate(OURS)]
    ours[0].name, ours[0].sofa_player_id = "Martin Damm Sr", 9999
    why = disagreement_summary(compare_to_entries(shape, ours))
    assert "in sofascore only" in why and "in ours only" in why


def test_names_still_join_when_nobody_is_resolved_yet():
    """The id is the first key, never the only one — an unresolved draw must
    match on names exactly as it always did."""
    shape = draw_shape(_payload())
    ours = [E(n, i + 1) for i, n in enumerate(OURS)]
    cmp = compare_to_entries(shape, ours)
    assert cmp["matched"] == 3                       # everyone but Damm
    assert cmp["only_ours"] == ["Martin Damm"]


# ── the order ─────────────────────────────────────────────────────────────

async def _db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _chengdu(db):
    d = Draw(name="Chengdu Open", year=2026, gender="M", draw_size=4,
             wiki_page_title="2026 Chengdu Open – Singles",
             num_rounds=2, status="upcoming",
             start_date=date.today(), end_date=date.today() + timedelta(days=6),
             sofa_tournament_id=9402, sofa_season_id=82383)
    db.add(d)
    await db.flush()
    for i, name in enumerate(OURS):
        db.add(DrawEntry(draw_id=d.id, name=name, bracket_position=i + 1,
                         nationality=None))
    await db.commit()
    return d


def _run(monkeypatch):
    said = []

    async def _log(level, category, message, *a, **k):
        said.append((level, message))

    async def _tree(uid, season_id):
        return _payload()

    monkeypatch.setattr(sofascore, "app_log", _log)
    monkeypatch.setattr(sofascore, "_cuptree_of", _tree)

    async def go():
        engine, Session = await _db()
        async with Session() as db:
            d = await _chengdu(db)
            report = await sofascore.resolve_draw(db, d)
            rows = {e.name: e for e in (await db.execute(
                DrawEntry.__table__.select().where(
                    DrawEntry.draw_id == d.id))).all()}
        await engine.dispose()
        return report, said, rows

    return asyncio.run(go())


def test_the_first_pass_that_slots_him_does_not_warn(monkeypatch):
    """Production's 10:01:20 call, start to finish: the resolver stamps Damm
    from the same tree the comparison then reads, so nothing disagrees."""
    report, said, rows = _run(monkeypatch)
    assert report["resolved"] == 4
    assert rows["Martin Damm"].sofa_player_id == 51345
    assert rows["Martin Damm"].sofa_name == "Martin Damm Jr"
    assert report["shape_matched"] == 4
    assert report["shape_disagreement"] is None
    assert [m for lvl, m in said if lvl == "warning"] == []


def test_the_comparison_still_happens(monkeypatch):
    """Moving it must not quietly turn it off — it is the evidence the
    decision to demote Wikipedia is being built on."""
    report, _, _ = _run(monkeypatch)
    assert "shape_matched" in report and "shape_disagreement" in report
