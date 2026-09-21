"""The champion's aces are read from where stats_for puts them.

2026-09-20/21: the Guadalajara, SP Open and both US Open finals recorded their
sets and minutes and never their aces — "still no winner_aces" on every one.
The code blamed Sofascore ("the 2026 Guadalajara final returned zero rows"),
but a read of that event's statistics on 2026-09-21 returned nine rows under
ALL, aces 5 and 4. capture_final_stats looked for the rows at `stats["ALL"]`;
stats_for returns them at `stats["periods"]["ALL"]`. So the aces key was null
on every final ever captured, and the SECOND tiebreak key never decided a
thing.

These tests drive the real stats_for over a Sofascore-shaped payload, so the
two can never disagree about the shape again without one of them failing here.
"""
import asyncio
import importlib
import pkgutil
from datetime import date

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.database
import app.models  # noqa: F401
from app.database import Base
from app.models.tournament import Draw, DrawEntry, Match
from app.services import final_tiebreak, sofascore, sofascore_results, sofascore_stats, system_log

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")

EVENT = 17066559
HOME_SOFA, AWAY_SOFA = 1111, 420632


def _payloads(home_aces, away_aces):
    event = {"event": {
        "id": EVENT,
        "homeTeam": {"id": HOME_SOFA}, "awayTeam": {"id": AWAY_SOFA},
        "time": {"period1": 2640, "period2": 2580},
    }}
    stats = {"statistics": [{"period": p, "groups": [{
        "groupName": "Service",
        "statisticsItems": [
            {"name": "Aces", "home": str(h), "away": str(a), "homeValue": h, "awayValue": a},
            {"name": "Double faults", "home": "4", "away": "2", "homeValue": 4, "awayValue": 2},
        ]}]} for p, h, a in (("ALL", home_aces, away_aces), ("1ST", 3, 1), ("2ND", 2, 3))]}
    return {f"/event/{EVENT}": event, f"/event/{EVENT}/statistics": stats}


def _capture(monkeypatch, *, winner_side, home_aces=5, away_aces=4):
    async def go():
        engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        pages = _payloads(home_aces, away_aces)

        async def _get(path, *a, **k):
            return pages.get(path)

        async def _log(*a, **k):
            return None

        monkeypatch.setattr(app.database, "AsyncSessionLocal", Session)
        monkeypatch.setattr(sofascore, "_get", _get)
        monkeypatch.setattr(system_log, "app_log", _log)
        monkeypatch.setattr(sofascore_results, "_FINAL_TRIED", {})
        monkeypatch.setattr(sofascore_stats, "_CACHE", {})

        async with Session() as db:
            d = Draw(name="Guadalajara Open", year=2026, gender="F", draw_size=32,
                     wiki_page_title="2026 Guadalajara Open – Singles",
                     num_rounds=5, status="active",
                     start_date=date(2026, 9, 13), end_date=date(2026, 9, 19))
            db.add(d)
            await db.flush()
            home = DrawEntry(draw_id=d.id, name="Home Player", bracket_position=1,
                             sofa_player_id=HOME_SOFA)
            away = DrawEntry(draw_id=d.id, name="Iva Jovic", bracket_position=2,
                             sofa_player_id=AWAY_SOFA)
            db.add_all([home, away])
            await db.flush()
            winner = away if winner_side == "away" else home
            scores = ([["4", "2"], ["6", "6"]] if winner_side == "away"
                      else [["6", "6"], ["4", "2"]])
            db.add(Match(draw_id=d.id, round_number=5, match_number=1,
                         player1_id=home.id, player2_id=away.id, winner_id=winner.id,
                         is_bye=False, status="completed", scores_json=scores,
                         sofa_scores_json=scores, sofa_event_id=EVENT,
                         sofa_duration_min=46))
            await db.commit()
            draw_id = d.id

        await sofascore_results.capture_final_stats()

        async with Session() as db:
            d = await db.get(Draw, draw_id)
            got = (d.final_sets, d.final_winner_aces, d.final_duration_min)
        await engine.dispose()
        return got

    return asyncio.run(go())


def test_the_champions_aces_are_recorded_when_she_sat_away(monkeypatch):
    # Guadalajara 2026: Jovic won 6-4 6-2 from the away side.
    assert _capture(monkeypatch, winner_side="away") == (2, 4, 87)


def test_the_champions_aces_are_recorded_when_she_sat_home(monkeypatch):
    assert _capture(monkeypatch, winner_side="home") == (2, 5, 87)


def test_zero_aces_is_an_answer_not_a_missing_one(monkeypatch):
    assert _capture(monkeypatch, winner_side="away", away_aces=0) == (2, 0, 87)


# ---------------------------------------------------- THE GUESS, BY ITS NAME

def test_the_guess_fields_are_named_for_what_they_hold():
    """guesses_for returns (sets, aces, minutes). The standings rows read [0]
    as the aces and [1] as the minutes — the layout from before the sets
    question — so a bracket that said 3 sets, 9 aces, 140 minutes was served
    as aces 3, minutes 9."""
    assert final_tiebreak.guess_fields((3, 9, 140)) == {
        "final_guess_sets": 3, "final_guess_aces": 9, "final_guess_minutes": 140}
    assert final_tiebreak.guess_fields((None, 9, 140))["final_guess_aces"] == 9
    assert final_tiebreak.guess_fields(None) == {
        "final_guess_sets": None, "final_guess_aces": None, "final_guess_minutes": None}
