"""The round the sheet does not print, from the feed that declined the day.

Chengdu's 22 September qualifying showed a BLANK where "Q1" belongs, while
Hangzhou the same morning showed Q1 (owner, 2026-09-21, with a screenshot).
Neither was a parse bug. The ATP's order of play for that day prints no round
anywhere on it — checked against the file itself — and Sofascore's feed, which
did know every round, had DECLINED the day for having no court to order it on.
So the day went to a source that has courts and no rounds, and the half that
was missing was simply thrown away.

The two sources are complementary and were being treated as exclusive. A
declined day now hands its rounds back, and they fill the rows the sheet could
not label.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.schedule_feeds import _surname, rounds_by_pair   # noqa: E402


class M:
    """Only the fields the pairing reads."""

    def __init__(self, side_a, side_b, round=None):
        self.side_a, self.side_b, self.round = side_a, side_b, round


def test_a_pair_of_surnames_names_the_round():
    # The feed's own spelling, read off Sofascore for this very day.
    got = rounds_by_pair([M(["Alexandre Muller"], ["Luka Pavlović"], "Q1")])
    assert got == {frozenset({"muller", "pavlovic"}): "Q1"}


def test_the_two_sources_spell_a_name_DIFFERENTLY_and_still_meet():
    """THE ASSERTION THE WHOLE FIX RESTS ON. The round comes from the feed and
    the rows come from the sheet, so the key has to survive both spellings.
    Measured against production on 2026-09-21: Sofascore says "Alexandre
    Muller" and "Luka Pavlović"; the stored sheet row says "[2] Alexandre
    MULLER FRA" and "Luka PAVLOVIC FRA" — a seed bracket, block capitals, a
    trailing country code and a dropped diacritic between them."""
    feed = frozenset({_surname("Alexandre Muller"), _surname("Luka Pavlović")})
    sheet = frozenset({_surname("[2] Alexandre MULLER FRA"),
                       _surname("Luka PAVLOVIC FRA")})
    assert feed == sheet == frozenset({"muller", "pavlovic"})
    assert rounds_by_pair([M(["Alexandre Muller"], ["Luka Pavlović"], "Q1")])[sheet] == "Q1"


def test_both_sides_are_required():
    """One side is how a qualifying row once matched somebody else's main-draw
    fixture (see schedule.resolve_pending_rounds). A pair, or nothing."""
    assert rounds_by_pair([M(["Alexandre Muller"], [], "Q1")]) == {}
    assert rounds_by_pair([M([], ["Luka Pavlović"], "Q1")]) == {}


def test_a_row_with_no_round_contributes_nothing():
    assert rounds_by_pair([M(["Alexandre Muller"], ["Luka Pavlović"], None)]) == {}
    assert rounds_by_pair([M(["Alexandre Muller"], ["Luka Pavlović"], "  ")]) == {}


def test_doubles_pairs_key_on_all_four_surnames():
    got = rounds_by_pair([M(["Alex Bolt", "Omar Jasika"],
                            ["Taro Daniel", "Jake Delaney"], "Q1")])
    assert got == {frozenset({"bolt", "jasika", "daniel", "delaney"}): "Q1"}


def test_the_same_pair_twice_with_different_rounds_is_dropped():
    """Two rows for the same two players on one day means something upstream is
    wrong, and a confident wrong round is worse than a blank one."""
    got = rounds_by_pair([M(["Alexandre Muller"], ["Luka Pavlović"], "Q1"),
                          M(["Alexandre Muller"], ["Luka Pavlović"], "Q2")])
    assert got == {}


def test_the_same_pair_twice_agreeing_is_kept():
    got = rounds_by_pair([M(["Alexandre Muller"], ["Luka Pavlović"], "Q1"),
                          M(["Luka Pavlović"], ["Alexandre Muller"], "Q1")])
    assert got == {frozenset({"muller", "pavlovic"}): "Q1"}


def test_the_real_chengdu_sheet_is_fully_keyed():
    """The eight rows of 22 September, as the feed states them."""
    pairs = [("Alexandre Muller", "Luka Pavlović"),
             ("Petr Bar Biryukov", "Andre Ilagan"),
             ("Elias Ymer", "Alexis Galarneau"),
             ("Shintaro Mochizuki", "Linang Xiao"),
             ("Lloyd Harris", "Kenta Miyoshi"),
             ("Luca Castelnuovo", "Pavel Kotov"),
             ("Nikoloz Basilashvili", "Hanlei Lu"),
             ("Kaichi Uchida", "Federico Cina")]
    got = rounds_by_pair([M([a], [b], "Q1") for a, b in pairs])
    assert len(got) == 8
    assert set(got.values()) == {"Q1"}


def test_nothing_in_nothing_out():
    assert rounds_by_pair([]) == {}
    assert rounds_by_pair(None) == {}
