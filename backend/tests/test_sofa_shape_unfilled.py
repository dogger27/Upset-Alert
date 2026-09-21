"""A slot one side has not filled yet is not a disagreement.

2026 Hangzhou and Chengdu (draws 122 and 145), 2026-09-21 18:20: the cup tree
held 20 entrants and 4 byes in a 32 bracket, we held 24 named entries and 4
blank qualifier slots, and resolve_draw warned "Draw shape disagrees with
Wikipedia … 4 in ours only" for each — four players Sofascore had not slotted
yet, with matched=20 and identical byes. The tree fills incrementally
(bracket_is_complete's docstring measured exactly this state that morning), so
the warning would have fired every day until play.

Rebuilt here from the Guadalajara fixture, which has the same geometry: 28
entrants in a 32 bracket, byes [2, 10, 24, 32], four of the entrants Q.
"""
import json
from pathlib import Path

import pytest

from app.services.sofa_draw_shape import (
    DrawShape,
    compare_to_entries,
    disagreement_summary,
    draw_shape,
)

FIXTURE = Path(__file__).parent / "fixtures" / "cuptree_guadalajara_2026.json"


class E:
    def __init__(self, name, bracket_position, seed=None, entry_type=None):
        self.name = name
        self.bracket_position = bracket_position
        self.seed = seed
        self.entry_type = entry_type


@pytest.fixture(scope="module")
def full():
    return draw_shape(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _partial(full, drop):
    """The same tree with some entrants not slotted yet."""
    return DrawShape(bracket_size=full.bracket_size, num_rounds=full.num_rounds,
                     entrants=[e for e in full.entrants if e.bracket_position not in drop],
                     byes=list(full.byes))


def _hangzhou(full):
    """Production's state: our qualifier slots blank, four named players the
    tree has not placed, the tree's own qualifier slots empty too."""
    qs = [e.bracket_position for e in full.entrants if e.entry_type == "Q"]
    assert len(qs) == 4
    unslotted = [e.bracket_position for e in full.entrants
                 if e.entry_type != "Q"][:4]
    ours = [E("" if e.bracket_position in qs else e.name, e.bracket_position,
              e.seed, e.entry_type) for e in full.entrants]
    return _partial(full, set(qs) | set(unslotted)), ours, qs, unslotted


def test_a_tree_still_filling_in_is_no_disagreement(full):
    tree, ours, qs, unslotted = _hangzhou(full)
    assert tree.entrant_count == 20 and len(tree.byes) == 4
    cmp = compare_to_entries(tree, ours)
    assert cmp["matched"] == 20
    assert disagreement_summary(cmp) is None
    assert cmp["only_ours"] == []
    assert len(cmp["pending_sofascore"]) == 4
    assert cmp["unfilled_sofascore"] == sorted(qs + unslotted)


def test_a_real_conflict_on_a_partial_tree_is_still_reported(full):
    """Only unfilled slots are forgiven: two sources stating the same slot
    differently is still a disagreement, however incomplete the tree."""
    tree, ours, _, _ = _hangzhou(full)
    stated = next(o for o in ours if o.name and o.bracket_position
                  in {s.bracket_position for s in tree.entrants})
    stated.bracket_position = 99
    cmp = compare_to_entries(tree, ours)
    assert "position" in disagreement_summary(cmp)


def test_our_player_at_a_slot_the_tree_filled_differently_is_reported(full):
    tree, ours, _, _ = _hangzhou(full)
    victim = next(o for o in ours if o.name and o.bracket_position
                  in {s.bracket_position for s in tree.entrants})
    victim.name = "Somebody Else Entirely"
    cmp = compare_to_entries(tree, ours)
    assert cmp["only_ours"] == ["Somebody Else Entirely"]
    why = disagreement_summary(cmp)
    assert "in ours only" in why and "in sofascore only" in why


def test_a_qualifier_the_tree_names_first_is_no_disagreement(full):
    """The other direction: Sofascore places a qualifier before our draw
    names the slot. That fills on our side on its own."""
    qs = {e.bracket_position for e in full.entrants if e.entry_type == "Q"}
    ours = [E("" if e.bracket_position in qs else e.name, e.bracket_position,
              e.seed, e.entry_type) for e in full.entrants]
    cmp = compare_to_entries(full, ours)
    assert disagreement_summary(cmp) is None
    assert sorted(p for p, _ in cmp["pending_ours"]) == sorted(qs)
    assert cmp["only_sofascore"] == []


def test_a_tree_name_at_a_slot_we_hold_named_is_still_reported(full):
    ours = [E(e.name, e.bracket_position, e.seed, e.entry_type) for e in full.entrants]
    ours[3].name = "Not The Same Player"
    why = disagreement_summary(compare_to_entries(full, ours))
    assert "in sofascore only" in why and "in ours only" in why


def test_our_bye_at_a_slot_the_tree_has_not_stated_is_no_disagreement(full):
    """A tree still filling can leave a whole pair empty, so a bye of ours
    there is a slot it has not stated yet — not one it denies."""
    tree = DrawShape(bracket_size=full.bracket_size, num_rounds=full.num_rounds,
                     entrants=[e for e in full.entrants if e.bracket_position != 1],
                     byes=[b for b in full.byes if b != 2])
    ours = [E(e.name, e.bracket_position, e.seed, e.entry_type) for e in full.entrants]
    cmp = compare_to_entries(tree, ours)
    assert disagreement_summary(cmp) is None
    assert cmp["unfilled_sofascore"] == [1, 2]
    assert cmp["pending_sofascore"] == [full.entrants[0].name]


def test_a_bye_the_tree_states_against_our_entrant_is_reported(full):
    moved = full.entrants[0]
    tree = DrawShape(bracket_size=full.bracket_size, num_rounds=full.num_rounds,
                     entrants=full.entrants[1:],
                     byes=sorted(full.byes + [moved.bracket_position]))
    ours = [E(e.name, e.bracket_position, e.seed, e.entry_type) for e in full.entrants]
    why = disagreement_summary(compare_to_entries(tree, ours))
    assert "byes" in why and "in ours only" in why


# ── a tree of placeholder names ───────────────────────────────────────────

def _placeholder_payload():
    """An 8 bracket Sofascore has created but not named — SP Open's shape on
    2026-09-12: every team a disabled R16Pn — with one bye."""
    blocks = []
    for order in range(1, 5):
        parts = [{"order": 1, "team": {"id": 900 + order * 2 - 1,
                                       "name": f"R16P{order * 2 - 1}", "disabled": True}}]
        if order != 1:
            parts.append({"order": 2, "team": {"id": 900 + order * 2,
                                               "name": f"R16P{order * 2}",
                                               "disabled": True}})
        blocks.append({"order": order, "matchesInRound": 0 if order == 1 else 1,
                       "participants": parts})
    return {"cupTrees": [{"name": "2026 Somewhere", "rounds": [{"blocks": blocks}]}]}


def test_placeholder_entrants_are_marked():
    shape = draw_shape(_placeholder_payload())
    assert shape.entrant_count == 7
    assert all(e.placeholder for e in shape.entrants)
    assert shape.byes == [2]


def test_a_tree_of_placeholders_is_no_disagreement():
    shape = draw_shape(_placeholder_payload())
    ours = [E(f"Player {p}", p) for p in (1, 3, 4, 5, 6, 7, 8)]
    cmp = compare_to_entries(shape, ours)
    assert disagreement_summary(cmp) is None
    assert cmp["matched"] == 0
    assert len(cmp["pending_sofascore"]) == 7


def test_named_entrants_are_not_placeholders(full):
    assert not any(e.placeholder for e in full.entrants)
