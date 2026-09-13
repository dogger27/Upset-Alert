"""A slot side that names NOBODY, against the shapes the sheets actually print.

Sao Paulo 2026-09-14 printed three R32 singles slots as "[Q/LL] Qualifier/LL" —
a seat the tournament says belongs to a qualifier or a lucky loser, and to no
person yet. Read as a name and split on its slash (which on a sheet means
PARTNERS) it published as a three-person doubles team against [3] Solana Sierra.

The counter-examples matter as much as the case: a lone "[Q]" is the wrapped
marker of the name above and must stay a continuation, and every real name here
is one the parser has been burned by before (LUZ, POW, TU, SURESH IND ANY).

    PYTHONPATH=. .venv/bin/pytest tests/test_oop_placeholder_side.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.oop_parser import is_placeholder, parse_pdf   # noqa: E402


PLACEHOLDERS = [
    "[Q/LL] Qualifier/LL",      # Sao Paulo, 2026-09-14 — the incident
    "Qualifier",
    "[Q] Qualifier",
    "Qualifier/Qualifier",
    "Bye",
    "[Alt] Alternate",
    "LL",
]

PEOPLE = [
    "[Q]",                      # the wrapped marker of the name above
    "[WC]",
    "CZE",
    "[LL] Daniel ALTMAIER GER",
    "[Alt] Andrea COLLARINI ARG",
    "Luca POW GBR",
    "Orlando LUZ",
    "Li TU AUS",
    "Dhakshineswar SURESH IND ANY",
    "JJ TRACY USA",
    "Qualifier BRA",            # not a shape any tour prints — not a licence
    "Magali KEMPEN / Alexandra PANOVA",
    "D. Parry or D. Vekic",
    "",
]


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    return cond


def main():
    ok = True
    for text in PLACEHOLDERS:
        ok &= check(f"{text!r} names nobody", is_placeholder(text))
    for text in PEOPLE:
        ok &= check(f"{text!r} is not a placeholder", not is_placeholder(text))

    # The whole sheet, if it is still on disk. The three placeholder slots must
    # come back SINGLES, one entry a side, with the open side declared.
    pdf = Path("/home/paulwiens/upsetalert/data/oop_pdfs/245.pdf")
    if pdf.exists():
        matches, _meta = parse_pdf(pdf.read_bytes())
        ok &= check("the sheet still yields 8 slots", len(matches) == 8)
        open_seats = [m for m in matches
                      if any(is_placeholder(n)
                             for n in list(m.side_a) + list(m.side_b))]
        ok &= check("three slots hold an open seat", len(open_seats) == 3)
        for m in open_seats:
            side = m.side_a if any(is_placeholder(n) for n in m.side_a) else m.side_b
            key = 'a' if side is m.side_a else 'b'
            ok &= check(f"{m.court}: kept whole", len(side) == 1)
            ok &= check(f"{m.court}: not a doubles team", not m.is_doubles)
            ok &= check(f"{m.court}: side {key} declared unresolved",
                        m.tbd and key in (m.tbd_side or ''))

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def test_oop_placeholder_side():
    """Run by the suite — a file with only a main() is collected as zero tests."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
