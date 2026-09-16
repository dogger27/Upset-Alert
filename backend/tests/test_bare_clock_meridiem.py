"""A clock printed without AM/PM — `oop_parser.settle_meridiems`.

SP Open's Thursday sheet (2026-09-17, document 275) printed "NB 2:30 possible
court change" on two courts that had opened at 11:00 AM, on a sheet that
wrote AM/PM on every other clock. Every reader of `start_time_local` takes a
clock with no meridiem as 24-hour, so both floors were stored as 2:30 in the
MORNING: the chain let Blinkova's estimate run to "~2:25 PM" under a floor of
2:30 PM, and the law's floor check — reading the same 2:30 AM — agreed.

A bare clock is still right on a 24-hour sheet ("Starts At 14:30", "Not
Before 16:00" — a third of the ATP corpus), so the meridiem is settled from
the SHEET: only where the sheet itself writes AM/PM, and then from the
court's own running order. The law's check (`clock_runs_backwards`) must
convict the stored rows as they were and acquit them as they are now.

    .venv/bin/python tests/test_bare_clock_meridiem.py
"""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.oop_parser import Match, settle_meridiems          # noqa: E402
from app.services.schedule_invariants import clock_runs_backwards    # noqa: E402

PDF_275 = Path('/home/paulwiens/upsetalert/data/oop_pdfs/275.pdf')


def _m(court, time, raw):
    return Match(court=court, time=time, start_raw=raw)


def _times(matches):
    return [m.time for m in matches]


def test_sp_open_thursday_floors_are_afternoon():
    ms = [
        _m('CENTRAL', '11:00 AM', 'Starting at 11:00 AM'),
        _m('CENTRAL', '1:00 PM', 'Not before 1:00 PM'),
        _m('CENTRAL', '2:30', 'NB 2:30 possible court change'),
        _m('CENTRAL', '5:30 PM', 'Not before 5:30 PM'),
        _m('CENTRAL', None, 'After suitable rest'),
        _m('QUADRA 1', '11:00 AM', 'Starting at 11:00 AM'),
        _m('QUADRA 1', '12:00 PM', 'Not before 12:00 PM'),
        _m('QUADRA 1', '2:30', 'NB 2:30 possible court change'),
    ]
    settle_meridiems(ms)
    assert _times(ms) == ['11:00 AM', '1:00 PM', '2:30 PM', '5:30 PM', None,
                          '11:00 AM', '12:00 PM', '2:30 PM']
    # The printed wording is never touched — start_note stays faithful.
    assert ms[2].start_raw == 'NB 2:30 possible court change'


def test_a_morning_clock_that_follows_the_order_stays_morning():
    ms = [_m('C1', '10:00 AM', 'Starting at 10:00 AM'),
          _m('C1', '11:30', 'Not before 11:30')]
    settle_meridiems(ms)
    assert _times(ms) == ['10:00 AM', '11:30 AM']


def test_a_clock_below_the_courts_evening_start_is_evening():
    ms = [_m('C1', '6:00 PM', 'Starting at 6:00 PM'),
          _m('C1', '9:00', 'Not before 9:00')]
    settle_meridiems(ms)
    assert _times(ms) == ['6:00 PM', '9:00 PM']


def test_noon_and_a_courts_first_clock():
    ms = [_m('C1', '10:00', 'Starting at 10:00'),
          _m('C2', '7:00', 'Starting at 7:00'),
          _m('C3', '12:30', 'Starting at 12:30'),
          _m('C4', '1:00 PM', 'Starting at 1:00 PM')]
    settle_meridiems(ms)
    # No match starts at 7 in the morning; 10 in the morning is ordinary.
    assert _times(ms) == ['10:00 AM', '7:00 PM', '12:30 PM', '1:00 PM']


def test_courts_do_not_share_an_order():
    ms = [_m('C1', '7:00 PM', 'Starting at 7:00 PM'),
          _m('C2', '11:00', 'Starting at 11:00')]
    settle_meridiems(ms)
    assert _times(ms) == ['7:00 PM', '11:00 AM']


def test_a_24_hour_sheet_is_left_alone():
    """No clock on the sheet says AM or PM, so none of them is missing one."""
    ms = [_m('CENTRE COURT', '11:00', 'Starts At 11:00'),
          _m('CENTRE COURT', '14:30', 'Not Before 14:30'),
          _m('COURT 2', '10:00', 'Starts At 10:00'),
          _m('COURT 2', '9:30', 'Starts At 9:30')]
    settle_meridiems(ms)
    assert _times(ms) == ['11:00', '14:30', '10:00', '9:30']


def test_a_24_hour_clock_on_a_12_hour_sheet_keeps_its_hour():
    ms = [_m('C1', '11:00 AM', 'Starting at 11:00 AM'),
          _m('C1', '14:30', 'Not before 14:30')]
    settle_meridiems(ms)
    assert _times(ms) == ['11:00 AM', '14:30']


def _row(court, order, clock):
    return SimpleNamespace(court=court, court_order=order, id=order,
                           start_time_local=clock, play_date=date(2026, 9, 17))


def test_the_law_convicts_the_stored_rows_and_acquits_the_fix():
    tz = 'America/Sao_Paulo'
    stored = [_row('Q1', 1, '11:00 AM'), _row('Q1', 2, '12:00 PM'),
              _row('Q1', 3, '2:30'), _row('Q1', 4, None)]
    bad = clock_runs_backwards(stored, tz)
    assert [(r.court_order, prev.court_order) for r, prev in bad] == [(3, 2)]
    stored[2].start_time_local = '2:30 PM'
    assert clock_runs_backwards(stored, tz) == []


def test_the_law_reads_courts_apart_and_in_court_order():
    tz = 'America/Sao_Paulo'
    rows = [_row('Q2', 2, '2:30 PM'), _row('Q1', 1, '6:00 PM'),
            _row('Q2', 1, '12:00 PM'), _row('Q1', 2, None),
            _row('Q1', 3, '7:00 PM')]
    assert clock_runs_backwards(rows, tz) == []


def test_document_275_parses_to_afternoon_floors():
    if not PDF_275.exists():
        return
    from app.services.oop_parser import parse_pdf
    matches, _meta = parse_pdf(PDF_275.read_bytes())
    nb = [m.time for m in matches if (m.start_raw or '').startswith('NB 2:30')]
    assert nb == ['2:30 PM', '2:30 PM']
    assert all(m.time is None or m.time.endswith(('AM', 'PM')) for m in matches)


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
