"""A country the tour withholds is withheld on the page too.

2026-09-18, Guadalajara doc 298: the sheet printed "[8] Liudmila SAMSONOVA"
with no country, as every sheet prints a neutral athlete, and the page flew a
Russian flag beside her. The WTA feed that had held the day at 10:13 UTC states
PlayerCountry "RUS"; it wrote the code onto the row, and when the sheet took
the day back its None could not erase it. Singapore (Lansere) and Korea
(Shubladze, Ibragimova, Astakhova) carried the same flag from the same feed.

2026-09-21, Korea Open "Alina KORNEEVA": the same flag, by the one road that
fix did not close. Nothing was stored on her row — the SERVE path prefers her
DRAW ENTRY, and `assign_rankings` fills a blank draw-entry nationality from
Tennis Explorer for exactly the neutral athletes Wikipedia leaves blank, so
the bracket can fly those flags (2026-07-11, "Show RU/BY flags"). The bracket
keeps them; the sheet's row does not borrow them.
"""
import asyncio
import importlib
import pkgutil
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.services import schedule as schedule_svc
from app.services import system_log
from app.routers.schedule import _player_out
from app.services.oop_parser import Match, served_nation
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
    (m,) = matches_for_day([_wta("RUS")], DAY, court_names={"CourtID 1": "ESTADIO SKARCH"})
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


# ------------------------------------------------------------------- SERVED


def test_the_bracket_may_hold_a_country_the_sheets_row_may_not_show():
    # Draw entry first, then the row's own code — and a withheld one ENDS the
    # question rather than falling through to fly some other flag.
    assert served_nation("THA", None) == "THA"
    assert served_nation(None, "USA") == "USA"
    assert served_nation("RUS", None) is None
    assert served_nation("BLR", "UKR") is None
    assert served_nation("  rus  ", None) is None
    assert served_nation(None, None) is None and served_nation("", "") is None


def _p(name, entry_id, nat=None):
    return SimpleNamespace(side="a", position=1, raw_name=name,
                           draw_entry_id=entry_id, nationality=nat)


def test_the_schedule_row_does_not_borrow_the_brackets_russian_flag():
    # Korea Open 2026-09-21, SHOW COURT 1, exactly as production served it.
    out = _player_out(_p("Alina KORNEEVA", 5957), {5957: "RUS"}, {}, {}, {}, True)
    assert out.nationality is None
    # Her opponent, from the same draw, keeps hers.
    out = _player_out(_p("Mananchaya SAWANGKAEW THA", 5958), {5958: "THA"},
                      {}, {}, {}, True)
    assert out.nationality == "THA"
    # And the sheet's own column, where no draw entry has resolved yet.
    assert _player_out(_p("Anna BLINKOVA", None, "RUS"),
                       {}, {}, {}, {}, True).nationality is None
    assert _player_out(_p("Maya JOINT AUS", None, "AUS"),
                       {}, {}, {}, {}, True).nationality == "AUS"


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
    from app.models.tournament import Draw, DrawEntry, Tournament

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

        # THE DRAW ENTRY, which the serve path prefers and which holds the
        # country on purpose — Korea Open 2026-09-21. The law reads what is
        # SERVED, so the bracket's RUS is no fault of the sheet's row; it is
        # only a fault if it reaches the row, and `served_nation` is what
        # stops it. The name's trailing code is still judged beside it.
        db.add(Draw(id=1, tournament_id=35, name="Guadalajara Open", year=2026,
                    gender="F", draw_size=32, num_rounds=5,
                    wiki_page_title="2026 Guadalajara Open"))
        await db.flush()
        de = DrawEntry(draw_id=1, name="Liudmila Samsonova", nationality="RUS",
                       bracket_position=1)
        db.add(de)
        await db.flush()
        p.raw_name, p.nationality, p.draw_entry_id = (
            "[8] Liudmila SAMSONOVA", None, de.id)
        await db.commit()
        assert await codes(db) == []
        assert _player_out(p, {de.id: de.nationality}, {}, {}, {},
                           True).nationality is None

        # The same row with the code glued to the name is still a fault: that
        # one really does reach the page, by a road `served_nation` never sees.
        p.raw_name = "[8] Liudmila SAMSONOVA RUS"
        await db.commit()
        assert await codes(db) == ["withheld_nation_served"]
    await engine.dispose()


def test_a_withheld_country_is_never_stored_and_a_stored_one_heals(monkeypatch):
    asyncio.run(_flow(monkeypatch))
