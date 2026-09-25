"""The ATP's own draw sheet (protennislive mds.pdf), read from two real 2026
sheets: Chengdu and Hangzhou, released 25 September."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import atp_pdf_draw as A  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def _slots(name):
    pdf = (FIX / name).read_bytes()
    return pdf, A.parse_slots(pdf)


def test_every_position_seed_entry_and_country():
    _, s = _slots("atp_mds_chengdu_2026.pdf")
    assert len(s) == 32
    by = {x["pos"]: x for x in s}
    assert (by[1]["surname"], by[1]["seed"], by[1]["country"]) == ("VACHEROT", 1, "MON")
    assert by[3]["entry"] == "Q" and by[11]["entry"] == "WC" and by[25]["entry"] == "LL"
    assert by[27]["entry"] == "NG"                       # Kouamé's Next Gen entry
    assert by[29]["given"] == "Juan Manuel"


def test_byes_follow_the_odd_slot_convention():
    # The sheet prints Bye 23 / van de Zandschulp 24; every reader here puts
    # the player on the odd slot.
    _, s = _slots("atp_mds_chengdu_2026.pdf")
    by = {x["pos"]: x for x in s}
    assert by[2]["bye"] and by[10]["bye"] and by[24]["bye"] and by[32]["bye"]
    assert by[23]["surname"] == "VAN DE ZANDSCHULP" and by[23]["seed"] == 4
    assert by[31]["surname"] == "DAVIDOVICH FOKINA"


def test_a_cut_name_is_flagged_and_resolved_never_left_with_an_ellipsis():
    pdf, s = _slots("atp_mds_hangzhou_2026.pdf")
    cut = [x for x in s if x["cut"]]
    assert [x["surname"] for x in cut] == ["ETCHEVERRY"]
    stats = A.resolve_names(s, held={}, te_players=[], seeded=A.seeded_table(pdf), country_to_ioc={})
    by = {x["pos"]: x for x in s}
    assert by[23]["name"] == "Tomas Martin Etcheverry"   # from the Seeded Players table
    assert stats["by_seed_table"] == 1
    assert all("…" not in (x.get("name") or "") for x in s)


def test_cut_name_resolved_from_the_slot_we_hold_and_from_tennis_explorer():
    _, s = _slots("atp_mds_chengdu_2026.pdf")
    te = [NS(name_display="Alejandro Davidovich Fokina", first_name="Alejandro",
             last_name="Davidovich Fokina", nationality="Spain")]
    A.resolve_names(s, held={23: "Botic van de Zandschulp"}, te_players=te, seeded={},
                    country_to_ioc={"spain": "ESP"})
    by = {x["pos"]: x for x in s}
    assert by[23]["name"] == "Botic van de Zandschulp"
    assert by[31]["name"] == "Alejandro Davidovich Fokina"


def test_our_spelling_is_kept_for_the_same_person():
    _, s = _slots("atp_mds_chengdu_2026.pdf")
    A.resolve_names(s, held={7: "Alexander Shevchenko"}, te_players=[], seeded={}, country_to_ioc={})
    assert {x["pos"]: x for x in s}[7]["name"] == "Alexander Shevchenko"


def test_neutral_athletes_carry_no_country():
    _, s = _slots("atp_mds_hangzhou_2026.pdf")
    by = {x["pos"]: x for x in s}
    assert by[1]["surname"] == "MEDVEDEV" and by[1]["country"] is None


def test_the_shape_is_complete():
    from app.services.sofa_draw_shape import bracket_is_complete
    pdf, s = _slots("atp_mds_hangzhou_2026.pdf")
    A.resolve_names(s, held={}, te_players=[], seeded=A.seeded_table(pdf), country_to_ioc={})
    shape = A.to_shape(s)
    assert shape.bracket_size == 32 and shape.num_rounds == 5 and len(shape.byes) == 4
    assert bracket_is_complete(shape)


def test_a_two_page_draw_under_its_watermark():
    # Miami: 96 players in a 128 bracket over two pages, a sideways
    # "Prize Money" watermark through the name column, and three-digit
    # positions that run into their entry mark ("108Q").
    pdf, s = _slots("atp_mds_miami_2026.pdf")
    assert len(s) == 128 and sum(x["bye"] for x in s) == 32
    by = {x["pos"]: x for x in s}
    assert by[7]["surname"] == "KORDA" and by[7]["seed"] == 32     # was "K O RDA"
    assert by[108]["entry"] == "Q" and by[108]["surname"] == "BARRIOS VERA"


def test_a_transliteration_is_the_same_person():
    assert A._same_person("Max Schönhaus", "SCHOENHAUS", "Max")
    assert A._same_person("Elmer Møller", "MOLLER", "Elmer")
    assert A._same_person("Kwon Soon-woo", "KWON", "Soonwoo")
    assert not A._same_person("Martin Damm", "NAKASHIMA", "Brandon")


def test_a_challenge_is_info_and_its_stand_down_survives_a_restart(tmp_path, monkeypatch):
    """A 429 from protennislive is an expected state: logged at info, and the
    six-hour stand-down is on disk, so a restarted process asks nobody."""
    import asyncio
    import httpx
    from app.services import system_log

    calls, logged = [], []

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url):
            calls.append(url)
            return NS(status_code=429, content=b"<html>challenge</html>")

    async def fake_log(level, *a, **k):
        logged.append(level)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(system_log, "app_log", fake_log)
    monkeypatch.setattr(A, "_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(A, "_blocked_until", 0.0)

    assert asyncio.run(A.fetch_pdf(329, 2026)) is None
    assert logged == ["info"] and len(calls) == 1
    assert (tmp_path / A._BLOCK_FILE).exists()

    # A restart: the in-memory stand-down is gone, the marker is not.
    monkeypatch.setattr(A, "_blocked_until", 0.0)
    assert asyncio.run(A.fetch_pdf(330, 2026)) is None
    assert len(calls) == 1 and logged == ["info"]
