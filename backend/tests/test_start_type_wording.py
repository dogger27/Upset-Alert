"""A not-before floor printed as "NB" — `schedule._start_type_of`.

Guadalajara 2026-09-15 printed its last doubles slot "NB 3:30 PM - After
suitable rest". The classifier knew only the spelled-out "not before", so the
row was stored `after_event`, the estimate chain gave it no floor, and the page
said "~2:50 PM" for a match that could not start before 3:30. The wordings
below are that sheet's and the corpus's own, including the two older sheets
that carried the same abbreviation unnoticed.

The law's independent reading (`schedule_invariants._NOT_BEFORE_WORDING_RE`)
must agree with the service on every one of them, and the parser must open a
slot on a line that says only "NB 3:30 PM".

    .venv/bin/python tests/test_start_type_wording.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.oop_parser import SLOT_RE                        # noqa: E402
from app.services.schedule import _start_type_of                   # noqa: E402
from app.services.schedule_invariants import (                     # noqa: E402
    _NOT_BEFORE_WORDING_RE)


CASES = [
    # (printed wording, printed clock, stored type)
    ("NB 3:30 PM - After suitable rest", "3:30 PM", "not_before"),
    ("After suitable rest, but NB 2:30", "2:30", "not_before"),
    ("Starting at NB 3:00 PM Singles", "3:00 PM", "not_before"),
    ("N/B 5:00 PM", "5:00 PM", "not_before"),
    ("Not before 5:00 PM", "5:00 PM", "not_before"),
    ("Not Bef. 1:00 PM", "1:00 PM", "not_before"),
    ("After suitable rest", None, "after_event"),
    ("AFTER REST, TIME TBA", None, "after_event"),
    ("30 mins after ceremony", None, "after_event"),
    ("Starting at 1:00 PM", "1:00 PM", "fixed"),
    ("Followed by", None, "followed_by"),
]


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    return cond


def main():
    ok = True
    for raw, clock, want in CASES:
        got = _start_type_of(SimpleNamespace(start_raw=raw, time=clock))
        ok &= check(f"{raw!r} -> {want} (got {got})", got == want)
        law = bool(_NOT_BEFORE_WORDING_RE.search(raw))
        ok &= check(f"law agrees on {raw!r}", law == (want == "not_before"))
    ok &= check("a bare 'NB 3:30 PM' line opens a slot",
                bool(SLOT_RE.search("NB 3:30 PM")))
    ok &= check("a name holding NB with no clock does not",
                not SLOT_RE.search("Nb KOVAC CRO"))
    print("PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())


def test_start_type_wording():
    assert main() == 0
