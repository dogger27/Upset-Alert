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
from app.services.schedule_invariants import (                    # noqa: E402
    player_on_two_courts, rest_slot_ahead_of_its_match,
    rest_slot_without_its_rest)

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


# Document 313 (12:50 PM): the 2:00 PM doubles QF went w/o and left the sheet,
# QUADRA 1's chain ran out at ~3:40 PM, and the rest-worded doubles no longer
# OVERLAPPED the singles it must follow — so it was listed two hours ahead.
EARLY = _row(1299, 'QUADRA 1', 'After suitable rest', 'after_event',
             'estimated', _at(18, 40), 80, DOUBLES.players)


def test_rest_orders_the_match_even_without_an_overlap():
    edges = set()
    one_court_at_a_time([SINGLES, EARLY],
                        {r.id: _span(r) for r in (SINGLES, EARLY)}, edges)
    assert edges == {(1263, 1299)}


def test_rest_waits_for_the_players_earliest_other_match():
    # A partner's evening singles is not what the rest is for.
    early = _row(1, 'CENTRAL', 'Starting at 1:00 PM', 'fixed', 'printed',
                 _at(16), 105, [_p('a', 'Mary STOIANA USA', 5948)],
                 discipline='singles')
    late = _row(2, 'CENTRAL', 'Not before 7:00 PM', 'not_before', 'printed',
                _at(22), 105, [_p('a', 'Vendula VALDMANNOVA CZE', 5932)],
                discipline='singles')
    d = _row(3, 'QUADRA 1', 'After suitable rest', 'after_event', 'estimated',
             _at(18), 80, DOUBLES.players)
    edges = set()
    one_court_at_a_time([early, late, d],
                        {r.id: _span(r) for r in (early, late, d)}, edges)
    assert edges == {(1, 3)}
    assert rest_slot_ahead_of_its_match([early, late, d]) == []


def test_rest_for_a_match_on_its_own_court_is_the_chains():
    own = _row(1, 'QUADRA 1', 'Starting at 11:00 AM', 'fixed', 'printed',
               _at(14), 105, [_p('a', 'Mary STOIANA USA', 5948)],
               discipline='singles')
    d = _row(2, 'QUADRA 1', 'After suitable rest', 'after_event', 'estimated',
             _at(18, 40), 80, DOUBLES.players)
    d.court_order = 2
    edges = set()
    one_court_at_a_time([own, SINGLES, d],
                        {r.id: _span(r) for r in (own, SINGLES, d)}, edges)
    assert (1263, 2) not in edges
    assert rest_slot_ahead_of_its_match([own, SINGLES, d]) == []


def test_rest_after_enough_rest_adds_nothing():
    d = _row(1299, 'QUADRA 1', 'After suitable rest', 'after_event',
             'estimated', SINGLES.expected_start_at + timedelta(minutes=105 + 45),
             80, DOUBLES.players)
    edges = set()
    one_court_at_a_time([SINGLES, d], {r.id: _span(r) for r in (SINGLES, d)}, edges)
    assert edges == set()


def test_law_convicts_a_rest_slot_listed_ahead_of_its_match():
    # player_on_two_courts is blind to it: the windows do not overlap.
    assert player_on_two_courts([SINGLES, EARLY]) == []
    hits = rest_slot_ahead_of_its_match([SINGLES, EARLY])
    assert [(r.id, o.id) for r, o, _ in hits] == [(1299, 1263)]


def test_law_waits_for_nobody_behind_a_walkover():
    wo = _row(1297, 'QUADRA 1', 'After suitable rest - NB 4pm', 'not_before',
              'printed', _at(19), 0,
              [_p('b', 'Kaitlin QUEVEDO ESP', 5929)])
    wo.status, wo.winner_side = 'completed', 'a'
    s = _row(1261, 'QUADRA CENTRAL', 'Starting at 1:00 PM', 'fixed', 'printed',
             _at(16), 105, [_p('b', '[7] Kaitlin QUEVEDO ESP', 5929)],
             discipline='singles')
    assert rest_slot_ahead_of_its_match([s, wo]) == []



# Singapore 2026-09-23 (document 441), UTC: both doubles partners in singles on
# CENTER COURT first. The rest was taken from Chwalinska's match alone (the
# earliest), and the windows never met, so the doubles sat 19 minutes after
# Krejcikova's singles was expected to end.
SG = datetime(2026, 9, 23)
SG_EARLY = _row(1422, 'CENTER COURT', 'Not before 1:00 PM', 'not_before',
                'printed', SG + timedelta(hours=5), 105,
                [_p('b', '[5] Maja CHWALINSKA POL', 5996)], discipline='singles')
SG_LATE = _row(1437, 'CENTER COURT', 'Not before 2:30 PM', 'not_before',
               'estimated', SG + timedelta(hours=6, minutes=54), 105,
               [_p('b', 'Barbora KREJCIKOVA CZE', 5991)], discipline='singles')
SG_DOUBLES = _row(1428, 'COURT 1', 'After suitable rest', 'after_event',
                  'estimated', SG + timedelta(hours=8, minutes=58), 80,
                  [_p('a', 'Maja CHWALINSKA POL', 5996),
                   _p('a', 'Barbora KREJCIKOVA CZE', 5991),
                   _p('b', 'Erin ROUTLIFFE NZL'), _p('b', 'Aldila SUTJIADI INA')])
SG_DAY = [SG_EARLY, SG_LATE, SG_DOUBLES]


def test_rest_is_from_every_match_of_theirs_ahead_of_it():
    edges = set()
    one_court_at_a_time(SG_DAY, {r.id: _span(r) for r in SG_DAY}, edges)
    assert edges == {(1437, 1428)}


def test_law_convicts_a_rest_slot_that_leaves_no_rest():
    # The two older laws were both blind to it.
    assert player_on_two_courts(SG_DAY) == []
    assert rest_slot_ahead_of_its_match(SG_DAY) == []
    hits = rest_slot_without_its_rest(SG_DAY)
    assert [(r.id, o.id) for r, o, _ in hits] == [(1428, 1437)]


def test_law_acquits_the_rest_slot_once_floored():
    rested = _row(1428, 'COURT 1', 'After suitable rest', 'after_event',
                  'estimated', SG_LATE.expected_start_at
                  + timedelta(minutes=105 + 45), 80, SG_DOUBLES.players)
    assert rest_slot_without_its_rest([SG_EARLY, SG_LATE, rested]) == []


def test_law_rests_nobody_from_a_match_after_it():
    # The partner's evening singles again: it starts after the doubles.
    early = _row(1, 'CENTRAL', 'Starting at 1:00 PM', 'fixed', 'printed',
                 _at(16), 105, [_p('a', 'Mary STOIANA USA', 5948)],
                 discipline='singles')
    late = _row(2, 'CENTRAL', 'Not before 7:00 PM', 'not_before', 'printed',
                _at(22), 105, [_p('a', 'Vendula VALDMANNOVA CZE', 5932)],
                discipline='singles')
    d = _row(3, 'QUADRA 1', 'After suitable rest', 'after_event', 'estimated',
             _at(18, 30), 80, DOUBLES.players)
    assert rest_slot_without_its_rest([early, late, d]) == []
    edges = set()
    one_court_at_a_time([early, late, d],
                        {r.id: _span(r) for r in (early, late, d)}, edges)
    assert edges == set()

if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
