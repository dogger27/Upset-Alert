"""A bare event heading is the sheet talking about itself, never a player.

Korea's 2026-09-24 order of play (doc 465) printed "Doubles" on a line of its
own in each court's column — the heading over a doubles section whose draw was
not made yet, with nothing under it. Every header reader wanted a ROUND word
after the discipline, NOISE_RE wanted one too, and `_is_name` takes any
mixed-case line with two letters in it: the word was appended as a PLAYER to
whichever side was open when it arrived. Ostapenko's R16 SINGLES match
published as a doubles match against "Taylah PRESTON AUS / Doubles", Bondar's
the same on the other court, and the schedule's law logged four violations
(doubles_side_not_two twice, name_not_sheet_form twice).

Title case is what made it reachable: the all-caps spelling was already fenced
off twice — `_allcaps_name` rejects "DOUBLES" for its shape, and the court-name
branch tested DISC_RE — and neither lock saw "Doubles". So the rule is stated
as a SHAPE, a whole line of event words and nothing else, and "Singles",
"Mixed Doubles" and "Qualifying" are covered by the same lock rather than
waiting their turn to arrive as players.

    PYTHONPATH=. .venv/bin/pytest tests/test_oop_bare_event_heading.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.oop_parser import (        # noqa: E402
    _event_header, _is_name, _parse_column, parse_pdf,
)


# Whole lines a sheet prints ABOUT its events. None may become a player, a
# court, or anything else the page renders.
HEADINGS = [
    "Doubles",                  # Korea, 2026-09-24 — the incident
    "DOUBLES",
    "Singles",
    "Mixed",
    "Mixed Doubles",
    "MIXED DOUBLES",
    "Qualifying",
    "QUALIFYING",
    "Main Draw",
    "WTA Doubles",
    "Women's Singles",
    "Women\u2019s Doubles",       # the typographic apostrophe a PDF may carry
]

# Lines that must keep their meaning. The names are ones this parser has been
# burned by before; the courts are the two the Korea sheet prints.
NOT_HEADINGS = [
    "CENTER COURT",
    "GRANDSTAND",
    "COURT 1",
    "DOUBLES COURT",            # an event word, but not a line of only them
    "Taylah PRESTON AUS",
    "Marie BOUZKOVA CZE",
    "JJ TRACY USA",
    "[WC] [1] Jelena OSTAPENKO LAT",
    "Magali KEMPEN / Alexandra PANOVA",
]

# The Korea column, as `_parse_column` receives it: (y, text) top to bottom.
# The heading arrives with the slot still open and side b already holding its
# one real name — the exact position that made it a partner.
KOREA_GRANDSTAND = [
    (98, "GRANDSTAND"),
    (114, "Starting at 12:00 PM"),
    (129, "R16"),
    (154, "[6] Anna BONDAR HUN"),
    (164, "vs"),
    (173, "Alina CHARAEVA ARM"),
    (257, "Doubles"),
]


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    return cond


def main():
    ok = True
    for text in HEADINGS:
        ok &= check(f"{text!r} reads as a header", _event_header(text) is not None)
        ok &= check(f"{text!r} is not a player", not _is_name(text))
    for text in NOT_HEADINGS:
        ok &= check(f"{text!r} is not a header", _event_header(text) is None)

    # A header that states a round keeps stating it — this must not have eaten
    # the readers it was added beside.
    ok &= check("'Doubles Final' still yields F", _event_header("Doubles Final") == ("doubles", "F"))
    ok &= check("'QUALIFYING FINAL' still yields Q", _event_header("QUALIFYING FINAL") == (None, "Q"))
    ok &= check("'Singles Semifinal' still yields SF",
                _event_header("Singles Semifinal") == ("singles", "SF"))

    # The column itself: one slot, one player a side, and a SINGLES match.
    col = _parse_column(KOREA_GRANDSTAND, 1)
    ok &= check("the column yields one slot", len(col) == 1)
    if col:
        m = col[0]
        ok &= check("court is GRANDSTAND", m.court == "GRANDSTAND")
        ok &= check("side a is Bondar alone", m.side_a == ["[6] Anna BONDAR HUN"])
        ok &= check("side b is Charaeva alone", m.side_b == ["Alina CHARAEVA ARM"])
        ok &= check("the heading did not make it doubles", not m.is_doubles)
        ok &= check("the heading is not among the unplaceable words", not m.rejected)

    # A heading that states NOTHING must not become the box's header and lock
    # a real one out. "Qualifying" carries neither discipline nor round; the
    # "DOUBLES FINAL" printed under it carries both, and it is the one that
    # must reach the row.
    col = _parse_column([(i * 10, t) for i, t in enumerate((
        "COURT 2", "Starting at 11:00 AM", "Qualifying", "DOUBLES FINAL",
        "[1] ARRIBAGE (FRA) / GUINARD (FRA)", "vs",
        "[3] CASH (GBR) / GLASSPOOL (GBR)"))], 1)
    ok &= check("the heading did not cost the box its slot", len(col) == 1)
    if col:
        m = col[0]
        ok &= check("the real header still reaches the box", m.round == "F")
        ok &= check("and states the discipline", m.discipline == "doubles")
        ok &= check("neither heading became a player",
                    len(m.side_a) == 2 and len(m.side_b) == 2)

    # The sheet itself, while the live archive still holds it.
    pdf = Path("/home/paulwiens/upsetalert/data/oop_pdfs/465.pdf")
    if pdf.exists():
        matches, meta = parse_pdf(pdf.read_bytes())
        ok &= check("the sheet still yields 4 slots", len(matches) == 4)
        ok &= check("no slot was dropped", not meta.get("dropped_slots"))
        for m in matches:
            who = f"{m.court} {m.time}"
            ok &= check(f"{who}: one player a side",
                        len(m.side_a) == 1 and len(m.side_b) == 1)
            ok &= check(f"{who}: reads as singles", not m.is_doubles)
            ok &= check(f"{who}: no heading among its names",
                        not any(_event_header(n) for n in m.side_a + m.side_b))

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def test_oop_bare_event_heading():
    """Run by the suite — a file with only a main() is collected as zero tests."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
