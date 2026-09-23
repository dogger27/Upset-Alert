"""A slot that gains a NAME gains a PLAYER, in the same transaction.

2026-09-23, 2026 Chengdu Open (M) and 2026 Hangzhou Open (M). ESPN's Round-1
pairings named eight blank qualifier slots hours before Wikipedia transcribed
them — and set nothing but `name`. A name on its own is half an entrant: no
te_player_id means no ranking, no ELO, no H2H, no form, and because the badge
on a pill is seed-or-ranking, no rank badge at all. `entries_without_draw_rank`
reported both draws as holding players who could be given no rank, which is
exactly what they were, on two draws already on court.

The scrape's own retry sweep resolves unmatched entries on every pass, so the
fault was survivable in principle — but only on the NEXT pass, and the check
watches in between. Resolving inside the same write is what removes the window
rather than shortening it: commit the names first and the database really does
hold, for as long as a Tennis Explorer lookup takes, a released draw full of
entrants nothing can rank.

    .venv/bin/python tests/test_named_slot_gets_a_player.py
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
import app.services.espn_monitor as espn                           # noqa: E402
from app.database import Base                                      # noqa: E402
from app.models.tournament import Draw, DrawEntry, Match           # noqa: E402
from app.services.draw_invariants import entries_without_draw_rank  # noqa: E402

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")


def _event(pairings):
    """An ESPN event carrying only what this job reads: main-draw Round-1
    men's singles competitions and the two names in each."""
    return {"groupings": [{
        "grouping": {"displayName": "Men's Singles"},
        "competitions": [
            {"status": {"type": {"name": "STATUS_SCHEDULED"}},
             "round": {"displayName": "Round 1"},
             "competitors": [{"athlete": {"fullName": n}} for n in names]}
            for names in pairings
        ],
    }]}


async def _db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def check(ok, label):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    return 0 if ok else 1


def main():
    bad = 0

    async def go():
        nonlocal bad
        engine, Session = await _db()

        # The job opens its own session; give it this one.
        real_session, real_log = espn.AsyncSessionLocal, espn.app_log

        async def quiet_log(*a, **k):
            return None

        seen = []

        async def spy_assign(players, gender, ref_date, db):
            seen.append(sorted(p.name for p in players))
            for p in players:
                if (p.name or "").strip() and p.te_player_id is None:
                    # What the real matcher does for "Alexandre Muller": a
                    # first-try token-set hit on a profile already in our table.
                    p.te_player_id, p.te_slug, p.ranking = 125, "muller-c81bc", 137
                    p.nationality = p.nationality or "FRA"

        async def spy_seed(*a, **k):
            return None

        import app.services.rankings as rankings
        real_assign, real_seed = rankings.assign_rankings, rankings.assign_seed_week_rankings
        espn.AsyncSessionLocal, espn.app_log = Session, quiet_log
        rankings.assign_rankings, rankings.assign_seed_week_rankings = spy_assign, spy_seed
        try:
            async with Session() as db:
                d = Draw(name="Chengdu Open", year=2026, gender="M", draw_size=2,
                         num_rounds=1, wiki_page_title="2026 Chengdu Open – Singles",
                         status="active", start_date=date(2026, 9, 23),
                         end_date=date(2026, 9, 29),
                         entry_ranking_week=date(2026, 8, 24),
                         seed_ranking_week=date(2026, 9, 7),
                         draw_released_direct_at=date(2026, 9, 21))
                db.add(d)
                await db.flush()
                known = DrawEntry(draw_id=d.id, name="Alpha One", bracket_position=1,
                                  te_player_id=1, ranking=44)
                blank = DrawEntry(draw_id=d.id, name="", bracket_position=2,
                                  entry_type="Q")
                db.add_all([known, blank])
                await db.flush()
                db.add(Match(draw_id=d.id, round_number=1, match_number=1,
                             player1_id=known.id, player2_id=blank.id,
                             status="pending"))
                await db.commit()
                draw_id = d.id

            monitor = espn.ESPNMonitor()
            filled = await monitor._fill_unnamed_slots(
                d, _event([["Alpha One", "Alexandre Muller"]]), [], {})
            bad += check(filled == 1, f"the slot is named ({filled} filled)")

            async with Session() as db:
                q = (await db.execute(select(DrawEntry).where(
                    DrawEntry.draw_id == draw_id,
                    DrawEntry.bracket_position == 2))).scalar_one()
                bad += check(q.name == "Alexandre Muller",
                             f"with the opponent's name (got {q.name!r})")
                bad += check(q.te_player_id is not None,
                             "and a Tennis Explorer player, not a bare name")
                bad += check(q.ranking is not None,
                             "and the ranking that gives the pill its badge")

                # And the law, asked directly: whatever the draw holds the
                # instant the fill's transaction commits must be lawful.
                # (A slot left unresolved would now be `_check_rankings_health`'s
                # to report, not this check's — so this passes either way and
                # the two assertions above are the discriminating ones. It is
                # here because the invariant is the thing that fired, and a
                # test of the fix should say so in the invariant's own terms.)
                entries = (await db.execute(select(DrawEntry).where(
                    DrawEntry.draw_id == draw_id))).scalars().all()
                why = entries_without_draw_rank(entries)
                bad += check(why is None,
                             f"so the draw is lawful on commit (got {why!r})")

            bad += check(seen == [["Alexandre Muller"]],
                         f"only the newly named slot is looked up (got {seen})")
        finally:
            espn.AsyncSessionLocal, espn.app_log = real_session, real_log
            rankings.assign_rankings, rankings.assign_seed_week_rankings = real_assign, real_seed
            await engine.dispose()

    asyncio.run(go())
    print("ALL PASS" if not bad else f"{bad} FAILURES")
    return 1 if bad else 0


def test_named_slot_gets_a_player():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
