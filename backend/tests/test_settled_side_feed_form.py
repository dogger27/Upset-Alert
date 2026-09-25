"""A doubles alternative that WINS becomes two players, even when the result
that decided it was written by a feed.

Chengdu 2026-09-26 (doc 559). The sheet printed three doubles sides as
"team or team"; the day before had been written by the Sofascore feed, so the
results naming the winners were stored as "R Galloway" / "A Goransson" — not
sheet form. `_as_settled_side` only knew how to substitute sheet-form result
rows, kept the one alternative row, and the page served "[4] GALLOWAY USA /
GORANSSON SWE" as ONE player under ONE (Swedish) flag, three slots at once.

    .venv/bin/python tests/test_settled_side_feed_form.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.schedule import (                        # noqa: E402
    settle_from_result_rows, settled_sides_index,
)


class P:
    def __init__(self, side, position, raw_name, nationality=None, draw_entry_id=None):
        self.side = side
        self.position = position
        self.raw_name = raw_name
        self.nationality = nationality
        self.draw_entry_id = draw_entry_id


class R:
    def __init__(self, players, winner_side):
        self.players = players
        self.winner_side = winner_side


def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    return cond


def _served(alts, rows):
    side = [P("a", i, n) for i, n in enumerate(alts, 1)]
    return settle_from_result_rows(side, settled_sides_index(rows))


def main():
    ok = True
    feed = [R([P("a", 1, "R Galloway"), P("a", 2, "A Goransson"),
               P("b", 1, "A Mannarino"), P("b", 2, "A Muller")], "a"),
            R([P("a", 1, "J Hu"), P("a", 2, "H Lu"),
               P("b", 1, "A Wang"), P("b", 2, "Y Zhou")], "b")]
    out, resolved = _served(["[4] GALLOWAY USA / GORANSSON SWE",
                             "MANNARINO FRA / MULLER FRA"], feed)
    ok &= check("a feed-written result settles the side", resolved)
    ok &= check("...into two players, not one team",
                [p.raw_name for p in out] == ["[4] GALLOWAY USA", "GORANSSON SWE"])
    # The router reads the flag off the name when the row states none; what
    # must never happen is one partner's country standing for both.
    ok &= check("...neither under the other's flag",
                all(n in (None, want) for n, want
                    in zip([p.nationality for p in out], ["USA", "SWE"])))
    out, resolved = _served(["[WC] HU CHN / LU CHN", "[WC] WANG CHN / ZHOU CHN"], feed)
    ok &= check("the side-b winner is kept, split",
                resolved and [p.raw_name for p in out] == ["[WC] WANG CHN", "ZHOU CHN"])

    # The sheet-form deciding row (Winston-Salem 2026-08-26) still wins: it
    # carries given names, which the printed alternative does not.
    sheet = [R([P("a", 1, "Jakob SCHNAITTER GER", "GER"), P("a", 2, "Mark WALLNER GER", "GER"),
                P("b", 1, "Nathaniel LAMMONS USA"), P("b", 2, "Jackson WITHROW USA")], "a")]
    out, resolved = _served(["SCHNAITTER GER / WALLNER GER",
                             "LAMMONS USA / WITHROW USA"], sheet)
    ok &= check("a sheet-form result row is still the source",
                resolved and [p.raw_name for p in out]
                == ["Jakob SCHNAITTER GER", "Mark WALLNER GER"])

    # A singles alternative has nothing to split: one person stays one row.
    singles = [R([P("a", 1, "Luka Pavlović"), P("b", 1, "Petr Bar Biryukov")], "a")]
    out, resolved = _served(["Luka PAVLOVIC FRA", "Petr BAR BIRYUKOV"], singles)
    ok &= check("a singles winner stays one row",
                resolved and [p.raw_name for p in out] == ["Luka PAVLOVIC FRA"])

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def test_settled_side_feed_form():
    """Run by the suite. A file with only a main() is collected as zero tests."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
