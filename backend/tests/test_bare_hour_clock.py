"""A clock printed as a BARE HOUR — "NB 4pm".

SP Open's Friday sheet (2026-09-18, document 284) printed QUADRA 1's second
doubles quarter-final "After suitable rest - NB 4pm". Every clock reader in
the ingest demanded minutes (`\\d{1,2}[:.]\\d{2}`), so the hour was a time to
none of them: `_slot_of` found no clock, `schedule._start_type_of` saw an "NB"
with nothing in front of it and fell through to the "after" branch — a type
the estimate chain gives no floor — and the page printed "~3:30 PM" under a
printed 4:00. One occurrence in the 335-file corpus.

The meridiem is mandatory without minutes: a lone 1-2 digit number on an order
of play is a seed, a court, a round or a set score far more often than a time.

The ratchet is `printed_clock_not_captured`, which sits UPSTREAM of the three
floor checks. `expected_undercuts_printed_floor`, `printed_clock_runs_backwards`
and `not_before_wording_misread` all begin at `start_time_local`, so a clock
the parser never recognised disarms every one of them at once — the law has to
be able to ask whether the SHEET stated a time the row does not have.

    .venv/bin/python tests/test_bare_hour_clock.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.oop_parser import (BARE_TIME_RE, CLOCK_RE, Match,   # noqa: E402
                                     _canonical_clock, _slot_of)
from app.services.schedule import _parse_clock, _start_type_of        # noqa: E402
from app.services.schedule_invariants import (                        # noqa: E402
    printed_clock_not_captured)

PDF_284 = Path('/home/paulwiens/upsetalert/data/oop_pdfs/284.pdf')


def test_a_bare_hour_is_a_clock():
    assert CLOCK_RE.findall('After suitable rest - NB 4pm') == ['4pm']
    assert CLOCK_RE.findall('Not before 4 PM') == ['4 PM']
    assert BARE_TIME_RE.match('4pm')
    assert BARE_TIME_RE.match('11 AM')


def test_a_lone_number_is_not_a_clock():
    """The meridiem is what makes the hour unambiguous. Without it a sheet is
    full of numbers that are not times."""
    assert CLOCK_RE.findall('30 mins after ceremony') == []
    assert CLOCK_RE.findall('Followed by R16') == []
    assert CLOCK_RE.findall('[4] Anna BLINKOVA FRA') == []
    assert not BARE_TIME_RE.match('4')


def test_a_clock_with_minutes_is_unchanged():
    assert CLOCK_RE.findall('Not before 3:00 PM') == ['3:00 PM']
    assert CLOCK_RE.findall('Starts At 14:30') == ['14:30']
    assert CLOCK_RE.findall('Not Before 2.30pm') == ['2.30pm']


def test_the_hour_is_canonicalised_where_the_clock_is_read():
    """`start_time_local` keeps one shape, so the five readers downstream of
    the parse never learn a second one."""
    assert _canonical_clock('4pm') == '4:00 PM'
    assert _canonical_clock('11 a.m.') == '11:00 AM'
    assert _canonical_clock('2:30 PM') == '2:30 PM'
    assert _canonical_clock('14:30') == '14:30'
    assert _slot_of('After suitable rest - NB 4pm')[0] == '4:00 PM'
    # And it parses, which is the whole point — every floor starts here.
    assert _parse_clock(_canonical_clock('4pm')).hour == 16


def test_the_wording_is_read_as_a_floor():
    """"NB" counts in front of a clock, and a bare hour is a clock. Read as
    `after_event` the slot carries no floor at all."""
    assert _start_type_of(Match(start_raw='After suitable rest - NB 4pm',
                                time='4:00 PM')) == 'not_before'
    assert _start_type_of(Match(start_raw='NB 3:30 PM - After suitable rest',
                                time='3:30 PM')) == 'not_before'
    # A stray "NB" with no clock behind it still may not invent a floor.
    assert _start_type_of(Match(start_raw='After suitable rest',
                                time=None)) == 'after_event'
    assert _start_type_of(Match(start_raw='NB possible court change',
                                time=None)) == 'tba'


def _row(note, clock, court='QUADRA 1', order=2):
    return SimpleNamespace(court=court, court_order=order, start_note=note,
                           start_time_local=clock)


def test_the_law_convicts_the_stored_row_and_acquits_the_fix():
    stored = _row('After suitable rest - NB 4pm', None)
    assert printed_clock_not_captured([stored]) == [(stored, '4pm')]
    stored.start_time_local = '4:00 PM'
    assert printed_clock_not_captured([stored]) == []


def test_the_law_leaves_a_note_that_states_no_clock_alone():
    rows = [_row('Followed by', None),
            _row('After suitable rest', None),
            _row('30 mins after ceremony', None),
            _row(None, None),
            # TBA says outright there is no clock. Cincinnati prints "Not
            # Before 3:00 PM" with "TBA" on the line below.
            _row('AFTER REST, TIME TBA', None),
            _row('To be arranged', None)]
    assert printed_clock_not_captured(rows) == []


def test_document_284_stores_the_printed_floor():
    if not PDF_284.exists():
        return
    from app.services.oop_parser import parse_pdf
    matches, _meta = parse_pdf(PDF_284.read_bytes())
    nb = [m for m in matches if 'NB 4pm' in (m.start_raw or '')]
    assert len(nb) == 1, [m.start_raw for m in matches]
    assert nb[0].time == '4:00 PM'
    assert nb[0].start_raw == 'After suitable rest - NB 4pm'   # never rewritten
    assert _start_type_of(nb[0]) == 'not_before'


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
