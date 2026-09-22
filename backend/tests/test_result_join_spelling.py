"""A result recorded by one source settles a slot printed by another.

2026-09-22, Chengdu (doc 410): the Q2 slot "[2] Alexandre MULLER FRA or Luka
PAVLOVIC FRA vs Petr BAR BIRYUKOV or [7] Andre ILAGAN USA" kept offering both
choices after both Q1 feeders had finished. The Q1 results sat on the Sofascore
feed's rows, spelled "Luka Pavlović" and "Petr Bar Biryukov", and the serve
path joined result to slot through `_sheet_surnames` — which keeps the accent
and reads an uncapitalised compound surname as its last word — so neither key
met. `join_surnames` is the reading both spellings agree on.
"""
from app.services.schedule import (join_surnames, settle_from_result_rows,
                                   settled_sides_index)
from app.services.schedule_invariants import _law_people, _people_agree


class _P:
    def __init__(self, side, position, raw_name):
        self.side, self.position, self.raw_name = side, position, raw_name
        self.nationality, self.draw_entry_id = None, None


class _Row:
    def __init__(self, a, b, winner_side):
        self.players = ([_P("a", i, n) for i, n in enumerate(a, 1)]
                        + [_P("b", i, n) for i, n in enumerate(b, 1)])
        self.winner_side = winner_side


def test_feed_and_sheet_spellings_join():
    for feed, sheet in [("Luka Pavlović", "Luka PAVLOVIC FRA"),
                        ("Petr Bar Biryukov", "Petr BAR BIRYUKOV"),
                        ("Alexandre Muller", "[2] Alexandre MULLER FRA"),
                        ("Federico Cinà", "[5] Federico CINA ITA"),
                        ("Botic van de Zandschulp", "Botic VAN DE ZANDSCHULP")]:
        assert join_surnames([feed]) == join_surnames([sheet]), (feed, sheet)


def test_the_readings_that_were_paid_for_still_hold():
    # See feedback-three-letter-caps-is-not-a-country: a surname spelled like
    # a code survives, and the strip loops.
    assert join_surnames(["Luca POW GBR"]) == {"pow"}
    assert join_surnames(["Orlando LUZ"]) == {"luz"}
    assert join_surnames(["[6] Dhakshineswar SURESH IND ANY"]) == {"suresh"}
    assert join_surnames(["H. Nys"]) == {"nys"}
    assert join_surnames(["J. SCHNAITTER GER / M. WALLNER AUT"]) == {"schnaitter", "wallner"}


def test_a_feed_result_settles_the_sheet_slot():
    wins = [_Row(["Alexandre Muller"], ["Luka Pavlović"], "a"),
            _Row(["Petr Bar Biryukov"], ["Andre Ilagan"], "a")]
    idx = settled_sides_index(wins)
    side_a = [_P("a", 1, "[2] Alexandre MULLER FRA"), _P("a", 2, "Luka PAVLOVIC FRA")]
    side_b = [_P("b", 1, "Petr BAR BIRYUKOV"), _P("b", 2, "[7] Andre ILAGAN USA")]
    got_a, ok_a = settle_from_result_rows(side_a, idx)
    got_b, ok_b = settle_from_result_rows(side_b, idx)
    assert ok_a and [p.raw_name for p in got_a] == ["[2] Alexandre MULLER FRA"]
    assert ok_b and [p.raw_name for p in got_b] == ["Petr BAR BIRYUKOV"]


def test_the_law_reads_people_on_its_own():
    # `pending_side_result_unjoined` finds the feeder by whole names.
    assert _people_agree(_law_people(["Petr BAR BIRYUKOV"]),
                         _law_people(["Petr Bar Biryukov"]))
    assert _people_agree(_law_people(["C. BUCSA ESP / N. MELICHAR-MARTINEZ USA"]),
                         _law_people(["Nicole Melichar-Martinez", "Cristina Bucsa"]))
    assert not _people_agree(_law_people(["Alexander ZVEREV GER"]),
                             _law_people(["Mischa Zverev"]))
