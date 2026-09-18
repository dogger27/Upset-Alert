"""A player is on one court at a time — `schedule.one_court_at_a_time`.

SP Open's Friday sheet (2026-09-18, document 289) printed Stoiana's doubles QF
third on QUADRA 1, "After suitable rest", and her singles QF on CENTRAL "Not
before 5:30 PM". The estimate chain runs down each court alone, so QUADRA 1's
ran out at 5:29 PM and the page said "~5:30 PM" for the doubles — listed ABOVE
the singles she would be playing at that moment.

The law's check (`player_on_two_courts`) must convict the day as it was and
acquit it once the doubles waits for the singles.

    .venv/bin/python tests/test_one_court_at_a_time.py
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.schedule import one_court_at_a_time            # noqa: E402
from app.services.schedule_invariants import player_on_two_courts  # noqa: E402

T = datetime(2026, 9, 18)


def _at(h, m=0):
    return T + timedelta(hours=h, minutes=m)


def _p(side, name, eid=None):
    return SimpleNamespace(side=side, raw_name=name, draw_entry_id=eid)


def _row(rid, court, note, start_type, source, start, dur, players,
         discipline='doubles', is_tbd=False, tbd_side=None):
    return SimpleNamespace(
        id=rid, court=court, court_order=1, start_note=note,
        start_type=start_type, expected_source=source,
        expected_start_at=start, estimated_duration_min=dur,
        discipline=discipline, players=players, is_tbd=is_tbd,
        tbd_side=tbd_side, started_at=None, completed_at=None,
        winner_side=None, live_scores_json=None, status='scheduled')


def _span(r, movable=True):
    return (r.expected_start_at,
            r.expected_start_at + timedelta(minutes=r.estimated_duration_min),
            movable)


# The day as document 289 left it (UTC).
SINGLES = _row(1263, 'QUADRA CENTRAL', 'Not before 5:30 PM', 'not_before',
               'printed', _at(20, 30), 105,
               [_p('a', 'Mary STOIANA USA', 5948),
                _p('b', '[2] Paula BADOSA ESP', 5894)], discipline='singles')
DOUBLES = _row(1274, 'QUADRA 1', 'After suitable rest', 'after_event',
               'estimated', _at(20, 29), 80,
               [_p('a', 'Mary STOIANA USA', 5948),
                _p('a', 'Vendula VALDMANNOVA CZE', 5932),
                _p('b', 'Yiming DANG CHN'), _p('b', 'Xiaodi YOU CHN', 5936)])


def test_the_rest_worded_match_waits_for_the_other():
    edges = set()
    one_court_at_a_time([SINGLES, DOUBLES],
                        {r.id: _span(r) for r in (SINGLES, DOUBLES)}, edges)
    assert edges == {(1263, 1274)}


def test_rest_wording_outranks_which_starts_first():
    # The doubles' own chain had it a minute EARLIER than the singles — start
    # order alone would have pushed the singles behind it.
    assert DOUBLES.expected_start_at < SINGLES.expected_start_at
    edges = set()
    one_court_at_a_time([DOUBLES, SINGLES],
                        {r.id: _span(r) for r in (SINGLES, DOUBLES)}, edges)
    assert edges == {(1263, 1274)}


def test_a_match_on_court_is_never_the_one_that_moves():
    edges = set()
    one_court_at_a_time([SINGLES, DOUBLES],
                        {1263: _span(SINGLES), 1274: _span(DOUBLES, False)}, edges)
    assert edges == {(1274, 1263)}


def test_no_overlap_no_edge():
    # Quevedo the same day: singles 1:00 PM, doubles "After suitable rest -
    # NB 4pm" — the sheet already left her room.
    s = _row(1, 'QUADRA CENTRAL', 'Starting at 1:00 PM', 'fixed', 'printed',
             _at(16), 105, [_p('b', '[7] Kaitlin QUEVEDO ESP', 5929)],
             discipline='singles')
    d = _row(2, 'QUADRA 1', 'After suitable rest - NB 4pm', 'not_before',
             'printed', _at(19), 80, [_p('b', 'Kaitlin QUEVEDO ESP', 5929)])
    edges = set()
    one_court_at_a_time([s, d], {r.id: _span(r) for r in (s, d)}, edges)
    assert edges == set()


def test_same_person_found_by_name_alone():
    # A doubles partner with no singles entry has no draw_entry_id anywhere.
    s = _row(1, 'A', 'Not before 5:30 PM', 'not_before', 'printed', _at(20, 30),
             105, [_p('a', 'Yiming DANG CHN')], discipline='singles')
    d = _row(2, 'B', 'Followed by', 'followed_by', 'estimated', _at(20), 80,
             [_p('b', 'Yiming DANG CHN')])
    edges = set()
    one_court_at_a_time([s, d], {r.id: _span(r) for r in (s, d)}, edges)
    # Neither says rest: the one the chain had starting later waits.
    assert edges == {(2, 1)}


def test_an_open_side_books_nobody():
    s = _row(1, 'A', 'Not before 5:30 PM', 'not_before', 'printed', _at(20, 30),
             105, [_p('a', 'Mary STOIANA USA', 5948)], discipline='singles')
    d = _row(2, 'B', 'After suitable rest', 'after_event', 'estimated',
             _at(20, 29), 80,
             [_p('a', 'Mary STOIANA USA', 5948), _p('a', 'Anna BONDAR HUN')],
             is_tbd=True, tbd_side='a')
    edges = set()
    one_court_at_a_time([s, d], {r.id: _span(r) for r in (s, d)}, edges)
    assert edges == set()
    assert player_on_two_courts([s, d]) == []


def test_two_fixed_starts_are_the_sheets_own():
    s = _row(1, 'A', 'Starting at 5:00 PM', 'fixed', 'printed', _at(20),
             105, [_p('a', 'Mary STOIANA USA')], discipline='singles')
    d = _row(2, 'B', 'Starting at 5:30 PM', 'fixed', 'printed', _at(20, 30),
             80, [_p('a', 'Mary STOIANA USA')])
    edges = set()
    one_court_at_a_time([s, d], {r.id: _span(r, False) for r in (s, d)}, edges)
    assert edges == set()
    assert player_on_two_courts([s, d]) == []


def test_law_convicts_the_day_as_it_was():
    hits = player_on_two_courts([SINGLES, DOUBLES])
    assert [(a.id, b.id) for a, b, _ in hits] == [(1263, 1274)]


def test_law_acquits_the_doubles_after_rest():
    after = _row(1274, 'QUADRA 1', 'After suitable rest', 'after_event',
                 'estimated', SINGLES.expected_start_at
                 + timedelta(minutes=105 + 45), 80, DOUBLES.players)
    assert player_on_two_courts([SINGLES, after]) == []


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
