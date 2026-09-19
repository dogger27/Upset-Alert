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
