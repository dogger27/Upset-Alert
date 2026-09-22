"""A qualifying row's seed, and its place in the field.

Two faults, one cause. The schedule moved to the feeds (2026-09-18), and a
Sofascore row states its seeding in a FIELD — `homeTeamSeed: '2'` — where a
PDF sheet prints it into the name, "[2] Alexandre MULLER FRA". Main-draw rows
never noticed: they resolve to a `draw_entries` row that carries the seeding
anyway. Qualifying has no such row, so the day the feeds took over, every
qualifying seed on the order of play disappeared (owner, 2026-09-23).

The same absence is why a qualifying name wore no grey badge either: the
inferred seed is read off the draw, and the qualifying draw is not in
`draw_entries` at all.
"""
import json

from app.services.qualifying_rank import qualifying_places
from app.services.sofa_schedule import parse_sofa_day


def _event(home, away, home_seed=None, away_seed=None, rnd="Qualification Round 1"):
    return {"id": abs(hash((home, away))) % 100000,
            "startTimestamp": 1758600000,
            "roundInfo": {"name": rnd},
            "venue": {"name": "Court 1"},
            "homeTeam": {"name": home}, "awayTeam": {"name": away},
            "homeTeamSeed": home_seed, "awayTeamSeed": away_seed}


# ── The feed's mark reaches the parsed row ────────────────────────────────

def test_the_feed_states_a_seed_and_the_parser_carries_it():
    doc = json.dumps([_event("Muller A.", "Pavlovic L.", "2", None)]).encode()
    (m,), _meta = parse_sofa_day(doc)
    assert m.seeds_a == ["2"], "the seeded side keeps its number"
    assert m.seeds_b == [None], "and the unseeded side is given no mark at all"


def test_a_wildcard_is_a_mark_like_any_other():
    """'WC' arrives in the same field as '1'. Splitting the number from the
    code is one reader's job, downstream, so both are carried unchanged."""
    doc = json.dumps([_event("Mochizuki S.", "Xiao L.", "1", "WC")]).encode()
    (m,), _meta = parse_sofa_day(doc)
    assert (m.seeds_a, m.seeds_b) == (["1"], ["WC"])


def test_an_empty_mark_is_no_mark():
    """An empty string would later read as "this source says: no seed", which
    is a different claim from "this source did not say"."""
    doc = json.dumps([_event("A B.", "C D.", "", "  ")]).encode()
    (m,), _meta = parse_sofa_day(doc)
    assert (m.seeds_a, m.seeds_b) == ([None], [None])


def test_both_halves_of_a_pair_carry_the_pair_s_seed():
    """Sofascore states one seed per TEAM, and a doubles seeding belongs to
    the pair — as a printed "[1] KRAJICEK / MEKTIC" says too."""
    doc = json.dumps([_event("Krajicek A. / Mektic N.", "Arends S. / Pel M.", "1")]).encode()
    (m,), _meta = parse_sofa_day(doc, discipline="doubles")
    assert m.seeds_a == ["1", "1"]
    assert m.seeds_b == [None, None]


# ── The field's order ─────────────────────────────────────────────────────

def test_the_seeds_lead_the_field_in_seed_order():
    places = qualifying_places({"a": (1, 60), "b": (2, 99), "c": (None, 70)})
    assert places["a"] == 1 and places["b"] == 2


def test_the_unseeded_follow_the_seeds_rather_than_the_rankings():
    """The best unseeded player in a field with two seeds is third, even
    where their ranking beats the second seed's."""
    places = qualifying_places({"seed1": (1, 60), "seed2": (2, 250),
                                "good": (None, 80), "worse": (None, 300)})
    assert places["good"] == 3
    assert places["worse"] == 4


def test_an_unranked_player_sorts_last_not_first():
    """None is not a good ranking — it is no ranking held."""
    places = qualifying_places({"ranked": (None, 400), "unknown": (None, None)})
    assert places["ranked"] == 1
    assert places["unknown"] == 2


def test_the_same_field_always_numbers_the_same_way():
    """Two players on the same ranking, or two with none, break on the key —
    so a page polled every ten seconds does not shuffle its badges."""
    field = {"zz": (None, None), "aa": (None, None), "mm": (None, 90), "nn": (None, 90)}
    assert qualifying_places(field) == {"mm": 1, "nn": 2, "aa": 3, "zz": 4}


def test_a_field_of_nobody_is_no_places():
    assert qualifying_places({}) == {}


# ── The row the client is served ──────────────────────────────────────────

def _player(raw_name, seed_mark=None):
    from types import SimpleNamespace
    return SimpleNamespace(side="a", position=1, raw_name=raw_name,
                           draw_entry_id=None, nationality=None, seed_mark=seed_mark)


def test_a_stored_mark_becomes_a_seed_on_a_name_that_carries_none():
    from app.routers.schedule import _player_out
    out = _player_out(_player("Alexandre Muller", "2"), {}, {}, {}, {}, False)
    assert out.seed == 2
    assert out.entry_type is None


def test_a_stored_code_is_an_entry_type_and_not_a_seed():
    from app.routers.schedule import _player_out
    out = _player_out(_player("Linang Xiao", "WC"), {}, {}, {}, {}, False)
    assert out.seed is None
    assert out.entry_type == "WC"


def test_the_printed_name_still_wins_where_it_says_anything():
    """A sheet reclaiming a day prints the mark itself; the stored one is the
    answer for the passes where nothing printed it."""
    from app.routers.schedule import _player_out
    out = _player_out(_player("[5] Alexandre MULLER FRA", "2"), {}, {}, {}, {}, False)
    assert out.seed == 5


def test_no_mark_anywhere_is_no_seed():
    from app.routers.schedule import _player_out
    out = _player_out(_player("Alexandre Muller"), {}, {}, {}, {}, False)
    assert out.seed is None and out.entry_type is None


def test_the_qualifying_place_reaches_the_row_the_bracket_cannot_describe():
    from app.routers.schedule import _player_out
    out = _player_out(_player("Alexandre Muller"), {}, {}, {}, {}, False, qual_rank=9)
    assert out.draw_rank == 9


def test_a_seed_is_a_change_the_fingerprint_can_see():
    """A day already read must be reachable by a mark the feed states later,
    or by a parser that can suddenly see one — the same trap the byte check
    exempts feeds from. The fingerprint is what decides, so it holds seeds."""
    import hashlib
    from app.services.oop_parser import Match

    def fp(matches):
        return hashlib.sha256(repr([
            (m.court, m.time, m.start_raw, m.tour, m.round, m.discipline,
             m.tbd, m.tbd_side, tuple(m.side_a), tuple(m.side_b),
             tuple(getattr(m, 'seeds_a', ()) or ()), tuple(getattr(m, 'seeds_b', ()) or ()))
            for m in matches]).encode()).hexdigest()

    bare = Match(court="Court 1", side_a=["Muller A."], side_b=["Pavlovic L."])
    seeded = Match(court="Court 1", side_a=["Muller A."], side_b=["Pavlovic L."],
                   seeds_a=["2"], seeds_b=[None])
    assert fp([bare]) != fp([seeded])


def test_a_field_of_sixteen_numbers_one_to_sixteen_however_few_seeds_are_known():
    """Hangzhou 2026-09-22 arrived with one of its sixteen marked — the [7].
    Numbering the unseeded on from the highest KNOWN seed put fifteen players
    into places 8 to 22 in a field of sixteen, which is a badge that cannot be
    true."""
    field = {f"p{i}": (None, 300 + i) for i in range(15)}
    field["seeded"] = (7, 120)
    places = qualifying_places(field)
    assert places["seeded"] == 1, "the only seed known leads the field"
    assert sorted(places.values()) == list(range(1, 17))


def test_a_full_set_of_seeds_numbers_exactly_as_a_bracket_does():
    """Where every seed is known the two rules agree: eight seeds take 1-8 and
    the rest follow at 9."""
    field = {f"s{i}": (i, 50 + i) for i in range(1, 9)}
    field.update({f"u{i}": (None, 200 + i) for i in range(8)})
    places = qualifying_places(field)
    assert [places[f"s{i}"] for i in range(1, 9)] == list(range(1, 9))
    assert places["u0"] == 9 and places["u7"] == 16


def test_the_field_s_seed_dresses_a_row_the_source_did_not_mark():
    """A seeding belongs to the player in the draw, not to the day. The feed
    marked Bernard Tomić as Hangzhou's [3] on his second-round row and not on
    his first, and the same player in the same field cannot be seeded on
    Tuesday and unseeded on Monday."""
    from app.routers.schedule import _player_out
    out = _player_out(_player("Bernard Tomić"), {}, {}, {}, {}, False,
                      qual_rank=3, qual_seed=3)
    assert out.seed == 3


def test_the_row_s_own_mark_still_leads_the_field_s():
    from app.routers.schedule import _player_out
    out = _player_out(_player("Bernard Tomić", "5"), {}, {}, {}, {}, False,
                      qual_rank=3, qual_seed=3)
    assert out.seed == 5
