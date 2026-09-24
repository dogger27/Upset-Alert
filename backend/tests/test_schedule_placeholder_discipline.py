"""A placeholder side is an open seat, not a choice — the OTHER side sets the shape.

Chengdu 2026-09-25 (doc 516) printed COURT 2's doubles R16 as "Alternate vs
Marcelo MELO / Ryan SEGGERMAN". The placeholder made the slot tbd, and
`_classify` read any tbd row without a slash as "X or Y" alternatives — singles.
The page then served "MELO or SEGGERMAN".

The counter-examples are the singles shapes that rule exists for.

    PYTHONPATH=. .venv/bin/pytest tests/test_schedule_placeholder_discipline.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.oop_parser import Match      # noqa: E402
from app.services.schedule import _classify     # noqa: E402


def _m(a, b, tbd_side):
    return Match(court='COURT 2', side_a=list(a), side_b=list(b),
                 tbd=bool(tbd_side), tbd_side=tbd_side)


CASES = [
    # the incident: a role word against a real pair
    (_m(['Alternate'], ['Marcelo MELO BRA', 'Ryan SEGGERMAN USA'], 'a'), 'doubles'),
    (_m(['Marcelo MELO BRA', 'Ryan SEGGERMAN USA'], ['[Alt] Alternate'], 'b'), 'doubles'),
    # Sao Paulo 2026-09-14: a role word against one player stays singles
    (_m(['[Q/LL] Qualifier/LL'], ['[3] Solana SIERRA ARG'], 'a'), 'singles'),
    # a role word against "X or Y" is a singles alternative, not a pair
    (_m(['Qualifier'], ['Diane PARRY FRA', 'Donna VEKIC CRO'], 'ab'), 'singles'),
    # an ordinary unresolved singles side
    (_m(['[7] Daniil MEDVEDEV'], ['Robin DAMM', 'Hamad SHELBAYH'], 'b'), 'singles'),
]


def test_placeholder_side_does_not_decide_discipline():
    for match, want in CASES:
        _stage, got = _classify(match)
        assert got == want, (match.side_a, match.side_b, got, want)


if __name__ == '__main__':
    test_placeholder_side_does_not_decide_discipline()
    print('ok')
