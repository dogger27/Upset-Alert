"""The sheet's own heading is never a player, in any casing.

Korea Open, 2026-09-24 (doc 465). Each court's column ended with "Doubles" on
a line of its own — the heading over a doubles section whose draw was not made
yet — and the parser stored it as a PLAYER on whichever side was open when it
arrived. Ostapenko's R16 SINGLES published as a doubles match against "Taylah
PRESTON AUS / Doubles", Bondar's the same on GRANDSTAND, and both rows lost
the bracket match a main-draw singles row is linked by.

The parser fix is oop_parser._BARE_EVENT_RE (da786379). This pins the LAW, and
the loophole it exists to close: `name_not_sheet_form`, the check that
happened to convict the incident, asks a name for a capitalised run — which
"DOUBLES", the spelling the sheets shout their headings in, has. Two names on
a doubles side satisfy `doubles_side_not_two` too, so the all-caps heading
would have published with the law silent.

    .venv/bin/python tests/test_name_is_event_heading.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.oop_parser import _is_name                       # noqa: E402
from app.services.schedule_invariants import (                    # noqa: E402
    _SHEET_CAPS_RE, _names_the_event)


HEADINGS = [
    "Doubles",                  # Korea 2026-09-24 — the incident
    "DOUBLES",                  # the spelling name_not_sheet_form cannot see
    "Singles",
    "Mixed Doubles",
    "Women's Doubles",
    "WTA Doubles",
    "Qualifying",
    "QUALIFICATION",
    "Main Draw",
    "Taylah PRESTON AUS Doubles",   # the same word GLUED to a real name
]

PEOPLE = [
    "[WC] [1] Jelena OSTAPENKO LAT",
    "Taylah PRESTON AUS",
    "[Q] Ye-Xin MA CHN",
    "Alina CHARAEVA ARM",
    "[6] Anna BONDAR HUN",
    "Orlando LUZ BRA",              # three capitals that are a surname
    "Li TU AUS",
    "JJ TRACY USA",
    "Dhakshineswar SURESH IND ANY",
    "Magali KEMPEN / Alexandra PANOVA",
    "[Q/LL] Qualifier/LL",          # names nobody, but it is a ROLE, not a heading
    "D. Parry or D. Vekic",
    "[ALT] Nadiia KICHENOK UKR",
    "",
]


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    return cond


def main():
    ok = True
    for text in HEADINGS:
        ok &= check(f"{text!r} is the sheet's heading", _names_the_event(text))
    for text in PEOPLE:
        ok &= check(f"{text!r} is not a heading", not _names_the_event(text))

    # THE SIBLING THE LAW FOUND, one archive away (wta/2026_1038): "Juniors -
    # Boys Singles FINAL", printed over the women's doubles final and read as
    # a third member of Andreeva/Shnaider's team. The audience before the
    # discipline is the shape no header reader accepts — the two that want an
    # event word first cannot see past "Juniors - ", and the bare-heading rule
    # wants no round word at all — so the parser fences it off as the side
    # event it is. Diffed over both archives: 393 sheets, one line changed.
    for text in ("Juniors - Boys Singles FINAL", "Juniors", "JUNIOR BOYS SF"):
        ok &= check(f"the parser refuses {text!r} as a name", not _is_name(text))
    for text in ("Mirra ANDREEVA", "Diana SHNAIDER", "[2] Katerina SINIAKOVA CZE"):
        ok &= check(f"the parser still takes {text!r}", _is_name(text))

    # WHY THIS LAW EXISTS BESIDE name_not_sheet_form: the neighbour passes the
    # all-caps heading, which is the spelling every ATP sheet uses.
    ok &= check("name_not_sheet_form cannot see 'DOUBLES'",
                bool(_SHEET_CAPS_RE.search("DOUBLES")))
    ok &= check("name_not_sheet_form does see 'Doubles'",
                not _SHEET_CAPS_RE.search("Doubles"))

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def test_name_is_event_heading():
    """Run by the suite. A file with only a main() is collected as zero tests."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
