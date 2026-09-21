"""Two draw-shape sources that are not Wikipedia, measured against it.

Both fixtures are real pages captured 2026-09-21: the WTA's official draw JSON
for Guadalajara (event 2075 = production draw 142) and Tennis Explorer's draw
pages for Hangzhou and Chengdu (draws 122 and 145), two days before play. The
expected values are what production held for those draws, built from
Wikipedia — so every assertion is a statement of agreement between sources.
"""
import json
from pathlib import Path

import pytest

from app.services import te_draw, wta_draw
from app.services.sofa_draw_shape import bracket_is_complete, shape_to_parsed

FIX = Path(__file__).parent / "fixtures"
WIKI_POSITIONS = [1, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19,
                  20, 21, 22, 23, 25, 26, 27, 28, 29, 30, 31]
WIKI_BYES = [2, 10, 24, 32]


# ── the WTA's official sheet ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def wta_doc():
    raw = json.loads((FIX / "wta_draw_guadalajara_2026.json").read_text(encoding="utf-8"))
    return json.loads(raw["drawInfo"][0])


@pytest.fixture(scope="module")
def wta_shape(wta_doc):
    return wta_draw.parse_draw(wta_doc)


def test_wta_every_slot_is_present_and_the_byes_are_explicit(wta_shape):
    assert wta_shape.bracket_size == 32 and wta_shape.num_rounds == 5
    assert wta_shape.entrant_count == 28
    assert bracket_is_complete(wta_shape)


def test_wta_byes_normalise_to_the_convention_every_draw_uses(wta_shape):
    """The sheet prints the bye ABOVE the seed in the bottom half (Bye at 23,
    Bejlek at 24); Wikipedia and Sofascore both put the player on the odd
    slot. Same pairs, same players — normalised so a later Wikipedia pass does
    not find every bottom-half seed one slot away from where it left it."""
    assert wta_shape.byes == WIKI_BYES
    assert [e.bracket_position for e in wta_shape.entrants] == WIKI_POSITIONS


def test_wta_seeds_entry_types_nationality_and_rank(wta_shape):
    assert sorted(e.seed for e in wta_shape.entrants if e.seed) == list(range(1, 9))
    assert sorted({e.entry_type for e in wta_shape.entrants if e.entry_type}) == ["Alt", "Q", "WC"]
    assert all(e.nationality for e in wta_shape.entrants)
    assert sum(1 for e in wta_shape.entrants if e.ranking) >= 24


def test_wta_the_top_seed_and_a_seed_from_the_mirrored_half(wta_shape):
    by = {e.bracket_position: e for e in wta_shape.entrants}
    assert by[1].name == "Marta Kostyuk" and by[1].seed == 1 and by[1].nationality == "UKR"
    assert by[23].seed == 3 and "Bejlek" in by[23].name       # printed at 24 on the sheet
    assert by[31].seed == 2 and "Jovic" in by[31].name


def test_wta_a_qualifier_placeholder_is_a_blank_q_entry():
    """Before qualifying is done the sheet holds the slot with player id 0;
    represented the way Wikipedia's blank Q is, so the writer counts it."""
    doc = {"Draws": {"Events": {"Event": [{"EventTypeCode": "LS", "DrawSize": 4, "Draw": {"DrawLine": [
        {"Pos": 1, "DisplayLine": "A Player", "Seed": "1", "EntryType": "", "Rank": 10,
         "Players": {"Player": {"id": 5, "FirstName": "A", "SurName": "Player", "Country": "XXX"}}},
        {"Pos": 2, "DisplayLine": "Qualifier", "Seed": "", "EntryType": "Q", "Rank": "",
         "Players": {"Player": {"id": 0, "FirstName": "", "SurName": "", "Country": ""}}},
        {"Pos": 3, "DisplayLine": "Bye", "Seed": "", "EntryType": "", "Rank": "",
         "Players": {"Player": {"id": 0, "FirstName": "Bye", "SurName": "Bye", "Country": ""}}},
        {"Pos": 4, "DisplayLine": "B Player", "Seed": "2", "EntryType": "WC", "Rank": 40,
         "Players": {"Player": {"id": 6, "FirstName": "B", "SurName": "Player", "Country": "YYY"}}},
    ]}}]}}}
    s = wta_draw.parse_draw(doc)
    q = next(e for e in s.entrants if e.bracket_position == 2)
    assert q.name == "" and q.entry_type == "Q"
    assert s.byes == [4]                                # bye printed at 3 -> player to 3, bye to 4
    assert next(e for e in s.entrants if e.seed == 2).bracket_position == 3
    assert bracket_is_complete(s)


def test_wta_qualifying_and_doubles_events_are_never_the_draw():
    doc = {"Draws": {"Events": {"Event": [
        {"EventTypeCode": "RS", "Draw": {"DrawLine": [{"Pos": 1, "DisplayLine": "X"}]}},
        {"EventTypeCode": "LD", "Draw": {"DrawLine": [{"Pos": 1, "DisplayLine": "Y"}]}},
    ]}}}
    assert wta_draw.parse_draw(doc) is None


def test_wta_an_unpublished_draw_is_none_not_an_error():
    assert wta_draw.parse_draw({}) is None
    assert wta_draw.singles_event({"Draws": {}}) is None


def test_wta_rides_the_same_adapter_into_the_writer(wta_shape):
    parsed = shape_to_parsed(wta_shape)
    assert len(parsed.players) == 28 and len(parsed.matches) == 31
    assert sum(1 for m in parsed.matches if m.is_bye) == 4
    assert all(p.nationality for p in parsed.players)


# ── Tennis Explorer ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def hangzhou():
    return te_draw.parse_bracket((FIX / "te_hangzhou_2026.html").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def chengdu():
    return te_draw.parse_bracket((FIX / "te_chengdu_2026.html").read_text(encoding="utf-8"))


def test_te_reads_the_whole_field_two_days_out(hangzhou):
    """28 in a 32 bracket, including the four Sofascore could not see."""
    assert hangzhou.bracket_size == 32 and hangzhou.num_rounds == 5
    assert hangzhou.entrant_count == 28
    assert bracket_is_complete(hangzhou)
    names = {e.name for e in hangzhou.entrants}
    for hidden in ("Marozsan", "Safiullin", "Sweeny", "Hijikata"):
        assert hidden in names, hidden


def test_te_byes_and_qualifier_slots_match_the_wikipedia_draft(hangzhou):
    assert hangzhou.byes == WIKI_BYES
    blanks = sorted(e.bracket_position for e in hangzhou.entrants if not e.name)
    assert blanks == [11, 18, 20, 30]
    assert all(e.entry_type == "Q" for e in hangzhou.entrants if not e.name)


def test_te_seeds_when_printed_land_on_the_normalised_slot(hangzhou):
    by = {e.bracket_position: e for e in hangzhou.entrants}
    assert by[1].seed == 1 and by[1].name == "Medvedev"
    assert by[23].seed == 3 and by[23].name == "Etcheverry"     # printed at 24
    assert by[31].seed == 2 and by[31].name == "Rublev"
    assert sorted(e.seed for e in hangzhou.entrants if e.seed) == list(range(1, 9))


def test_te_slugs_are_the_identity(hangzhou):
    slugs = {e.te_slug for e in hangzhou.entrants if e.te_slug}
    assert len(slugs) == 24
    assert "medvedev-e0d2d" in slugs and "marozsan" in slugs


def test_te_seeds_are_optional_not_required(chengdu):
    """Chengdu had no seed marks on the same afternoon Hangzhou had all eight.
    The bracket is still complete and still usable; seeds fill from elsewhere."""
    assert chengdu.entrant_count == 28 and bracket_is_complete(chengdu)
    assert not any(e.seed for e in chengdu.entrants)
    assert chengdu.byes == WIKI_BYES


def test_te_a_page_off_the_grid_yields_nothing_not_a_half_bracket():
    assert te_draw.parse_bracket("<html>no bracket here</html>") is None
    off_grid = "".join(
        f'<div style="position:absolute; left:10px; top:{20 + i * 25}px; "><a href="/player/p{i}/">P{i}</a></div>'
        for i in range(8))
    assert te_draw.parse_bracket(off_grid) is None
    not_pow2 = "".join(
        f'<div style="position:absolute; left:10px; top:{20 + i * 24}px; "><a href="/player/p{i}/">P{i}</a></div>'
        for i in range(6))
    assert te_draw.parse_bracket(not_pow2) is None


def test_te_two_byes_in_one_pair_is_refused():
    page = "".join(
        f'<div style="position:absolute; left:10px; top:{20 + i * 24}px; ">{"bye" if i < 2 else "<a href=/player/p/>P</a>"}</div>'
        for i in range(4))
    assert te_draw.parse_bracket(page) is None


# ── finding the page ──────────────────────────────────────────────────────

INDEX = '''
<tr class="one"><td class="t-name"><span class="type-men2">&nbsp;</span><a href="/hangzhou/2026/atp-men/">Hangzhou</a></td></tr>
<tr class="two"><td class="t-name"><span class="type-men2">&nbsp;</span><a href="/chengdu/2026/atp-men/">Chengdu</a></td></tr>
<tr class="one"><td class="t-name"><span class="type-women2">&nbsp;</span><a href="/seoul-wta/2026/wta-women/">Seoul WTA</a></td></tr>
<tr class="two"><td class="t-name"><span class="type-women2">&nbsp;</span><a href="/sao-paulo-wta/2026/wta-women/">Sao Paulo WTA</a></td></tr>
<tr class="one"><td class="t-name"><span class="type-men2">&nbsp;</span><a href="/genoa-2-challenger/2026/atp-men/">Genoa 2 challenger</a></td></tr>
<tr class="two"><td class="t-name"><span class="type-men2">&nbsp;</span><a href="/hangzhou/2025/atp-men/">Hangzhou</a></td></tr>
<tr class="one"><td class="t-name"><a href="/tokyo/2026/atp-men/"><span class="fl fl-jp">&nbsp;</span>Tokyo</a></td></tr>
'''


def test_te_reads_the_front_pages_row_form_too():
    """The front page puts the flag span INSIDE the anchor; the index on a draw
    page puts a type span before it. The first regex read only the second and
    parsed zero rows from the real front page, so the Hangzhou rebuild
    declined. Both forms, and a row printed twice, must read as one each."""
    rows = te_draw.index_tournaments(INDEX + INDEX)
    by = {r["path"]: r for r in rows}
    assert by["/tokyo/2026/atp-men/"]["name"] == "Tokyo"
    assert by["/hangzhou/2026/atp-men/"]["name"] == "Hangzhou"
    assert len(rows) == len(by)



def test_te_index_rows_are_read_with_tour_and_year():
    rows = te_draw.index_tournaments(INDEX)
    assert ("Hangzhou", "/hangzhou/2026/atp-men/", 2026, "M") in [
        (r["name"], r["path"], r["year"], r["tour"]) for r in rows]
    assert any(r["tour"] == "F" and r["name"] == "Seoul WTA" for r in rows)


def test_te_matches_by_city_first_then_name():
    rows = te_draw.index_tournaments(INDEX)
    assert te_draw.match_tournament(rows, name="Hangzhou Open", city="Hangzhou",
                                    gender="M", year=2026) == "/hangzhou/2026/atp-men/"
    assert te_draw.match_tournament(rows, name="Korea Open", city="Seoul",
                                    gender="F", year=2026) == "/seoul-wta/2026/wta-women/"
    assert te_draw.match_tournament(rows, name="SP Open", city="São Paulo",
                                    gender="F", year=2026) == "/sao-paulo-wta/2026/wta-women/"


def test_te_never_crosses_tour_year_or_level():
    rows = te_draw.index_tournaments(INDEX)
    assert te_draw.match_tournament(rows, name="Hangzhou Open", city="Hangzhou", gender="F", year=2026) is None
    assert te_draw.match_tournament(rows, name="Hangzhou Open", city="Hangzhou", gender="M", year=2024) is None
    assert te_draw.match_tournament(rows, name="Genoa Open", city="Genoa", gender="M", year=2026) is None


def test_te_two_candidates_is_no_candidate():
    rows = te_draw.index_tournaments(INDEX + INDEX.replace("/hangzhou/2026/", "/hangzhou-2/2026/"))
    assert te_draw.match_tournament(rows, name="Hangzhou Open", city="Hangzhou", gender="M", year=2026) is None


def test_the_real_index_page_lists_the_two_that_started_all_this():
    """The index embedded in a draw page captured the same afternoon."""
    page = (FIX / "te_hangzhou_2026.html").read_text(encoding="utf-8")
    rows = te_draw.index_tournaments(page)
    paths = {r["path"] for r in rows}
    assert "/hangzhou/2026/atp-men/" in paths and "/chengdu/2026/atp-men/" in paths


# ── the country map the TE path leans on ─────────────────────────────────

def test_country_map_covers_the_tennis_nations_and_only_ioc_codes():
    """Derived from our own data, not typed. A TE-built draw carries no codes,
    so this is what turns 'France' into FRA for the flag."""
    from app.services.rankings import COUNTRY_TO_IOC
    for name, code in {"france": "FRA", "australia": "AUS", "czech republic": "CZE",
                       "great britain": "GBR", "chinese taipei": "TPE", "usa": "USA",
                       "russia": "RUS", "hungary": "HUN", "china": "CHN", "japan": "JPN"}.items():
        assert COUNTRY_TO_IOC.get(name) == code, name
    assert all(len(v) == 3 and v.isupper() for v in COUNTRY_TO_IOC.values())
    assert all(k == k.lower().strip() for k in COUNTRY_TO_IOC)
    assert len(COUNTRY_TO_IOC) >= 60
