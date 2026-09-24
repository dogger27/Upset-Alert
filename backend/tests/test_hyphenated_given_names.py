"""A hyphen is two spellings, and a player who has not played is not news.

2026-09-19, Korea Open 2026. Our draw spells two Korean players "Park So-hyun"
and "Back Da-yeon"; Tennis Explorer and TML write "Sohyun Park" and "Dayeon
Back". Every name comparison split the hyphen, so {park, so, hyun} matched
nothing strictly and the loose prefix rule matched the leftovers: "hyun" is
the start of "hyunyee", and she was linked to Lee Hyunyee. The nightly repair
cleared the link as unmatchable ("1 cleared as unmatchable") and the roster
sweep, finding her unlinked, put it straight back — a loop that warned every
run. Rule 5's guard should have refused it, but it compared the matched pair
with itself ("hyun" and "hyunyee" share "hyu"), so it could never fire.

The same night the linkage warned "NEW: unlinked" for Back Da-yeon, whose TML
record exists under the solid spelling. And that warning was already a false
alarm by construction: on 2026-09-14 it fired for Hayu Kinoshita, a debutant
the night before her first match, who linked by match the day she played.
"""
import asyncio
import importlib
import json
import pkgutil
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.database
import app.models  # noqa: F401
import app.services.system_log
from app.database import Base
from app.models.rankings import TePlayer
from app.models.tournament import Draw, DrawEntry, Match, Tournament
from app.services.history import db as hdb
from app.services.history.link import link_all_async, names_agree, repair_te_links
from app.services.history.tml import name_key, name_keys
from app.services.rankings import _match_token_set, _norm

for _m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_m.name}")


def _index(*names):
    """Tennis Explorer's "Surname Given" rows, ids from 1."""
    idx = {}
    for i, n in enumerate(names, 1):
        idx.setdefault(frozenset(_norm(n).split()), []).append(i)
    return idx


KOREA = _index("Park Sohyun", "Lee Hyunyee", "Parks Alycia", "Back Dayeon", "Ku Yeon Woo")


# ------------------------------------------------------------ THE MATCHER

def test_a_hyphenated_given_name_finds_its_solid_spelling():
    assert _match_token_set("Park So-hyun", KOREA) == 1
    assert _match_token_set("Back Da-yeon", KOREA) == 4


def test_a_split_given_name_still_matches_a_split_one():
    assert _match_token_set("Ku Yeon-woo", KOREA) == 5


def test_western_double_barrels_stay_two_words():
    idx = _index("Auger Aliassime Felix", "Struff Jan Lennard", "Ruse Elena Gabriela")
    assert _match_token_set("Félix Auger-Aliassime", idx) == 1
    assert _match_token_set("Jan-Lennard Struff", idx) == 2
    assert _match_token_set("Elena-Gabriela Ruse", idx) == 3


def test_a_prefix_is_not_a_player_when_nothing_else_agrees():
    """Without Sohyun Park in the index there is no one to link — not the
    player whose given name "hyun" begins, nor the one "park" begins."""
    idx = _index("Lee Hyunyee", "Parks Alycia")
    assert _match_token_set("Park So-hyun", idx) is None


def test_a_prefix_that_was_a_different_player():
    """The same guard, found by the corpus audit: "alexandre" begins
    "alexandrescou", and the vacuous guard waved it through."""
    idx = _index("Alexandrescou Yannick Theodor", "Muller Alexandre")
    assert _match_token_set("Alexandre Müller", idx) == 2
    assert _match_token_set("Alexandre Zzyzx", _index("Alexandrescou Yannick Theodor")) is None


def test_a_nickname_still_finds_the_given_name():
    idx = _index("Nadal Rafael", "Wawrinka Stanislas", "Ruud Casper")
    assert _match_token_set("Rafa Nadal", idx) == 1
    assert _match_token_set("Stan Wawrinka", idx) == 2


# ------------------------------------------------------------ NAME KEYS

def test_name_keys_file_a_hyphen_both_ways():
    assert name_keys("Park So-hyun") == {"hyun park so", "park sohyun"}
    assert name_keys("Sohyun Park") == {name_key("Sohyun Park")} == {"park sohyun"}
    assert name_keys("") == set()


def test_names_agree_across_the_hyphen():
    assert names_agree("Park So-hyun", "Sohyun Park")
    assert names_agree("Back Da-yeon", "Dayeon Back")
    assert not names_agree("Park So-hyun", "Hyunyee Lee")
    assert not names_agree("Park So-hyun", "Alycia Parks")


# ------------------------------------------------------------ REPAIR + LINKAGE

async def _db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _korea_open(db, *, days_from_now=2):
    t = Tournament(name="Korea Open", year=2026)
    db.add(t)
    await db.flush()
    start = date.today() + timedelta(days=days_from_now)
    d = Draw(tournament_id=t.id, name="Korea Open", year=2026, gender="F", draw_size=32, num_rounds=5, category="WTA 500",
             wiki_page_title="2026 Korea Open – Singles", start_date=start, end_date=start + timedelta(days=6))
    db.add(d)
    tes = [TePlayer(id=i, gender="F", name_raw=raw, name_norm=_norm(raw), name_display=disp, te_slug=slug)
           for i, raw, disp, slug in [(2539, "Park Sohyun", "Sohyun Park", "park-aa1d7"),
                                      (4570, "Lee Hyunyee", "Hyunyee Lee", "lee-88b86"),
                                      (2550, "Back Dayeon", "Dayeon Back", "back-6aabb"),
                                      (9001, "Newcomer Debut", "Debut Newcomer", "newcomer-x")]]
    db.add_all(tes)
    await db.flush()
    park = DrawEntry(draw_id=d.id, name="Park So-hyun", bracket_position=1, te_player_id=4570, te_slug="lee-88b86")
    back = DrawEntry(draw_id=d.id, name="Back Da-yeon", bracket_position=2, te_player_id=2550)
    new = DrawEntry(draw_id=d.id, name="Debut Newcomer", bracket_position=3, te_player_id=9001)
    db.add_all([park, back, new])
    await db.commit()
    return d, park, back, new


def _tml(tmp_path, monkeypatch, baseline=None):
    monkeypatch.setattr(hdb.settings, "history_db_path", str(tmp_path / "history.db"))
    conn = hdb.connect()
    with conn:
        for pid, name in [("216213", "Sohyun Park"), ("220432", "Dayeon Back"), ("999", "Hyunyee Lee")]:
            conn.execute("INSERT INTO tml_players (tour, player_id, name, name_key, last_date, n_matches) "
                         "VALUES ('wta', ?, ?, ?, '2025-09-15', 8)", (pid, name, name_key(name)))
        if baseline is not None:
            hdb.set_meta(conn, "link_counts", json.dumps(baseline))
    conn.close()


def test_the_repair_re_points_rather_than_clears(tmp_path, monkeypatch):
    """The link it used to clear — and the sweep used to restore — now goes
    to the player her name names."""
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            _, park, _, _ = await _korea_open(db)
            out = await repair_te_links(db)
            await db.refresh(park)
        await engine.dispose()
        return out, park
    out, park = asyncio.run(go())
    assert out["cleared"] == []
    assert [f["now"] for f in out["fixed"]] == ["Sohyun Park"]
    assert (park.te_player_id, park.te_slug) == (2539, "park-aa1d7")


def test_the_linkage_is_quiet_and_links_both_spellings(tmp_path, monkeypatch):
    """Both Korean players link to TML by name; the debutant, in a draw not
    yet played, is listed but raises no alarm — against a baseline of zero."""
    _tml(tmp_path, monkeypatch, baseline={"stuck": 0, "unlinked": 0, "conflicts": 0, "bad_te_links": 0})
    said = []

    async def _log(level, category, message, *a, **k):
        said.append((level, message))
    monkeypatch.setattr(app.services.system_log, "app_log", _log)

    async def go():
        engine, Session = await _db()
        monkeypatch.setattr(app.database, "AsyncSessionLocal", Session)
        async with Session() as db:
            await _korea_open(db)
        report = await link_all_async()
        async with Session() as db:
            got = {p.id: p.tml_player_id for p in (await db.execute(
                TePlayer.__table__.select())).fetchall()}
        await engine.dispose()
        return report, got
    report, got = asyncio.run(go())
    assert got[2539] == "216213" and got[2550] == "220432"
    assert [u["name"] for u in report["unlinked"]] == ["Debut Newcomer"]
    assert report["unlinked"][0]["played"] is False
    assert all(level == "info" for level, _ in said), said


def test_an_unlinked_player_who_has_played_is_still_news(tmp_path, monkeypatch):
    """The alarm keeps its teeth: a completed match, in a draw TML has had
    time to publish, and still no TML player — that is a linkage failure.
    (The draw itself is a standing "stuck" one: this TML has no tournaments.)"""
    _tml(tmp_path, monkeypatch, baseline={"stuck": 1, "unlinked": 0, "conflicts": 0, "bad_te_links": 0})
    said = []

    async def _log(level, category, message, *a, **k):
        said.append((level, message))
    monkeypatch.setattr(app.services.system_log, "app_log", _log)

    async def go():
        engine, Session = await _db()
        monkeypatch.setattr(app.database, "AsyncSessionLocal", Session)
        async with Session() as db:
            d, _, back, new = await _korea_open(db, days_from_now=-30)
            db.add(Match(draw_id=d.id, round_number=1, match_number=1, player1_id=new.id,
                         player2_id=back.id, winner_id=new.id, is_bye=False))
            await db.commit()
        report = await link_all_async()
        await engine.dispose()
        return report
    report = asyncio.run(go())
    assert [(u["name"], u["played"]) for u in report["unlinked"]] == [("Debut Newcomer", True)]
    warned = [m for level, m in said if level == "warning"]
    assert len(warned) == 1 and warned[0].endswith("— NEW: unlinked")


# ------------------------------------------------- THE ORDER OF PLAY'S LOOKUP
#
# 2026-09-20, Korea Open Q2 (doc 348): the sheet's "[5] Ye-Xin MA CHN" keyed as
# "ye xin ma"; Tennis Explorer files her "Yexin Ma", so the card served her
# with no ranking, no Elo and no head-to-head link. The page's by-name lookup
# (routers/schedule) had been left out of the 09-19 fix.

from app.routers.schedule import (_by_name, _name_keys, _name_words,  # noqa: E402
                                  _profiles_by_name, _slugs_by_name)


def test_the_sheet_name_is_filed_under_both_spellings():
    assert _name_words("[5] Ye-Xin MA CHN") == "Ye-Xin MA"
    assert _name_keys("[5] Ye-Xin MA CHN") == {"ye xin ma", "yexin ma"}
    assert _name_keys("[1] Maya JOINT AUS") == {"maya joint"}


def test_two_spellings_reaching_two_people_is_no_answer():
    assert _by_name({"yexin ma": "ma-1"}, "Ye-Xin MA") == "ma-1"
    assert _by_name({"yexin ma": "ma-1", "ye xin ma": "ma-2"}, "Ye-Xin MA") is None
    assert _by_name({"yexin ma": None}, "Ye-Xin MA") is None


def test_the_order_of_play_links_a_solid_spelling_either_way_round():
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            db.add_all([
                TePlayer(gender="F", name_raw="Ma Yexin", name_norm="ma yexin",
                         name_display="Yexin Ma", te_slug="ma-2d7c9"),
                TePlayer(gender="F", name_raw="Xu Yi-Fan", name_norm="xu yi fan",
                         name_display="Yi-Fan Xu", te_slug="xu-f5123"),
                TePlayer(gender="F", name_raw="Joint Maya", name_norm="joint maya",
                         name_display="Maya Joint", te_slug="joint-2322"),
            ])
            await db.commit()
            raws = ["[5] Ye-Xin MA CHN", "Yifan XU CHN", "[1] Maya JOINT AUS"]
            slugs = await _slugs_by_name(db, raws)
            profiles = await _profiles_by_name(db, raws)
        await engine.dispose()
        return slugs, profiles
    slugs, profiles = asyncio.run(go())
    assert [_by_name(slugs, r) for r in ("[5] Ye-Xin MA CHN", "Yifan XU CHN",
                                         "[1] Maya JOINT AUS")] == [
        "ma-2d7c9", "xu-f5123", "joint-2322"]
    assert _by_name(profiles, "[5] Ye-Xin MA CHN") is not None


# ------------------------------------------- THE ORDER OF PLAY'S OWN IDENTITY
#
# 2026-09-20 02:04 UTC, Korea Open, GRANDSTAND. The WTA feed stopped printing
# the Q2 it had carried all Saturday (entry 1318, "[WC] Eunhye LEE KOR" vs
# "[5] Ye-Xin MA CHN", by then on court with a live Sofascore event on it), so
# the Sofascore half of the same document supplied the match instead — where
# she is "Yexin Ma". `_pairing_key` hashes `_norm`, which spaces the hyphen,
# so the two spellings were two identities: the day stored the match TWICE,
# and the real row, unstamped by the newest document, was reported as a slot
# the sheet had pulled (`slot_pulled_not_retired`).
#
# `_dedupe_day` is the designed net for a row "stored under a key no future
# revision will produce" — but its relations read `_name_tokens`, which split
# the hyphen too, so {ye, xin, ma} and {yexin, ma} were two different people
# and there was nothing to collapse. The net is what this restores; the key
# is deliberately left alone, since neither spelling is canonical.

from datetime import datetime, timezone  # noqa: E402

from app.models.schedule import ScheduleEntry, ScheduleEntryPlayer  # noqa: E402
from app.services.schedule import (_dedupe_day, _name_tokens,  # noqa: E402
                                   _pairing_key, _same_pairing)

KOREA_DAY = date(2026, 9, 20)


def test_a_printed_name_is_filed_under_both_spellings():
    assert _name_tokens("[5] Ye-Xin MA CHN") == {"ye", "xin", "ma", "yexin"}
    assert _name_tokens("Yexin Ma") == {"yexin", "ma"}
    # Nothing else moves: a name without a hyphen has one spelling, and an
    # initial still carries no name.
    assert _name_tokens("[WC] Eunhye LEE KOR") == {"eunhye", "lee"}
    assert _name_tokens("Y. Ma") == {"ma"}


class _Slot:
    """A stored row as the dedupe relations read it."""

    def __init__(self, a, b, is_tbd=False, tbd_side=None):
        self.is_tbd, self.tbd_side = is_tbd, tbd_side
        self.players = [
            type("P", (), {"side": s, "position": i, "raw_name": n})()
            for s, names in (("a", a), ("b", b))
            for i, n in enumerate(names, 1)]


def test_two_sources_spelling_one_player_differently_are_one_match():
    wta = _Slot(["[WC] Eunhye LEE KOR"], ["[5] Ye-Xin MA CHN"])
    sofa = _Slot(["Eunhye Lee"], ["Yexin Ma"])
    assert _same_pairing(wta, sofa) and _same_pairing(sofa, wta)


def test_a_western_double_barrel_still_agrees_with_its_spaced_form():
    """The joined spelling is ADDED, not substituted: a source that spaces
    "Auger-Aliassime" must keep meeting the one that hyphenates it."""
    hyphen = _Slot(["[2] Felix AUGER-ALIASSIME CAN"], ["Jan-Lennard STRUFF GER"])
    spaced = _Slot(["Felix Auger Aliassime"], ["Jan Lennard Struff"])
    assert _same_pairing(hyphen, spaced)


def test_different_matches_are_still_different():
    assert not _same_pairing(_Slot(["Eunhye Lee"], ["Yexin Ma"]),
                             _Slot(["Eunhye Lee"], ["Xinxin Yao"]))
    assert not _same_pairing(_Slot(["Miho Kuramochi"], ["Xinxin Yao"]),
                             _Slot(["Eunhye Lee"], ["Yexin Ma"]))


def _slot_row(db, *, key, court_order, doc, a, b, live=False):
    e = ScheduleEntry(
        tournament_id=1, play_date=KOREA_DAY, tour="WTA", stage="qualifying",
        discipline="singles", round_label="Q2", court="GRANDSTAND",
        court_order=court_order, pairing_key=key, is_tbd=False,
        last_document_id=doc,
        first_seen_at=datetime(2026, 9, 19, 9, 44, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc))
    if live:
        e.sofa_event_id = 17136067
        e.live_scores_json = [["1"], ["0"], 2, [None]]
        e.started_at = datetime(2026, 9, 20, 2, 10, tzinfo=timezone.utc)
    db.add(e)
    for side, names in (("a", a), ("b", b)):
        for i, n in enumerate(names, 1):
            db.add(ScheduleEntryPlayer(entry=e, side=side, position=i, raw_name=n))
    return e


def test_the_day_stops_carrying_the_same_match_twice():
    """The incident, end to end: the two rows Korea's Sunday held at 02:04,
    and the pass that has to collapse them. The live row survives — and would
    have inherited the Sofascore event had the phantom been the one holding
    it, which is what `_absorb` is for."""
    sheet = ["[WC] Eunhye LEE KOR"], ["[5] Ye-Xin MA CHN"]
    feed = ["Eunhye Lee"], ["Yexin Ma"]
    # The two identities really are different — the dedupe pass, not the key,
    # is what closes this.
    assert (_pairing_key(1, KOREA_DAY, "singles", *sheet, [None, None])
            != _pairing_key(1, KOREA_DAY, "singles", *feed, [None, None]))

    async def go():
        engine, Session = await _db()
        async with Session() as db:
            live = _slot_row(db, key="sheet", court_order=1, doc=363,
                             a=sheet[0], b=sheet[1], live=True)
            _slot_row(db, key="feed", court_order=3, doc=362,
                      a=feed[0], b=feed[1])
            await db.commit()
            dropped = await _dedupe_day(db, 1, KOREA_DAY)
            await db.commit()
            rows = (await db.execute(ScheduleEntry.__table__.select())).fetchall()
            left = (await db.execute(
                ScheduleEntryPlayer.__table__.select())).fetchall()
        await engine.dispose()
        return dropped, rows, left, live.id

    dropped, rows, left, live_id = asyncio.run(go())
    assert dropped == 1
    assert [r.id for r in rows] == [live_id]
    assert rows[0].sofa_event_id == 17136067 and rows[0].started_at is not None
    # The phantom's players go with it — a row deleted by the relationship
    # cascade, not orphaned behind the page.
    assert {p.schedule_entry_id for p in left} == {live_id}


# ------------------------------------------------------------- AND THE LAW
#
# THE RATCHET (schedule_invariants' header): the check for the class goes in
# with the fix. `pairing_duplicated` is the law that should have named Korea's
# duplicate and did not — it compared raw printed STRINGS lowercased, so it
# could only see a slot both sources spelled identically, and the duplicate
# that matters is the one they spelled differently. What reached the owner was
# the downstream symptom (`slot_pulled_not_retired`, the live row left
# unstamped by the newest document) rather than the fault.

from app.models.tournament import Tournament as _T  # noqa: E402
from app.services.schedule_invariants import (_person_words,  # noqa: E402
                                              _sides_agree, check_day)


def test_the_law_reads_a_name_as_a_person():
    assert _person_words("[5] Ye-Xin MA CHN") == {"ye", "xin", "ma", "yexin"}
    assert _person_words("Yexin Ma") == {"yexin", "ma"}
    # The furniture comes off; an initial is not a name; a team names two.
    assert _person_words("[WC] Eunhye LEE KOR") == {"eunhye", "lee"}
    assert _person_words("O. Luz") == {"luz"}
    assert _person_words("S. Aoyama / E. Liang") == {"aoyama", "liang"}


def test_sides_agree_on_equality_and_containment_only():
    assert _sides_agree({"lee"}, {"lee"})
    assert _sides_agree({"cabral"}, {"cabral", "tracy"})
    assert not _sides_agree({"lee"}, {"yao"})
    assert not _sides_agree(set(), set())


async def _korea_sunday(db, *, doubles=False):
    db.add(_T(id=1, name="Korea Open", year=2026))
    await db.flush()
    _slot_row(db, key="sheet", court_order=1, doc=363,
              a=["[WC] Eunhye LEE KOR"], b=["[5] Ye-Xin MA CHN"], live=True)
    second = _slot_row(db, key="feed", court_order=3, doc=362,
                       a=["Eunhye Lee"], b=["Yexin Ma"])
    if doubles:
        second.discipline = "doubles"
        second.round_label = "R16"
        for p in second.players:
            p.raw_name = {"Eunhye Lee": "Eunhye Lee / Sohyun Park",
                          "Yexin Ma": "Yexin Ma / Xinxin Yao"}[p.raw_name]
    await db.commit()


def _codes(violations, code):
    return [v for v in violations if v["code"] == code]


def test_the_law_names_the_duplicate_the_two_spellings_made():
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            await _korea_sunday(db)
            out = await check_day(db, 1, KOREA_DAY)
        await engine.dispose()
        return out
    dupes = _codes(asyncio.run(go()), "pairing_duplicated")
    assert len(dupes) == 1 and "same players as entry" in dupes[0]["detail"]


def test_a_doubles_slot_is_not_its_players_singles_slot():
    """The guard that keeps the containment test honest: a player in the
    singles and in the doubles on one day puts her singles side inside her
    doubles side, and those are two matches."""
    async def go():
        engine, Session = await _db()
        async with Session() as db:
            await _korea_sunday(db, doubles=True)
            out = await check_day(db, 1, KOREA_DAY)
        await engine.dispose()
        return out
    assert _codes(asyncio.run(go()), "pairing_duplicated") == []


def test_a_hyphen_on_tennis_explorers_side_matches_the_joined_sheet_name():
    # TE lists "Xu Yi-Fan"; the sheet prints "Yifan XU". The Tang/Xu doubles
    # pair went unranked because the index only held "xu yi fan" (2026-09-24).
    from types import SimpleNamespace as NS
    from app.services.rankings import _build_te_index, _match_token_set, _norm
    ps = [NS(id=4400, name_raw="Xu Yi-Fan", name_norm=_norm("Xu Yi-Fan"), te_slug="xu-f5123")]
    idx, _, _ = _build_te_index(ps)
    assert _match_token_set("Yifan XU", idx) == 4400
    assert _match_token_set("Yi-Fan XU", idx) == 4400
