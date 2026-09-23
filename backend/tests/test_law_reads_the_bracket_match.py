"""A singles row's result lives on `matches`, and the law must read it there.

Korea Open, 2026-09-23. Back v Joint (entry 1401, CENTER COURT, "Not before
2:00 PM") finished at 06:12 UTC — match 5407 carried the winner and the
completion time, and the schedule row carried, as a main-draw singles row
always does, nothing at all: status `scheduled`, every result column empty.

`schedule.recompute_expected_starts` reads the linked match, so it freed
CENTER COURT at 06:12 and floored Joint's "After suitable rest" doubles on
GRANDSTAND from there. `rest_slot_without_its_rest` read the ROW, called the
finished singles a match still to come, invented its end as printed start +
102 minutes = 06:42, and convicted the doubles at "~7:22" for not leaving 45
minutes after a moment that never happened.

Doubles and qualifying rows DO carry their own state — nothing else ever sees
them — which is why the row-only reading looked right for a season.

    .venv/bin/python tests/test_law_reads_the_bracket_match.py
"""
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.schedule_invariants import (                    # noqa: E402
    _row_played, player_on_two_courts, rest_slot_ahead_of_its_match,
    rest_slot_without_its_rest)


def _at(h, m=0):
    return datetime(2026, 9, 23, h, m)


def _p(side, name, eid=None, position=0):
    return SimpleNamespace(side=side, raw_name=name, draw_entry_id=eid,
                           position=position)


def _row(rid, court, note, start, dur, players, discipline='doubles',
         start_type='after_event', source='estimated', match_id=None):
    return SimpleNamespace(
        id=rid, court=court, court_order=4, start_note=note,
        start_type=start_type, expected_source=source, expected_start_at=start,
        estimated_duration_min=dur, discipline=discipline, players=players,
        is_tbd=False, tbd_side=None, started_at=None, completed_at=None,
        winner_side=None, live_scores_json=None, status='scheduled',
        match_id=match_id)


# The Korea day as the sweep found it at 06:40 UTC, to the minute.
SINGLES = _row(1401, 'CENTER COURT', 'Not before 2:00 PM', _at(5), 102,
               [_p('a', '[WC] Dayeon BACK KOR', 5966),
                _p('b', '[5] Maya JOINT AUS', 5968)],
               discipline='singles', start_type='not_before', source='printed',
               match_id=5407)
DOUBLES = _row(1407, 'GRANDSTAND', 'After suitable rest', _at(7, 22), 80,
               [_p('a', 'Ya Hsin LEE TPE'), _p('a', 'Qiu Yu YE CHN', position=1),
                _p('b', '[2] Maya JOINT AUS', 5968),
                _p('b', 'Elena-Gabriela RUSE ROU', 5976, position=1)])

# Match 5407 finished at 06:12; the row it belongs to says nothing about it,
# which is what `check_day`'s `never_played` joins and `_row_played` cannot.
PLAYED = {1401}


def joined(r):
    return _row_played(r) or r.id in PLAYED


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    return cond


def main():
    ok = True
    day = [SINGLES, DOUBLES]

    ok &= check(
        "the row-only reading convicts the Korea day as it was",
        [(r.id, o.id) for r, o, _ in
         rest_slot_without_its_rest(day, played=_row_played)] == [(1407, 1401)])
    ok &= check(
        "reading the bracket match too, a finished singles is not waited for",
        rest_slot_without_its_rest(day, played=joined) == [])

    # The whole class: the other two laws take the same predicate and were
    # blind in the same way. A finished singles is not a player on two courts,
    # and it is not a match a rest slot can be printed ahead of.
    clash = _row(1410, 'GRANDSTAND', 'Followed by', _at(5, 30), 80,
                 [_p('b', '[2] Maya JOINT AUS', 5968)],
                 start_type='followed_by')
    ok &= check("row-only: a finished singles still books a player",
                len(player_on_two_courts([SINGLES, clash],
                                         played=_row_played)) == 1)
    ok &= check("joined: it does not",
                player_on_two_courts([SINGLES, clash], played=joined) == [])

    early = _row(1411, 'GRANDSTAND', 'After suitable rest', _at(4), 80,
                 [_p('b', '[2] Maya JOINT AUS', 5968)], match_id=5407)
    ok &= check("row-only: a rest row over a finished match is convicted",
                len(rest_slot_ahead_of_its_match([SINGLES, early],
                                                 played=_row_played)) == 1)
    ok &= check("joined: a rest row whose own match has been played is exempt",
                rest_slot_ahead_of_its_match(
                    [SINGLES, early],
                    played=lambda r: _row_played(r) or r.match_id == 5407) == [])

    # The default stays the row's own columns, for a caller with no database:
    # tests/test_one_court_at_a_time.py judges these same functions without
    # one, and must go on meaning what it meant.
    ok &= check("the default predicate is the row-only reading",
                [(r.id, o.id) for r, o, _ in rest_slot_without_its_rest(day)]
                == [(1407, 1401)])

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def test_law_reads_the_bracket_match():
    """Run by the suite. A file with only a main() is collected as zero tests."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
