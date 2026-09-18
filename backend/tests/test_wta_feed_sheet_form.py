"""The WTA feed's rows read like the sheet's, and a day the feed wrote can be
read again.

2026-09-18, 10:13 UTC: the first three days taken from the WTA's JSON (Korea,
Singapore, Guadalajara) re-stamped forty rows from "[2] Alexandra SHUBLADZE"
to "Alexandra Shubladze". `name_not_sheet_form` convicted every one. The alarm
was right — the page lost every [2] and [WC] a qualifying row reads off its
name, and the readers that find a surname by its capitals fell back to the last
word — and the rows could not heal: the feed that wrote them no longer stood
behind the day, and the sheet that should have taken it back was byte-identical
to a PDF already stored, so ingest skipped it as "unchanged".
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
from app.services.schedule import _clean_name, _fold
from app.services.schedule_invariants import _SHEET_CAPS_RE
from app.services.sofascore_doubles import _sheet_surnames
from app.services.wta_feed import matches_for_day

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")

DAY = date(2026, 9, 19)


def _row(first_a, last_a, first_b, last_b, *, seed_a="", entry_b="", nat_a="RUS",
         nat_b="KOR", doubles=False):
    r = {"CourtID": 1, "DateSeq": 1, "MatchTimeStamp": "2026-09-19T02:00:00Z",
         "RoundID": "1", "DrawMatchType": "D" if doubles else "S",
         "PlayerNameFirstA": first_a, "PlayerNameLastA": last_a, "PlayerCountryA": nat_a,
         "PlayerNameFirstB": first_b, "PlayerNameLastB": last_b, "PlayerCountryB": nat_b,
         "SeedA": seed_a, "SeedB": "", "EntryTypeA": "", "EntryTypeB": entry_b}
    if doubles:
        r.update({"PlayerNameFirstA2": "Anastasia", "PlayerNameLastA2": "Tikhonova",
                  "PlayerCountryA2": "", "PlayerNameFirstB2": "Luisa",
                  "PlayerNameLastB2": "Stefani", "PlayerCountryB2": "BRA"})
    return r


def _one(row):
    (m,) = matches_for_day([row], DAY, court_names={"Court 1": "CENTRE COURT"})
    return m


def test_a_feed_row_is_printed_the_way_the_sheet_prints_it():
    m = _one(_row("Alexandra", "Shubladze", "Gaeul", "Jang", seed_a="2", entry_b="WC"))
    assert m.side_a == ["[2] Alexandra SHUBLADZE RUS"]
    assert m.side_b == ["[WC] Gaeul JANG KOR"]
    assert m.nations_a == ["RUS"] and m.nations_b == ["KOR"]
    for name in m.side_a + m.side_b:
        assert _SHEET_CAPS_RE.search(name), name        # name_not_sheet_form's own test


def test_the_feed_and_the_sheet_name_the_same_person_the_same_way():
    # The sheet withholds a neutral athlete's country; the feed states it.
    # Every reader that keys a row on its name must still see one player.
    feed = _one(_row("Alexandra", "Shubladze", "Eunhye", "Lee", seed_a="2", entry_b="WC"))
    for fed, printed in ((feed.side_a[0], "[2] Alexandra SHUBLADZE"),
                         (feed.side_b[0], "[WC] Eunhye LEE KOR")):
        assert _clean_name(fed) == _clean_name(printed)
        assert _fold(fed) == _fold(printed)
        assert _sheet_surnames([fed]) == _sheet_surnames([printed])
    # The three-letter surname survives: without the country after it, _fold
    # took LEE for one and folded her to plain "eunhye".
    assert "lee" in _fold(feed.side_b[0])


def test_a_two_word_surname_is_capitalised_whole():
    m = _one(_row("Beatriz", "Haddad Maia", "Gaeul", "Jang"))
    assert m.side_a == ["Beatriz HADDAD MAIA RUS"]
    assert _sheet_surnames(m.side_a) == {"haddad", "maia"}


def test_a_doubles_seed_goes_on_the_first_partner_only():
    m = _one(_row("Valeriya", "Strakhova", "Gabriela", "Dabrowski", seed_a="2",
                  nat_a="UKR", nat_b="CAN", doubles=True))
    # A partner with no country in the feed prints none, as on the sheet.
    assert m.side_a == ["[2] Valeriya STRAKHOVA UKR", "Anastasia TIKHONOVA"]
    assert m.side_b == ["Gabriela DABROWSKI CAN", "Luisa STEFANI BRA"]


def test_an_unknown_country_code_stays_off_the_name():
    # Anything else in that position is `name_trailing_noncountry`.
    m = _one(_row("Alexandra", "Shubladze", "Gaeul", "Jang", nat_a="XYZ"))
    assert m.side_a == ["Alexandra SHUBLADZE"]


def test_a_row_without_a_given_name_is_left_as_written():
    m = _one(_row("", "Qualifier", "Gaeul", "Jang"))
    assert m.side_a == ["Qualifier"]


# ------------------------------------------------------------------ INGEST

FEED_URL = "https://api.wtatennis.com/tennis/tournaments/1024/2026/matches"
PDF_URL = "https://wtafiles.wtatennis.com/pdf/draws/2026/1024/OP.pdf"


def _m(court, a, b):
    return Match(court=court, time="11:00", tour="WTA", round="Q1",
                 discipline="singles", start_raw="11:00", side_a=[a], side_b=[b])


SHEET = [_m("CENTRE COURT", "[2] Alexandra SHUBLADZE", "[WC] Gaeul JANG KOR")]
OLD_FEED = [_m("", "Alexandra Shubladze", "Gaeul Jang")]
NEW_FEED = [_m("", "[2] Alexandra SHUBLADZE RUS", "[WC] Gaeul JANG KOR")]


def _parser(matches):
    return lambda _bytes: (list(matches), {"kind": "ok"})


async def _names(db, tid):
    from app.models.schedule import ScheduleEntry, ScheduleEntryPlayer
    rows = (await db.execute(
        select(ScheduleEntry.court, ScheduleEntryPlayer.raw_name)
        .join(ScheduleEntryPlayer, ScheduleEntryPlayer.schedule_entry_id == ScheduleEntry.id)
        .where(ScheduleEntry.tournament_id == tid, ScheduleEntry.play_date == DAY)
        .order_by(ScheduleEntryPlayer.side))).all()
    return [(c, n) for c, n in rows]


async def _flow(monkeypatch):
    from app.models.tournament import Tournament

    async def _quiet(*a, **k):
        return None
    monkeypatch.setattr(system_log, "app_log", _quiet)
    monkeypatch.setattr(schedule_svc, "parse_pdf", _parser(SHEET))

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        t = Tournament(id=97, name="Korea Open", year=2026)
        db.add(t)
        await db.commit()

        async def sheet(**kw):
            return await schedule_svc.ingest_document(
                db, t, DAY, PDF_URL, b"%PDF sheet", tour="WTA", queue_verify=False, **kw)

        async def feed(matches):
            return await schedule_svc.ingest_document(
                db, t, DAY, FEED_URL, b'[{"MatchID":"QS001"}]', tour="WTA",
                parser=_parser(matches), queue_verify=False)

        first = await sheet()
        assert "skipped" not in first
        # The sheet's bytes again, with nothing else in between: nothing to do.
        assert (await sheet())["skipped"] == "unchanged"

        # The feed takes the day (the 10:13 UTC ingest: no court, plain names).
        assert "skipped" not in await feed(OLD_FEED)
        assert await _names(db, 97) == [("", "Alexandra Shubladze"), ("", "Gaeul Jang")]

        # A feed that FAILED hands the sheet nothing to reclaim with.
        assert (await sheet(reclaim=False))["skipped"] == "unchanged"
        assert await _names(db, 97) == [("", "Alexandra Shubladze"), ("", "Gaeul Jang")]

        # A feed that DECLINED the day: the sheet takes it back, although
        # its bytes are the ones already stored.
        assert "skipped" not in await sheet()
        assert await _names(db, 97) == [("CENTRE COURT", "[2] Alexandra SHUBLADZE"),
                                         ("CENTRE COURT", "[WC] Gaeul JANG KOR")]
        # ...and then holds it.
        assert (await sheet())["skipped"] == "unchanged"

        # The feed, back with the SAME bytes it sent before, retakes the day.
        assert "skipped" not in await feed(OLD_FEED)
        assert await _names(db, 97) == [("", "Alexandra Shubladze"), ("", "Gaeul Jang")]
        # Same bytes, same parse: nothing to do.
        assert "skipped" in await feed(OLD_FEED)
        # Same bytes, CORRECTED parse: the correction reaches the day.
        assert "skipped" not in await feed(NEW_FEED)
        assert await _names(db, 97) == [("", "[2] Alexandra SHUBLADZE RUS"),
                                         ("", "[WC] Gaeul JANG KOR")]
        assert "skipped" in await feed(NEW_FEED)
    await engine.dispose()


def test_a_day_the_feed_wrote_can_be_read_again(monkeypatch):
    asyncio.run(_flow(monkeypatch))
