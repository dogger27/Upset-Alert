"""A country the tour withholds is withheld on the page too.

2026-09-18, Guadalajara doc 298: the sheet printed "[8] Liudmila SAMSONOVA"
with no country, as every sheet prints a neutral athlete, and the page flew a
Russian flag beside her. The WTA feed that had held the day at 10:13 UTC states
PlayerCountry "RUS"; it wrote the code onto the row, and when the sheet took
the day back its None could not erase it. Singapore (Lansere) and Korea
(Shubladze, Ibragimova, Astakhova) carried the same flag from the same feed.
"""
import asyncio
import importlib
import pkgutil
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.services import schedule as schedule_svc
from app.services import system_log
from app.services.oop_parser import Match
from app.services.schedule_invariants import check_day
from app.services.sofa_schedule import _names as sofa_names
from app.services.wta_feed import matches_for_day

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")

DAY = date(2026, 9, 18)


def _wta(nat_a, nat_b="USA", *, doubles=False, nat_a2=""):
    r = {"CourtID": 1, "DateSeq": 3, "MatchTimeStamp": "2026-09-18T20:00:00Z",
         "RoundID": "S", "DrawMatchType": "D" if doubles else "S",
         "PlayerNameFirstA": "Liudmila", "PlayerNameLastA": "Samsonova",
         "PlayerCountryA": nat_a, "SeedA": "8", "EntryTypeA": "",
         "PlayerNameFirstB": "Peyton", "PlayerNameLastB": "Stearns",
         "PlayerCountryB": nat_b, "SeedB": "", "EntryTypeB": ""}
    if doubles:
        r.update({"PlayerNameFirstA2": "Aliaksandra", "PlayerNameLastA2": "Sasnovich",
                  "PlayerCountryA2": nat_a2, "PlayerNameFirstB2": "Taylor",
                  "PlayerNameLastB2": "Townsend", "PlayerCountryB2": "USA"})
    return r


def test_the_wta_feed_prints_a_neutral_athlete_as_the_sheet_does():
    (m,) = matches_for_day([_wta("RUS")], DAY, court_names={"Court 1": "ESTADIO SKARCH"})
    assert m.side_a == ["[8] Liudmila SAMSONOVA"]      # the sheet, verbatim
    assert m.nations_a == [""]
    assert m.side_b == ["Peyton STEARNS USA"] and m.nations_b == ["USA"]


def test_a_neutral_doubles_partner_is_withheld_and_her_partner_is_not():
    (m,) = matches_for_day([_wta("UKR", doubles=True, nat_a2="BLR")], DAY)
    assert m.side_a == ["[8] Liudmila SAMSONOVA UKR", "Aliaksandra SASNOVICH"]
    assert m.nations_a == ["UKR", ""]


def test_sofascore_states_no_neutral_country_either():
    names, nations = sofa_names({"name": "Medvedev D.", "country": {"alpha3": "RUS"}})
    assert nations == [""]
    _, nations = sofa_names({"name": "Sinner J.", "country": {"alpha3": "ITA"}})
    assert nations == ["ITA"]


# ------------------------------------------------------------------ INGEST

FEED_URL = "https://api.wtatennis.com/tennis/tournaments/2075/2026/matches"
PDF_URL = "https://wtafiles.wtatennis.com/pdf/draws/2026/2075/OP.pdf"


def _m(a, nat_a, b="Peyton STEARNS USA", start_raw="Followed by"):
    # The feed states its clock ("Est. 18:50") where the sheet prints a
    # wording, so a source switch is a content change and re-syncs the rows.
    return Match(court="ESTADIO SKARCH", time="17:00", tour="WTA", round="SF",
                 discipline="singles", start_raw=start_raw,
                 side_a=[a], side_b=[b], nations_a=nat_a, nations_b=[])


def _parser(matches):
    return lambda _bytes: (list(matches), {"kind": "ok"})


async def _flow(monkeypatch):
    from app.models.schedule import ScheduleEntry, ScheduleEntryPlayer
    from app.models.tournament import Tournament

    async def _quiet(*a, **k):
        return None
    monkeypatch.setattr(system_log, "app_log", _quiet)

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def samsonova(db):
        return (await db.execute(
            select(ScheduleEntryPlayer).join(ScheduleEntry).where(
                ScheduleEntry.tournament_id == 35,
                ScheduleEntryPlayer.side == "a"))).scalars().one()

    async def codes(db):
        return [v["code"] for v in await check_day(db, 35, DAY)
                if v["code"] == "withheld_nation_served"]

    async with Session() as db:
        t = Tournament(id=35, name="Guadalajara Open", year=2026)
        db.add(t)
        await db.commit()

        # Whatever a source states, a withheld country is never stored.
        await schedule_svc.ingest_document(
            db, t, DAY, FEED_URL, b'[{"MatchID":"LS029"}]', tour="WTA",
            parser=_parser([_m("[8] Liudmila SAMSONOVA", ["RUS"], start_raw="Est. 18:50")]),
            queue_verify=False)
        await db.commit()
        p = await samsonova(db)
        assert p.nationality is None
        assert await codes(db) == []

        # The row the 10:13 UTC feed left, before this fix: the law sees both
        # halves — the stored code and the one glued to the name.
        p.nationality = "RUS"
        p.raw_name = "[8] Liudmila SAMSONOVA RUS"
        await db.commit()
        assert await codes(db) == ["withheld_nation_served"]
        p.nationality = None
        await db.commit()
        assert await codes(db) == ["withheld_nation_served"]
        p.nationality = "RUS"
        await db.commit()

        # The sheet takes the day back, stating no country — and that None
        # now erases the feed's.
        monkeypatch.setattr(schedule_svc, "parse_pdf",
                            _parser([_m("[8] Liudmila SAMSONOVA", [])]))
        r = await schedule_svc.ingest_document(
            db, t, DAY, PDF_URL, b"%PDF sheet", tour="WTA", queue_verify=False)
        assert "skipped" not in r
        await db.commit()
        p = await samsonova(db)
        assert (p.raw_name, p.nationality) == ("[8] Liudmila SAMSONOVA", None)
        assert await codes(db) == []

        # A surname is not a country: Arantxa RUS (NED) keeps hers.
        p.raw_name, p.nationality = "Arantxa RUS", "NED"
        await db.commit()
        assert await codes(db) == []
        p.raw_name = "Arantxa RUS NED"
        await db.commit()
        assert await codes(db) == []
    await engine.dispose()


def test_a_withheld_country_is_never_stored_and_a_stored_one_heals(monkeypatch):
    asyncio.run(_flow(monkeypatch))
