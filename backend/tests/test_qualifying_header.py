"""A spelled-out QUALIFYING round header — `oop_parser._QUALI_HEADER_RE`.

Chengdu's Wednesday sheet (2026-09-23, document 408) printed "QUALIFYING
FINAL" over its four qualifying boxes. `_EVENT_HEADER_RE` wants a discipline
word first, so nothing read the line and the four rows were stored with no
round. The alarm for exactly that (`printed_round_dropped`) was silent, because
the sheet's header count was taken with the reader's own regex.

The law must convict the parse as it was and acquit it as it is now.

    .venv/bin/python tests/test_qualifying_header.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import oop_parser                                 # noqa: E402
from app.services.oop_parser import _event_header, _parse_column, parse_pdf  # noqa: E402
from app.services.schedule_invariants import check_parse            # noqa: E402

PDF_408 = Path('/home/paulwiens/upsetalert/data/oop_pdfs/408.pdf')


def _codes(meta, matches):
    return sorted(v['code'] for v in check_parse(meta, len(matches),
                                                 [m.round for m in matches]))


def test_qualifying_final_is_the_generic_last_qualifying_round():
    # Never the tournament's final: the line ends in FINAL.
    assert _event_header('QUALIFYING FINAL') == (None, 'Q')
    assert _event_header('Qualifying - Final') == (None, 'Q')
    assert _event_header('QUALIFYING ROUND 1') == (None, 'Q1')
    assert _event_header('SINGLES QUALIFYING ROUND 2') == ('singles', 'Q2')
    # The readers that were already there are untouched.
    assert _event_header('DOUBLES FINAL') == ('doubles', 'F')
    assert _event_header('SINGLES SEMI-FINAL') == ('singles', 'SF')
    # A BARE "QUALIFYING" STATES NO ROUND, and never did. It is now READ —
    # as a section heading stating nothing, so that it cannot be taken for a
    # player (test_oop_bare_event_heading) — and the round it yields is still
    # None, which is the whole of what this line has ever guarded.
    assert _event_header('QUALIFYING') == (None, None)


def test_the_header_reaches_the_box_and_files_it_qualifying():
    ms = _parse_column([(i, t) for i, t in enumerate((
        'COURT 1', 'Starts At 13:00', 'QUALIFYING FINAL',
        '[2] Alexandre MULLER (FRA) or', 'Luka PAVLOVIC (FRA)', 'vs',
        'Petr BAR BIRYUKOV or', '[7] Andre ILAGAN (USA)'))], 1)
    assert len(ms) == 1
    m = ms[0]
    assert m.round == 'Q' and m.tbd_side == 'ab'
    # A header with no discipline states no shape: it must not make an
    # "A or B" singles slot doubles.
    assert m.discipline is None and not m.rejected


def test_doc_408_parses_its_rounds_and_the_law_is_quiet():
    if not PDF_408.exists():
        return
    ms, meta = parse_pdf(PDF_408.read_bytes())
    assert [(m.court, m.round) for m in ms] == [
        ('CENTER COURT', None), ('CENTER COURT', None),
        ('COURT 1', 'Q'), ('COURT 1', 'Q'), ('COURT 2', 'Q'), ('COURT 2', 'Q')]
    assert meta['round_headers'] == 4
    assert _codes(meta, ms) == []


def test_the_law_convicts_the_reader_as_it_was():
    if not PDF_408.exists():
        return
    real = oop_parser._QUALI_HEADER_RE
    oop_parser._QUALI_HEADER_RE = re.compile(r'(?!)')   # the old reader: none
    try:
        ms, meta = parse_pdf(PDF_408.read_bytes())
    finally:
        oop_parser._QUALI_HEADER_RE = real
    assert not any(m.round for m in ms)
    assert _codes(meta, ms) == ['printed_round_dropped'] + ['printed_round_unread'] * 4


def test_the_count_ignores_an_event_name():
    # wta/2026_1106 advertises the year-end "ATP FINALS": a tour, no event word.
    assert not oop_parser._HEADER_SHAPED_RE.match('ATP FINALS')
    assert oop_parser._HEADER_SHAPED_RE.match('QUALIFYING FINAL')
    assert oop_parser._HEADER_SHAPED_RE.match('WTA Doubles Final')


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
