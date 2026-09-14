"""When may a sheet that parsed to nothing EMPTY a day — `sheet_is_blank`.

An order of play that comes back with zero matches means one of two opposite
things, and this reading is the whole of what tells them apart:

* SP Open 2026-09-14 — the 4:55 PM revision was three court headers over three
  empty columns. Fifteen minutes later Tuesday's sheet was released carrying
  all four of Monday's remaining R32 matches; nothing had been played. Every
  later revision belongs to another day, so unless this revision retires the
  rows, nothing ever can.
* a parser regression, which looks identical from the outside — and which must
  leave the day exactly where it is, because a bug that empties the page is far
  worse than one that freezes it.

The sheet answers it itself. `vs_lines`, `round_headers` and `slot_markers` are
counted off the raw cells before a column is assigned or a slot is opened, so a
sheet with match boxes on it cannot report zero however badly the slot parser
fails. Measured over the 285-file corpus: this returns True for none of them,
and for none of the 33 that parse to zero matches.

    .venv/bin/python tests/test_blank_sheet.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.oop_parser import sheet_is_blank                 # noqa: E402


def meta(**kw):
    """A parse result, as much of one as the reading looks at."""
    out = {"kind": "oop", "dropped_slots": [],
           "vs_lines": 0, "round_headers": 0, "slot_markers": 0}
    out.update(kw)
    return out


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    return cond


def main():
    ok = True

    # SP Open's blank Monday sheet, as parse_pdf reads it.
    ok &= check("a sheet printing no boxes at all is blank",
                sheet_is_blank(meta()) is True)

    # The parser regressions, each of which alone must save the day's rows.
    # These are the counts SP Open's Tuesday sheet actually carries (15/0/15),
    # against a parse that produced nothing.
    ok &= check("a sheet whose 'vs' lines were lost is NOT blank",
                sheet_is_blank(meta(vs_lines=15, slot_markers=0)) is False)
    ok &= check("a sheet whose start wordings were lost is NOT blank",
                sheet_is_blank(meta(slot_markers=15)) is False)
    ok &= check("a sheet whose event header was lost is NOT blank",
                sheet_is_blank(meta(round_headers=1)) is False)
    ok &= check("a slot opened and left unfilled is NOT blank",
                sheet_is_blank(meta(dropped_slots=[object()])) is False)

    # The documents parse_pdf turns away before it counts anything. All 33 of
    # the corpus files that parse to zero matches are one of these, and none of
    # them is a day to empty: a results summary or an admin placeholder says
    # nothing about today's order of play.
    for kind in ("not-an-oop", "results-summary", "slam", "empty"):
        ok &= check(f"a {kind} document is NOT blank",
                    sheet_is_blank(meta(kind=kind)) is False)

    # UNKNOWN IS NOT ZERO. uso_feed, wta_feed and sofa_schedule satisfy
    # ingest_document's (matches, meta) contract without counting anything off
    # a sheet — there is no sheet. A missing count means "this source cannot
    # tell", and a source that cannot tell may not empty a day.
    ok &= check("a feed meta with no counts is NOT blank",
                sheet_is_blank({"kind": "ok", "date_line": "Monday"}) is False)
    ok &= check("an oop meta missing one count is NOT blank",
                sheet_is_blank({"kind": "oop", "dropped_slots": [],
                                "vs_lines": 0, "round_headers": 0}) is False)
    ok &= check("no meta at all is NOT blank", sheet_is_blank(None) is False)

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def test_blank_sheet():
    """Run by the suite. A file with only a main() is collected as zero tests."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
