"""A doubles pair of NEUTRALS: surnames only, no country codes at all.

Hangzhou 2026-09-26 (doc 560) printed COURT 1's fourth slot as "LIUTAREVICH /
SAFIULLIN or [2] NOUZA (CZE) / OBERLEITNER (AUT)". Russian and Belarusian
players carry no flag, and every all-caps name rule wanted a country as proof
of a person — so the neutral pair was read as furniture and the open side
offered ONE team. The counter-examples are the furniture that same rule
exists to keep out.

    PYTHONPATH=. .venv/bin/pytest tests/test_oop_neutral_pair.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.oop_parser import _is_name, parse_pdf   # noqa: E402
from app.services.schedule_invariants import check_parse  # noqa: E402

PAIRS = [
    "LIUTAREVICH / SAFIULLIN",          # doc 560 — the incident
    "[3] RUBLEV / KHACHANOV",
    "LIUTAREVICH / NOUZA CZE",          # one neutral, one flagged
    "[WC] SUN CHN / ZHANG CHN",
]

NOT_PEOPLE = [
    "ANY MATCH ON ANY COURT MAY BE MOVED",
    "MEDVEDEV",                         # a lone word vouches for nothing
    "USA / FRA",
    "TBA / LL",
    "SINGLES / DOUBLES",
]

SHEET = Path('/home/paulwiens/upsetalert/data/oop_pdfs/560.pdf')


def test_neutral_pair_is_a_name():
    for s in PAIRS:
        assert _is_name(s), s
    for s in NOT_PEOPLE:
        assert not _is_name(s), s


def test_doc_560_keeps_both_alternatives():
    if not SHEET.exists():
        return
    matches, meta = parse_pdf(SHEET.read_bytes())
    last = [m for m in matches if m.court == 'COURT 1'][-1]
    assert last.tbd_side == 'b'
    assert last.side_b == ['LIUTAREVICH / SAFIULLIN',
                           '[2] NOUZA CZE / OBERLEITNER AUT']
    assert not meta['rejected_pairs']
    assert not [v for v in check_parse(meta, len(matches))
                if v['code'] == 'pair_line_rejected']


def test_rejected_pair_alarms():
    meta = {'rejected_pairs': [('COURT 1', 'LIUTAREVICH / SAFIULLIN')]}
    assert [v['code'] for v in check_parse(meta, 1)] == ['pair_line_rejected']
