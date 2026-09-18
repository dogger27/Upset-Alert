"""A nationality code the sheets print, whichever standard it comes from.

The WTA's Singapore Open sheet for 2026-09-19 (document 291) printed its two
wildcards with Singapore's ISO code, SGP, not the IOC's SIN. Unrecognised, it
failed two ways on one page: "[WC] Eva Marie DESVIGNES SGP" kept it glued on and
raised name_trailing_noncountry, and "[WC] Kai Ning Chanya NG SGP", whose code
sat 0.6pt lower and wrapped onto its own line, lost it without a word — a lone
three-capital line is only a continuation when it is a real country.

The counter-examples are the surnames the table must never swallow.

    PYTHONPATH=. .venv/bin/pytest tests/test_oop_country_codes.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import schedule_invariants                     # noqa: E402
from app.services.oop_parser import (COUNTRY_CODES, _is_continuation,  # noqa: E402
                                     parse_pdf)
from app.services.schedule import _clean_name                    # noqa: E402


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    return cond


def main():
    ok = True
    ok &= check("SGP is a country", "SGP" in COUNTRY_CODES)
    ok &= check("SIN still is", "SIN" in COUNTRY_CODES)
    ok &= check("the invariant reads the same table",
                schedule_invariants.COUNTRY_CODES is COUNTRY_CODES)
    ok &= check("a wrapped SGP line is a continuation", _is_continuation("SGP"))
    ok &= check("a wrapped TBC line still is not", not _is_continuation("TBC"))
    for raw, want in [
        ("[WC] Eva Marie DESVIGNES SGP", "Eva Marie DESVIGNES"),
        ("[WC] Kai Ning Chanya NG SGP", "Kai Ning Chanya NG"),
        ("Orlando LUZ", "Orlando LUZ"),
        ("Luca POW GBR", "Luca POW"),
    ]:
        got = _clean_name(raw)
        ok &= check(f"{raw!r} -> {got!r}", got == want)

    # The sheet itself, if it is still on disk: both wildcards keep their code.
    pdf = Path("/home/paulwiens/upsetalert/data/oop_pdfs/291.pdf")
    if pdf.exists():
        matches, _meta = parse_pdf(pdf.read_bytes())
        names = [n for m in matches for n in list(m.side_a) + list(m.side_b)]
        ok &= check("the sheet still yields 8 slots", len(matches) == 8)
        ok &= check("Desvignes keeps SGP", "[WC] Eva Marie DESVIGNES SGP" in names)
        ok &= check("Ng keeps SGP", "[WC] Kai Ning Chanya NG SGP" in names)

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def test_oop_country_codes():
    """Run by the suite — a file with only a main() is collected as zero tests."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
