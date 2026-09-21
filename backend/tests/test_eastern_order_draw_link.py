"""A sheet's hyphen, a draw's surname-first name, and the row between them.

Korea Open 2026-09-22 (doc 382): three main-draw R32 rows held their own
bracket match and printed its player — "[WC] Sohyun PARK KOR" against the
draw's "Park So-hyun", "[WC] Yeonwoo KU KOR" against "Ku Yeon-woo", "[Q]
Ye-Xin MA CHN" against "Ma Yexin" — and none was linked to a draw entry. The
ingest's subset match knew one spelling of a hyphen; `stamp_linked_rows`,
the pass for exactly this row, read the sheet's COUNTRY and the draw's GIVEN
name as the two surnames. The law had nothing that looked.
"""
import asyncio
import importlib
import pkgutil
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models
from app.database import Base
from app.models.schedule import ScheduleEntry, ScheduleEntryPlayer
from app.models.tournament import Draw, DrawEntry, Match, Tournament
from app.services.schedule import (_candidates, _entry_tokens, _resolve_players,
                                   surname_agrees)
from app.services.schedule_invariants import check_day

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")

DAY = date(2026, 9, 22)
ROSTER = [(5963, "Park So-hyun"), (5974, "Ku Yeon-woo"), (5982, "Ma Yexin"),
          (5964, "Robin Montgomery"), (5966, "Back Da-yeon"),
          (5967, "Yao Xinxin"), (5976, "Elena-Gabriela Ruse")]


def _draws():
    return [{'draw': None,
             'entries': [(eid, *_entry_tokens(nm)) for eid, nm in ROSTER]}]


def _resolve(*names):
    return asyncio.run(_resolve_players(None, _draws(), None, list(names)))


# ------------------------------------------------------------ THE INGEST

def test_the_sheet_joins_what_the_draw_hyphenates():
    assert _resolve("[WC] Sohyun PARK KOR", "[WC] Yeonwoo KU KOR") == [5963, 5974]


def test_the_sheet_hyphenates_what_the_draw_joins():
    assert _resolve("[Q] Ye-Xin MA CHN") == [5982]
    assert _candidates(_draws(), ["[Q] Ye-Xin MA CHN"]) == {5982}


def test_the_spellings_that_already_met_still_meet():
    assert _resolve("[4] Elena-Gabriela RUSE ROU", "Robin MONTGOMERY USA",
                    "Da-yeon BACK KOR") == [5976, 5964, 5966]


def test_a_probe_is_one_spelling_not_both():
    # A joined spelling must not let a different given name through.
    assert _resolve("Soyeon PARK KOR", "Ye-Jin MA CHN") == [None, None]


# ------------------------------------------------------- THE STAMP PASS

def test_the_country_is_not_the_surname():
    assert surname_agrees("Robin MONTGOMERY USA", "Robin Montgomery")
    assert surname_agrees("Mees ROTTGERING NED", "Mees Röttgering")
    assert surname_agrees("Beatriz HADDAD MAIA BRA", "Beatriz Haddad Maia")
    assert not surname_agrees("Robin MONTGOMERY USA", "Sofia Kenin")


def test_the_draw_may_write_the_surname_first():
    assert surname_agrees("[WC] Sohyun PARK KOR", "Park So-hyun")
    assert surname_agrees("[WC] Yeonwoo KU KOR", "Ku Yeon-woo")
    assert surname_agrees("[Q] Ye-Xin MA CHN", "Ma Yexin")
    assert not surname_agrees("[Q] Ye-Xin MA CHN", "Emerson Jones")


def test_a_run_of_initials_is_not_the_surname():
    assert surname_agrees("J.J. WOLF", "J. J. Wolf")


# -------------------------------------------------------------- THE LAW

async def _db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _center_court(db, *, park_id=None, printed="[WC] Sohyun PARK KOR"):
    db.add(Tournament(id=1, name="Korea Open", year=2026))
    db.add(Draw(id=146, tournament_id=1, name="Korea Open", year=2026, gender="F",
                draw_size=32, num_rounds=5,
                wiki_page_title="2026 Korea Open – Singles"))
    db.add(DrawEntry(id=5963, draw_id=146, name="Park So-hyun", bracket_position=11))
    db.add(DrawEntry(id=5964, draw_id=146, name="Robin Montgomery", bracket_position=12))
    db.add(Match(id=5401, draw_id=146, round_number=1, match_number=6,
                 player1_id=5963, player2_id=5964))
    e = ScheduleEntry(
        tournament_id=1, play_date=DAY, tour="WTA", stage="main",
        discipline="singles", round_label="R32", court="CENTER COURT",
        court_order=1, pairing_key="k", is_tbd=False, match_id=5401,
        draw_id=146, start_type="fixed", start_note="Starting at 12:00 PM",
        start_time_local="12:00 PM",
        first_seen_at=datetime(2026, 9, 21, 3, 43, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 9, 21, 3, 43, tzinfo=timezone.utc))
    db.add(e)
    db.add(ScheduleEntryPlayer(entry=e, side="a", position=1, raw_name=printed,
                               draw_entry_id=park_id))
    db.add(ScheduleEntryPlayer(entry=e, side="b", position=1,
                               raw_name="Robin MONTGOMERY USA", draw_entry_id=5964))
    await db.commit()


def _law(**kw):
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            await _center_court(db, **kw)
            out = await check_day(db, 1, DAY)
        await engine.dispose()
        return [v for v in out if v["code"] == "bracket_player_unlinked"]
    return asyncio.run(go())


def test_the_law_names_a_player_her_own_match_already_names():
    out = _law()
    assert len(out) == 1 and "entry 5963" in out[0]["detail"]


def test_the_law_is_quiet_once_she_is_linked():
    assert _law(park_id=5963) == []


def test_a_substitute_the_draw_has_not_caught_up_with_is_not_a_fault():
    assert _law(printed="[LL] Dayeon BACK KOR") == []
