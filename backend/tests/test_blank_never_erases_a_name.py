"""A source that does not know the name does not get to erase it.

2026-09-23, 2026 Chengdu Open (M) and 2026 Hangzhou Open (M). Wikipedia was
still printing four Round-1 slots as "Qualifier" hours into play while ESPN's
published pairings had already named them. Those slots parse to an EMPTY name,
and the writer's upsert applied it: `player.name = pe.name` over a name we
held. The ESPN fill put each name back, the next scrape blanked it again —
three round trips inside seven minutes — and the wreckage was not cosmetic:

* a duplicate "filled" draw-change event on every fill, 24 of them queued for
  re-announcement to people who had already been told once at 08:24;
* `assign_rankings`, which retries every entry with no te_player_id on every
  scrape, was handed a BLANK name each time, so all eight kept te_player_id
  NULL — no ranking, no ELO, no H2H, no form, and no rank badge at all — on
  two draws already on court. Every one of the eight matched a Tennis Explorer
  player already in our own table, on the first token-set try;
* and `entries_without_draw_rank` reported it, correctly, as a draw holding
  players who could be given no rank.

`classify_change` had long since decided a slot going blank is not NEWS. It is
not a FACT either. This is the same law the match upsert states one screen
below for a later-round slot (`_keep_known`, tests/test_shape_ownership.py): a
source's blank means "unknown", not "nobody".

    .venv/bin/python tests/test_blank_never_erases_a_name.py
"""
import asyncio
import importlib
import pkgutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select                                      # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool                             # noqa: E402

import app.models  # noqa: F401,E402
from app.database import Base                                      # noqa: E402
from app.models.notification import DrawChangeEvent                # noqa: E402
from app.models.tournament import Draw, DrawEntry, Match           # noqa: E402
from app.services.scraper import MatchResult, ParsedDraw, PlayerEntry  # noqa: E402

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")


async def _db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# The four entrants of a 4-draw. Position 2 is the qualifier slot at issue:
# ESPN named it, Wikipedia still prints "Qualifier".
FIELD = ["Alpha One", "Nikoloz Basilashvili", "Gamma Three", "Delta Four"]


def _wikipedia_with_an_unnamed_qualifier():
    """What Wikipedia's page parses to: position 2 blank, and marked Q."""
    players = [
        PlayerEntry(bracket_position=1, name="Alpha One", nationality="USA",
                    seed=1, entry_type=None),
        PlayerEntry(bracket_position=2, name="", nationality=None,
                    seed=None, entry_type="Q"),
        PlayerEntry(bracket_position=3, name="Gamma Three", nationality="FRA",
                    seed=None, entry_type=None),
        PlayerEntry(bracket_position=4, name="Delta Four", nationality="ITA",
                    seed=2, entry_type=None),
    ]
    return ParsedDraw(
        draw_size=4, num_rounds=2, players=players,
        matches=[
            MatchResult(round_number=1, match_number=1, player1_position=1,
                        player2_position=2, winner_position=None),
            MatchResult(round_number=1, match_number=2, player1_position=3,
                        player2_position=4, winner_position=None),
        ],
        start_date=date(2026, 9, 23), end_date=date(2026, 9, 29),
        has_direct_draw=True, has_qualifiers=True)


async def _scrape(db, draw, parsed, seen):
    """Run the writer, recording every name assign_rankings is handed."""
    import app.routers.tournaments as router

    async def spy(players, gender, ref_date, session):
        seen.append([p.name for p in players])
        # What the real one does for a name it can bridge, which for
        # "Nikoloz Basilashvili" is the first token-set try.
        for p in players:
            if (p.name or "").strip() and p.te_player_id is None:
                p.te_player_id, p.ranking = 118, 131

    async def noop(*a, **k):
        return None

    real_assign = router.assign_rankings
    real_seed = router.assign_seed_week_rankings
    router.assign_rankings, router.assign_seed_week_rankings = spy, noop
    try:
        await router._do_scrape(draw, db, parsed=parsed)
        await db.commit()
    finally:
        router.assign_rankings, router.assign_seed_week_rankings = real_assign, real_seed


async def _setup(db):
    d = Draw(name="Chengdu Open", year=2026, gender="M", draw_size=4, num_rounds=2,
             wiki_page_title="2026 Chengdu Open – Singles", status="active",
             start_date=date(2026, 9, 23), end_date=date(2026, 9, 29),
             draw_released_direct_at=date(2026, 9, 21),
             draw_release_notified_at=date(2026, 9, 21))
    db.add(d)
    await db.flush()
    ents = [DrawEntry(draw_id=d.id, name=n, bracket_position=i + 1,
                      entry_type="Q" if i == 1 else None)
            for i, n in enumerate(FIELD)]
    db.add_all(ents)
    await db.flush()
    e = {x.bracket_position: x.id for x in ents}
    db.add_all([
        Match(draw_id=d.id, round_number=1, match_number=1,
              player1_id=e[1], player2_id=e[2], status="pending"),
        Match(draw_id=d.id, round_number=1, match_number=2,
              player1_id=e[3], player2_id=e[4], status="pending"),
        Match(draw_id=d.id, round_number=2, match_number=1, status="pending"),
    ])
    await db.commit()
    return d


def check(ok, label):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    return 0 if ok else 1


def main():
    bad = 0

    async def go():
        nonlocal bad
        engine, Session = await _db()
        async with Session() as db:
            d = await _setup(db)
            seen = []

            # Scrape once with the page that still says "Qualifier"...
            await _scrape(db, d, _wikipedia_with_an_unnamed_qualifier(), seen)
            q = (await db.execute(select(DrawEntry).where(
                DrawEntry.draw_id == d.id,
                DrawEntry.bracket_position == 2))).scalar_one()
            bad += check(q.name == "Nikoloz Basilashvili",
                         f"the named slot survives a blank parse (got {q.name!r})")
            bad += check(q.entry_type == "Q",
                         "the slot keeps the entry type the placeholder states")

            # ...and the retry sweep must see the REAL name, or the entry can
            # never resolve: a blank name matches no Tennis Explorer player.
            bad += check(any("Nikoloz Basilashvili" in names for names in seen),
                         "assign_rankings is handed the name, not a blank")
            bad += check(q.te_player_id is not None and q.ranking is not None,
                         "so the slot ends the scrape with a rank to render")

            # And the draw-change queue is not re-armed by a slot that never
            # actually changed.
            events = (await db.execute(select(DrawChangeEvent).where(
                DrawChangeEvent.draw_id == d.id))).scalars().all()
            bad += check(not events,
                         f"no draw change is recorded for it ({len(events)} found)")

            # Scrape again — the page has not caught up yet. Nothing may drift.
            await _scrape(db, d, _wikipedia_with_an_unnamed_qualifier(), seen)
            q2 = (await db.execute(select(DrawEntry).where(
                DrawEntry.draw_id == d.id,
                DrawEntry.bracket_position == 2))).scalar_one()
            bad += check(q2.name == "Nikoloz Basilashvili" and q2.id == q.id,
                         "and it still survives the next scrape, same row")
            events = (await db.execute(select(DrawChangeEvent).where(
                DrawChangeEvent.draw_id == d.id))).scalars().all()
            bad += check(not events, "still no draw-change churn on the second pass")

            # THE OTHER HALF OF THE LAW: a source that DOES know a name may
            # still fill a slot that has none. Blanking is refused; filling is
            # the whole point of the path.
            empty = DrawEntry(draw_id=d.id, name="", bracket_position=5,
                              entry_type="Q")
            db.add(empty)
            await db.commit()
            parsed = _wikipedia_with_an_unnamed_qualifier()
            parsed.draw_size = 8
            parsed.players.append(PlayerEntry(bracket_position=5, name="Lloyd Harris",
                                              nationality="RSA", seed=None,
                                              entry_type="Q"))
            await _scrape(db, d, parsed, seen)
            filled = (await db.execute(select(DrawEntry).where(
                DrawEntry.draw_id == d.id,
                DrawEntry.bracket_position == 5))).scalar_one()
            bad += check(filled.name == "Lloyd Harris",
                         "a source that knows the name still fills an empty slot")
            kinds = [e.kind for e in (await db.execute(select(DrawChangeEvent).where(
                DrawChangeEvent.draw_id == d.id))).scalars().all()]
            bad += check(kinds == ["filled"],
                         f"and that one IS announced, once (got {kinds})")

        await engine.dispose()

    asyncio.run(go())
    print("ALL PASS" if not bad else f"{bad} FAILURES")
    return 1 if bad else 0


def test_blank_never_erases_a_name():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
