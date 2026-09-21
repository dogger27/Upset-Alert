"""A draw's shape can be owned by a source that is not Wikipedia — safely.

Two guards make rewriting a LIVE draw from the WTA sheet or Tennis Explorer
safe rather than reckless, and both are tested here against the failure they
prevent: a shape-only source carries no results, so its None for a later-round
player must never erase one a result placed; and a source that identified the
wrong tournament must not be allowed to take a draw over.
"""
import asyncio
import importlib
import pkgutil

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.tournament import Draw, DrawEntry, Match
from app.routers.tournaments import REFRESH_AGREEMENT_FLOOR, _agreement, _do_scrape, _keep_known
from app.services.draw_changes import same_person
from app.services.sofa_draw_shape import DrawShape, ShapeEntrant, compare_to_entries, shape_to_parsed

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")


# ── the writer's later-round guard ────────────────────────────────────────

@pytest.mark.parametrize("rnd,incoming,existing,expected", [
    (1, 5, None, True), (1, None, 7, True), (1, 5, 7, True),      # round 1: structural, always
    (2, 5, None, True),                                          # nobody there yet: fill
    (2, 5, 7, True),                                             # a name: replace
    (2, None, 7, False),                                         # None over a known player: NEVER
    (5, None, 9, False),
])
def test_a_later_round_player_is_never_cleared_by_a_source_that_does_not_know(rnd, incoming, existing, expected):
    assert _keep_known(rnd, incoming, existing) is expected


# ── the agreement floor ───────────────────────────────────────────────────

class E:
    def __init__(self, pos, name, seed=None, nationality=None, te_slug=None):
        self.bracket_position, self.name, self.seed = pos, name, seed
        self.nationality, self.te_slug, self.entry_type = nationality, te_slug, None


def _shape(names):
    return DrawShape(bracket_size=8, num_rounds=3,
                     entrants=[ShapeEntrant(bracket_position=i + 1, name=n) for i, n in enumerate(names)])


def test_respellings_are_full_agreement():
    ours = [E(1, "Fábián Marozsán"), E(2, "Zhang Zhizhen"), E(3, "Cui Jie"), E(4, "Sára Bejlek")]
    theirs = _shape(["Fabian Marozsan", "Zhizhen Zhang", "Jie Cui", "Sara Bejlek"])
    assert _agreement(theirs, ours) == 1.0


def test_the_wrong_tournament_scores_near_zero_and_is_refused():
    ours = [E(i + 1, n) for i, n in enumerate(["Daniil Medvedev", "Andrey Rublev", "Adam Walton", "Valentin Royer"])]
    theirs = _shape(["Carlos Alcaraz", "Jannik Sinner", "Ben Shelton", "Holger Rune"])
    assert _agreement(theirs, ours) == 0.0 < REFRESH_AGREEMENT_FLOOR


def test_a_lucky_loser_replacing_one_player_still_clears_the_floor():
    ours = [E(i + 1, f"Player {i}") for i in range(28)]
    names = [f"Player {i}" for i in range(28)]
    names[5] = "Lucky Loser"
    assert _agreement(_shape(names), ours) >= REFRESH_AGREEMENT_FLOOR


def test_blank_qualifier_slots_do_not_count_either_way():
    ours = [E(1, "A"), E(2, ""), E(3, "C")]
    assert _agreement(_shape(["A", "", "C"]), ours) == 1.0
    assert _agreement(_shape(["A", "Now Named", "C"]), ours) == 1.0


def test_nothing_named_on_both_sides_is_no_agreement():
    assert _agreement(_shape(["", ""]), [E(1, ""), E(2, "")]) == 0.0


# ── the spellings the sources actually differ on ─────────────────────────

@pytest.mark.parametrize("a,b", [
    ("Fábián Marozsán", "Fabian Marozsan"), ("Zhang Zhizhen", "Zhizhen Zhang"),
    ("Cui Jie", "Jie Cui"), ("Tomás Martín Etcheverry", "Tomas Martin Etcheverry"),
    ("Cristina Bucșa", "Cristina Bucsa"), ("Liang En-shuo", "En-Shuo Liang"),
    # hyphen AND order at once — what held the WTA sheet off the Korea Open
    ("Park So-hyun", "Sohyun Park"), ("Back Da-yeon", "Dayeon Back"),
    ("Ku Yeon-woo", "Yeonwoo Ku"), ("Ma Yexin", "Ye-Xin Ma"),
])
def test_cross_source_spellings_are_the_same_person(a, b):
    """Measured 2026-09-21 between Wikipedia, the WTA sheet, Tennis Explorer
    and Sofascore. A False here would fire a phantom 'replaced' notice on
    takeover — which is why they are pinned."""
    assert same_person(a, b)


def test_a_real_replacement_is_still_a_replacement():
    assert not same_person("Daniil Medvedev", "Andrey Rublev")


# ── seed fill from Sofascore ─────────────────────────────────────────────

def test_a_seed_we_lack_is_offered_and_one_we_hold_is_not():
    ours = [E(1, "A Player", seed=None), E(2, "B Player", seed=2)]
    shape = DrawShape(bracket_size=2, num_rounds=1, entrants=[
        ShapeEntrant(bracket_position=1, name="A Player", seed=1),
        ShapeEntrant(bracket_position=2, name="B Player", seed=9)])   # 9 disagrees with our 2
    cmp = compare_to_entries(shape, ours)
    assert [(e.name, s) for e, s, _ in cmp["fillable"]] == [("A Player", 1)]
    assert cmp["seed"] == [("B Player", 2, 9)]                         # logged, never overwritten


# ── the writer, on a live draw, with a shape-only source ─────────────────

async def _db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_a_shape_only_rewrite_keeps_every_result_and_every_advancer(monkeypatch):
    """The hazard feedback_scraper_clears_espn_winner records, in the form a
    shape source would produce it: a ParsedDraw whose rounds 2+ are empty.
    Before the guard, `match.player1_id = p1_id` wiped every advancer.

    The writer's release stamp calls assign_rankings, which on an empty
    database scrapes Tennis Explorer's ranking pages — twelve requests from a
    unit test. Stubbed: rankings are not what this test is about."""
    import app.routers.tournaments as router
    import app.services.rankings as rankings

    async def no_rankings(*a, **k):
        return None
    for mod in (router, rankings):
        for name in ("assign_rankings", "assign_rankings_for_draw", "ensure_rankings"):
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, no_rankings)

    async def go():
        engine, Session = await _db()
        async with Session() as db:
            from datetime import date as _date
            d = Draw(name="Guard Open", year=2026, gender="M", draw_size=4, num_rounds=2,
                     wiki_page_title="Guard Open", status="upcoming",
                     start_date=_date(2026, 9, 23), end_date=_date(2026, 9, 29))   # a Wednesday start
            db.add(d); await db.flush()
            ents = [DrawEntry(draw_id=d.id, name=n, bracket_position=i + 1)
                    for i, n in enumerate(["Alpha One", "Beta Two", "Gamma Three", "Delta Four"])]
            db.add_all(ents); await db.flush()
            e = {x.bracket_position: x.id for x in ents}
            # Round 1 played; round 2 populated by those results, with a winner.
            db.add_all([
                Match(draw_id=d.id, round_number=1, match_number=1, player1_id=e[1], player2_id=e[2],
                      winner_id=e[1], status="completed", scores_json=[["6", "6"], ["3", "4"]]),
                Match(draw_id=d.id, round_number=1, match_number=2, player1_id=e[3], player2_id=e[4],
                      winner_id=e[4], status="completed", scores_json=[["2", "1"], ["6", "6"]]),
                Match(draw_id=d.id, round_number=2, match_number=1, player1_id=e[1], player2_id=e[4],
                      winner_id=e[4], status="completed", scores_json=[["4", "3"], ["6", "6"]]),
            ])
            await db.commit()

            shape = DrawShape(bracket_size=4, num_rounds=2, entrants=[
                ShapeEntrant(bracket_position=i + 1, name=n, seed=(1 if i == 0 else None))
                for i, n in enumerate(["Alpha One", "Beta Two", "Gamma Three", "Delta Four"])])
            parsed = shape_to_parsed(shape)
            assert parsed.carries_dates is False
            assert all(m.player1_position is None for m in parsed.matches if m.round_number == 2)
            await _do_scrape(d, db, parsed=parsed)
            await db.commit()

            ms = {(m.round_number, m.match_number): m for m in
                  (await db.execute(select(Match).where(Match.draw_id == d.id))).scalars()}
            assert (ms[(2, 1)].player1_id, ms[(2, 1)].player2_id) == (e[1], e[4]), "advancers wiped"
            assert ms[(2, 1)].winner_id == e[4] and ms[(2, 1)].status == "completed"
            assert ms[(1, 1)].winner_id == e[1] and ms[(1, 2)].winner_id == e[4]
            assert ms[(1, 1)].scores_json == [["6", "6"], ["3", "4"]]
            top = (await db.execute(select(DrawEntry).where(
                DrawEntry.draw_id == d.id, DrawEntry.bracket_position == 1))).scalar_one()
            assert top.seed == 1, "the shape's seed should have been written"
            fresh = await db.get(Draw, d.id)
            assert fresh.start_date == _date(2026, 9, 23), (
                "a shape source carries no dates; the Wednesday start must not be snapped to Monday")
        await engine.dispose()
    asyncio.run(go())
