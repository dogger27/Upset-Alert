"""A clock printed over an EMPTY box — `oop_parser._carried_clock`.

SP Open's Thursday reissue (2026-09-17, document 277) left QUADRA 2's first
box blank under "Starting at 12:00 PM" and printed the next one "Followed by".
The parser dropped the blank box, and its noon with it, so the court's first
match was stored with no clock and nothing ahead of it to chain from: the page
printed a bare "Followed by" and the Time view filed it after the 7:20 PM
finish. The same loss hit two corpus sheets that print two wordings in one band
("Starts At 14:30" over "AFTER SUITABLE REST").

The law's check (`court_opener_untimed`) must convict the stored row as it was
and acquit it as it is now.

    .venv/bin/python tests/test_empty_box_clock.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.oop_parser import _parse_column                   # noqa: E402
from app.services.schedule_invariants import court_opener_untimed   # noqa: E402

PDF_277 = Path('/home/paulwiens/upsetalert/data/oop_pdfs/277.pdf')
CORPUS = Path('/home/paulwiens/upsetalert/oop_corpus')


def _column(*lines):
    return _parse_column([(i, t) for i, t in enumerate(lines)], 1)


def _box(a, b, rnd='R16'):
    return (rnd, a, 'vs', b)


def test_a_blank_first_box_hands_its_clock_down():
    ms = _column('QUADRA 2',
                 'Starting at 12:00 PM',
                 'Followed by', *_box('Elina AVANESYAN ARM', '[8] Alina CHARAEVA ARM'),
                 'Not before 2:30 PM', *_box('Dominika SALKOVA CZE', 'Mary STOIANA USA'),
                 'Followed by', *_box('Lucia BRONZETTI ITA', 'Anna BONDAR HUN'))
    assert [(m.time, m.start_raw) for m in ms] == [
        ('12:00 PM', 'Followed by'),
        ('2:30 PM', 'Not before 2:30 PM'),
        # A full box above: the chain times this one, no clock is handed down.
        (None, 'Followed by')]


def test_a_blank_box_mid_court_is_a_floor_for_the_next():
    ms = _column('COURT 1',
                 'Starting at 11:00 AM', *_box('Anna BLINKOVA FRA', 'Suzan LAMENS NED'),
                 'Not before 3:00 PM',
                 'After suitable rest', *_box('Eva LYS GER', 'Nadia PODOROSKA ARG'))
    assert [m.time for m in ms] == ['11:00 AM', '3:00 PM']
    assert ms[1].start_raw == 'After suitable rest'


def test_blank_boxes_in_a_row_carry_through():
    ms = _column('COURT 1',
                 'Starting at 11:00 AM', 'Followed by',
                 'Followed by', *_box('Eva LYS GER', 'Nadia PODOROSKA ARG'))
    assert [m.time for m in ms] == ['11:00 AM']


def test_a_slot_with_its_own_clock_keeps_it():
    ms = _column('COURT 1',
                 'Starting at 11:00 AM',
                 'Not before 1:00 PM', *_box('Eva LYS GER', 'Nadia PODOROSKA ARG'))
    assert [m.time for m in ms] == ['1:00 PM']


def test_a_time_the_sheet_calls_unknown_stays_unknown():
    ms = _column('CANCHA',
                 'Starting at 1:00 PM',
                 'Time TBA - After suitable rest',
                 *_box('Anna ROGERS USA', 'Julia RIERA ARG', rnd='SF'))
    assert [m.time for m in ms] == [None]


def test_a_blank_band_with_no_clock_hands_down_nothing():
    """Guadalajara 2026-09-17 (doc 274): CANCHA's first band printed nothing."""
    ms = _column('CANCHA',
                 'Followed by',
                 'After suitable rest', *_box('Anna ROGERS USA', 'Julia RIERA ARG'))
    assert [m.time for m in ms] == [None]


def test_document_277_opens_quadra_2_at_noon():
    if not PDF_277.exists():
        return
    from app.services.oop_parser import parse_pdf
    matches, _meta = parse_pdf(PDF_277.read_bytes())
    q2 = [m for m in matches if m.court == 'QUADRA 2']
    assert [(m.time, m.start_raw) for m in q2] == [
        ('12:00 PM', 'Followed by'),
        ('2:30 PM', 'Not before 2:30 PM'),
        (None, 'Followed by'),
        (None, 'After suitable rest')]
    assert len(matches) == 14


def test_two_wordings_in_one_band_keep_the_clock():
    """Corpus: Eastbourne 2025 prints "Starts At 14:30" over "AFTER SUITABLE
    REST", Cincinnati 2026-08-19 "Not Before 2:30 PM" over "AFTER REST"."""
    from app.services.oop_parser import parse_pdf
    for rel, court, raw, want in (
            ('atp/2025_741.pdf', 'COURT 1', 'AFTER SUITABLE REST', '14:30'),
            ('atp/2026_422.pdf', 'COURT 10', 'AFTER REST', '2:30 PM')):
        path = CORPUS / rel
        if not path.exists():
            continue
        matches, _meta = parse_pdf(path.read_bytes())
        got = [m.time for m in matches if m.court == court and m.start_raw == raw]
        assert got == [want], (rel, got)


def _row(court, order, clock, stype, note, **kw):
    base = dict(court=court, court_order=order, id=order, start_time_local=clock,
                start_type=stype, start_note=note, started_at=None,
                completed_at=None, winner_side=None, live_scores_json=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_the_law_convicts_the_stored_row_and_acquits_the_fix():
    stored = [_row('QUADRA 2', 1, None, 'followed_by', 'Followed by'),
              _row('QUADRA 2', 2, '2:30 PM', 'not_before', 'Not before 2:30 PM'),
              _row('QUADRA 2', 3, None, 'followed_by', 'Followed by'),
              _row('QUADRA 1', 1, '11:00 AM', 'fixed', 'Starting at 11:00 AM'),
              _row('QUADRA 1', 2, None, 'after_event', 'After suitable rest')]
    assert [(r.court, r.court_order) for r in court_opener_untimed(stored)] == [
        ('QUADRA 2', 1)]
    stored[0].start_time_local = '12:00 PM'
    assert court_opener_untimed(stored) == []


def test_the_law_leaves_a_stated_tba_and_a_played_opener_alone():
    rows = [_row('CANCHA', 1, None, 'after_event', 'Time TBA - After suitable rest'),
            _row('COURT 2', 1, None, 'followed_by', 'Followed by',
                 winner_side='a'),
            _row('COURT 3', 1, None, 'tba', None)]
    assert court_opener_untimed(rows) == []


def test_the_law_reads_the_note_when_the_type_is_misfiled():
    rows = [_row('COURT 4', 1, None, 'tba', 'Followed By')]
    assert len(court_opener_untimed(rows)) == 1


def main():
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as ex:
                fails += 1
                print(f"  FAIL {name} {ex}")
    print("PASS" if not fails else "FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
