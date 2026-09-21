"""Sofascore's cup tree, measured against the draw Wikipedia gave us.

The fixture is a real /cuptrees response for 2026 Guadalajara (uid 16559,
season 85638), captured 2026-09-21 and trimmed to the shape fields. Draw 142
in production is the same event: a 28-entrant field in a 32 bracket, whose
Wikipedia-derived bracket positions and byes are the ground truth asserted
below. Every expected value here was read off production, not invented.

This is the evidence for demoting Wikipedia from sole author of draw shape,
so the assertions are deliberately specific: if Sofascore changes the payload,
these fail with the field that moved.
"""
import json
from pathlib import Path

import pytest

from app.services.sofa_draw_shape import (
    _split_seed,
    compare_to_entries,
    disagreement_summary,
    draw_shape,
    main_tree,
)

FIXTURE = Path(__file__).parent / "fixtures" / "cuptree_guadalajara_2026.json"

# Ground truth, read off production draw 142 on 2026-09-21.
WIKI_POSITIONS = [1, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19,
                  20, 21, 22, 23, 25, 26, 27, 28, 29, 30, 31]
WIKI_BYES = [2, 10, 24, 32]


@pytest.fixture(scope="module")
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def shape(payload):
    return draw_shape(payload)


# ── the tree ──────────────────────────────────────────────────────────────

def test_the_main_tree_is_chosen_by_name_not_position(payload):
    """The qualifying tree is not reliably second, and reading one as a main
    draw would produce a plausible, wrong bracket."""
    assert "Qualifying" not in main_tree(payload)["name"]
    assert main_tree(payload)["name"] == "2026 Guadalajara, Mexico"


def test_a_payload_with_no_main_tree_is_none():
    assert draw_shape({"cupTrees": []}) is None
    assert draw_shape({}) is None
    assert draw_shape({"cupTrees": [{"name": "X Qualifying", "rounds": []}]}) is None


# ── geometry ──────────────────────────────────────────────────────────────

def test_the_bracket_size_and_round_count(shape):
    assert shape.bracket_size == 32          # 16 round-1 blocks
    assert shape.num_rounds == 5


def test_the_entrant_count_is_the_field_not_the_bracket(shape):
    assert shape.entrant_count == 28


# ── the two fields Wikipedia was sole author of ───────────────────────────

def test_every_bracket_position_matches_wikipedia(shape):
    """28 of 28, derived as (block.order - 1) * 2 + participant.order."""
    assert [e.bracket_position for e in shape.entrants] == WIKI_POSITIONS


def test_the_byes_match_wikipedias_absent_slots(shape):
    """A bye is the absence of a match, and Sofascore says so outright:
    one participant, matchesInRound 0. Wikipedia encodes the same fact as an
    absent slot, and the two agree exactly."""
    assert shape.byes == WIKI_BYES
    assert len(shape.byes) == shape.bracket_size - shape.entrant_count


def test_the_byes_belong_to_the_top_seeds(shape):
    """The structural check: in a 28-draw the four byes go to seeds 1-4, so
    each bye's partner slot holds one of them."""
    by_pos = {e.bracket_position: e for e in shape.entrants}
    partners = []
    for b in shape.byes:
        other = b - 1 if b % 2 == 0 else b + 1
        partners.append(by_pos[other].seed)
    assert sorted(p for p in partners if p) == [1, 2, 3, 4]


# ── seeds and entry types, multiplexed into one field ─────────────────────

def test_the_seeds_are_present_and_complete(shape):
    assert sorted(e.seed for e in shape.entrants if e.seed) == [1, 2, 3, 4, 5, 6, 7, 8]


def test_entry_types_are_read_out_of_the_same_field(shape):
    kinds = sorted({e.entry_type for e in shape.entrants if e.entry_type})
    assert kinds == ["Alt", "Q", "WC"]


def test_entry_types_use_this_projects_vocabulary(shape):
    """Every marker produced must be one scraper.ENTRY_TYPES already knows, or
    a comparison reports two spellings of one fact as a conflict."""
    from app.services.scraper import ENTRY_TYPES
    for e in shape.entrants:
        if e.entry_type:
            assert e.entry_type in ENTRY_TYPES, e.entry_type


@pytest.mark.parametrize("raw,seed,entry", [
    ("1", 1, None), ("32", 32, None), (" 7 ", 7, None),
    ("Q", None, "Q"), ("WC", None, "WC"), ("wc", None, "WC"),
    ("LL", None, "LL"),
    # Sofascore writes an alternate "A"; this project writes "Alt"
    # (scraper.ENTRY_TYPES). Mapping it is what stops the only real
    # disagreement found across four draws from being reported forever.
    ("A", None, "Alt"), ("ALT", None, "Alt"),
    (None, None, None), ("", None, None), ("???", None, None),
])
def test_one_field_two_facts(raw, seed, entry):
    assert _split_seed(raw) == (seed, entry)


def test_a_seed_is_never_mistaken_for_an_entry_type(shape):
    for e in shape.entrants:
        assert not (e.seed is not None and e.entry_type is not None)


# ── names and ids ─────────────────────────────────────────────────────────

def test_every_entrant_carries_a_name_and_a_sofascore_id(shape):
    assert all(e.name for e in shape.entrants)
    assert all(e.sofa_player_id for e in shape.entrants)


def test_the_top_seed_is_where_production_says(shape):
    top = next(e for e in shape.entrants if e.seed == 1)
    assert top.bracket_position == 1
    assert top.name == "Marta Kostyuk"


# ── the shadow comparison ─────────────────────────────────────────────────

class E:
    def __init__(self, name, bracket_position, seed=None, entry_type=None):
        self.name = name
        self.bracket_position = bracket_position
        self.seed = seed
        self.entry_type = entry_type


def test_identical_draws_report_no_disagreement(shape):
    ours = [E(e.name, e.bracket_position, e.seed, e.entry_type) for e in shape.entrants]
    cmp = compare_to_entries(shape, ours)
    assert cmp["matched"] == 28
    assert disagreement_summary(cmp) is None


def test_diacritics_are_not_disagreements(shape):
    """The six apparent mismatches at Guadalajara were all spelling: Bucsa vs
    Bucșa, Jović vs Jovic, Frech vs Fręch, Zarazua vs Zarazúa, Sara vs Sára,
    Lois vs Loïs. Folding is what makes the real fault rate zero."""
    swap = {"Cristina Bucsa": "Cristina Bucșa", "Iva Jović": "Iva Jovic",
            "Lois Boisson": "Loïs Boisson", "Magdalena Frech": "Magdalena Fręch",
            "Renata Zarazua": "Renata Zarazúa", "Sara Bejlek": "Sára Bejlek"}
    ours = [E(swap.get(e.name, e.name), e.bracket_position, e.seed, e.entry_type)
            for e in shape.entrants]
    cmp = compare_to_entries(shape, ours)
    assert cmp["matched"] == 28
    assert disagreement_summary(cmp) is None


def test_a_real_position_disagreement_is_reported(shape):
    ours = [E(e.name, e.bracket_position, e.seed, e.entry_type) for e in shape.entrants]
    ours[0].bracket_position = 30
    cmp = compare_to_entries(shape, ours)
    assert len(cmp["position"]) == 1
    assert "position" in disagreement_summary(cmp)


def test_a_seed_disagreement_is_reported(shape):
    ours = [E(e.name, e.bracket_position, e.seed, e.entry_type) for e in shape.entrants]
    next(o for o in ours if o.seed == 1).seed = 9
    cmp = compare_to_entries(shape, ours)
    assert len(cmp["seed"]) == 1
    assert "seed" in disagreement_summary(cmp)


def test_a_missing_entrant_is_reported_on_the_right_side(shape):
    ours = [E(e.name, e.bracket_position, e.seed, e.entry_type)
            for e in shape.entrants][:-1]
    cmp = compare_to_entries(shape, ours)
    assert len(cmp["only_sofascore"]) == 1
    assert "sofascore only" in disagreement_summary(cmp)


def test_our_byes_are_derived_from_the_slots_nobody_holds(shape):
    ours = [E(e.name, e.bracket_position, e.seed, e.entry_type) for e in shape.entrants]
    cmp = compare_to_entries(shape, ours)
    assert cmp["byes_ours"] == WIKI_BYES
    assert cmp["byes_sofascore"] == WIKI_BYES


def test_a_reversed_name_order_is_not_two_missing_players(shape):
    """Monterrey, 2026-09-21: we hold "Zhang Shuai" and "Liang En-shuo" while
    Sofascore publishes "Shuai Zhang" and "En-Shuo Liang". Folding alone
    reported two players missing from each side and a false 26/28."""
    ours = [E(" ".join(reversed(e.name.split())), e.bracket_position,
              e.seed, e.entry_type) for e in shape.entrants]
    cmp = compare_to_entries(shape, ours)
    assert cmp["matched"] == 28
    assert disagreement_summary(cmp) is None


def test_the_entrys_own_sofa_name_is_used_when_present(shape):
    """The resolver already established and stored this mapping; reusing it
    beats repeating the matching."""
    class ES(E):
        def __init__(self, name, sofa_name, pos, seed=None, entry=None):
            super().__init__(name, pos, seed, entry)
            self.sofa_name = sofa_name

    ours = [ES("Totally Different Spelling" if i == 0 else e.name,
               e.name, e.bracket_position, e.seed, e.entry_type)
            for i, e in enumerate(shape.entrants)]
    cmp = compare_to_entries(shape, ours)
    assert cmp["matched"] == 28, disagreement_summary(cmp)


def test_one_entrant_is_matched_once_even_with_several_keys(shape):
    """Each row answers to up to four keys; a matched row must not also show
    up as 'only in ours'."""
    ours = [E(e.name, e.bracket_position, e.seed, e.entry_type) for e in shape.entrants]
    cmp = compare_to_entries(shape, ours)
    assert cmp["matched"] == 28
    assert cmp["only_ours"] == []
    assert cmp["only_sofascore"] == []


# ── the adapter, against the bracket Wikipedia actually built ─────────────
# Ground truth read off production draws 122 and 142 on 2026-09-21: 16 round-1
# matches with byes at match 1, 5, 12 and 16 (slots 1, 9, 23, 31), and round 2
# carrying those four occupants pre-placed on the side their feeder dictates —
# p1 for an odd feeder, p2 for an even one.

WIKI_R1 = [(1, True, 1, None), (2, False, 3, 4), (3, False, 5, 6), (4, False, 7, 8),
           (5, True, 9, None), (6, False, 11, 12), (7, False, 13, 14),
           (8, False, 15, 16), (9, False, 17, 18), (10, False, 19, 20),
           (11, False, 21, 22), (12, True, 23, None), (13, False, 25, 26),
           (14, False, 27, 28), (15, False, 29, 30), (16, True, 31, None)]
WIKI_R2 = [(1, 1, None), (2, None, None), (3, 9, None), (4, None, None),
           (5, None, None), (6, None, 23), (7, None, None), (8, None, 31)]


@pytest.fixture(scope="module")
def parsed(shape):
    from app.services.sofa_draw_shape import shape_to_parsed
    return shape_to_parsed(shape)


def test_the_adapter_reproduces_the_geometry(parsed):
    assert parsed.draw_size == 32
    assert parsed.num_rounds == 5
    assert len(parsed.players) == 28


def test_the_match_count_per_round_matches_production(parsed):
    from collections import Counter
    per = Counter(m.round_number for m in parsed.matches)
    assert dict(per) == {1: 16, 2: 8, 3: 4, 4: 2, 5: 1}
    assert len(parsed.matches) == 31


def test_round_one_is_identical_to_the_wikipedia_built_bracket(parsed):
    got = [(m.match_number, m.is_bye, m.player1_position, m.player2_position)
           for m in parsed.matches if m.round_number == 1]
    assert got == WIKI_R1


def test_a_bye_advances_its_occupant(parsed):
    byes = [m for m in parsed.matches if m.is_bye]
    assert len(byes) == 4
    for m in byes:
        assert m.player2_position is None
        assert m.winner_position == m.player1_position


def test_round_two_inherits_the_byes_on_the_correct_side(parsed):
    """The side matters: match n joins the winners of n*2-1 and n*2, so the bye
    from an EVEN feeder lands as p2. Production has 23 and 31 as p2."""
    got = [(m.match_number, m.player1_position, m.player2_position)
           for m in parsed.matches if m.round_number == 2]
    assert got == WIKI_R2


def test_nothing_beyond_round_two_is_pre_decided(parsed):
    for m in parsed.matches:
        if m.round_number >= 3:
            assert m.player1_position is None and m.player2_position is None


def test_no_result_is_ever_carried_across(parsed):
    """The cup tree holds winners; the adapter must not, or a shape refresh
    would clear a winner the result pipeline already wrote."""
    for m in parsed.matches:
        if not m.is_bye:
            assert m.winner_position is None
    assert parsed.has_final_winner is False


def test_the_flags_the_writer_gates_on(parsed):
    assert parsed.has_direct_draw is True      # named entrants present
    assert parsed.has_qualifiers is True       # Guadalajara had four Q slots


def test_seeds_and_entry_types_survive_the_adapter(parsed):
    assert sorted(p.seed for p in parsed.players if p.seed) == [1, 2, 3, 4, 5, 6, 7, 8]
    assert sorted({p.entry_type for p in parsed.players if p.entry_type}) == ["Alt", "Q", "WC"]


def test_every_player_keeps_its_slot(parsed):
    assert sorted(p.bracket_position for p in parsed.players) == WIKI_POSITIONS


# ── the completeness gate ────────────────────────────────────────────────

def test_a_full_bracket_is_complete(shape):
    """Guadalajara: 28 entrants + 4 byes = 32 slots, nothing unaccounted for."""
    from app.services.sofa_draw_shape import bracket_is_complete
    assert bracket_is_complete(shape) is True
    assert shape.entrant_count + len(shape.byes) == shape.bracket_size


def test_the_half_filled_bracket_sofascore_actually_served(shape):
    """MEASURED 2026-09-21 10:58, two days before play: Hangzhou and Chengdu
    each read 20 entrants and 4 byes in a 32 bracket, while the Wikipedia draft
    of the same draw held all 28. Writing that would have presented a partial
    field as the draw and stamped it released, since 20 clears the 50% bar."""
    from app.services.sofa_draw_shape import DrawShape, ShapeEntrant, bracket_is_complete
    partial = DrawShape(
        bracket_size=32, num_rounds=5,
        entrants=[ShapeEntrant(bracket_position=i, name=f"P{i}") for i in range(1, 21)],
        byes=[2, 10, 24, 32])
    assert partial.entrant_count == 20
    assert bracket_is_complete(partial) is False


@pytest.mark.parametrize("entrants,byes,bracket", [
    (28, 4, 32), (48, 16, 64), (96, 32, 128), (32, 0, 32), (128, 0, 128),
])
def test_every_real_draw_measured_that_day_is_complete(entrants, byes, bracket):
    from app.services.sofa_draw_shape import DrawShape, ShapeEntrant, bracket_is_complete
    s = DrawShape(bracket_size=bracket, num_rounds=5,
                  entrants=[ShapeEntrant(bracket_position=i, name=f"P{i}")
                            for i in range(entrants)],
                  byes=list(range(byes)))
    assert bracket_is_complete(s) is True


def test_nothing_is_not_complete():
    from app.services.sofa_draw_shape import DrawShape, bracket_is_complete
    assert bracket_is_complete(None) is False
    assert bracket_is_complete(DrawShape(bracket_size=0, num_rounds=0)) is False
    assert bracket_is_complete(DrawShape(bracket_size=32, num_rounds=5)) is False
