"""A singles walkover is written on the bracket, and the clock law reads it there.

Singapore 2026-09-23, CENTER COURT. Mertens v Krejcikova went w/o; match 5437
said `[["w/o"], [""]]` and the schedule row, as a main-draw singles row always
does, said nothing. The WTA feed rightly dropped the walkover's stamp, the row
kept the sheet's "Not before 2:30 PM" and sorted untimed-last, as #6 under
the court's 19:56 finale — and `printed_clock_runs_backwards` read only the
row, so it convicted a match that never took the court.
"""
from types import SimpleNamespace

from app.services.schedule_invariants import _walked_over, clock_runs_backwards

TZ = "Asia/Singapore"


def _row(rid, order, clock, start_type="fixed", match_id=None):
    return SimpleNamespace(
        id=rid, court="CENTER COURT", court_order=order, start_time_local=clock,
        start_note=clock, start_type=start_type, play_date=None,
        printed_score=None, scores_json=None, match_id=match_id)


def _day():
    from datetime import date
    rows = [_row(1421, 1, "10:48"), _row(1422, 2, "12:48", match_id=5438),
            _row(1427, 3, "14:36"), _row(1424, 4, "18:20"),
            _row(1425, 5, "19:56"),
            _row(1437, 6, "2:30 PM", "not_before", match_id=5437)]
    for r in rows:
        r.play_date = date(2026, 9, 23)
    return rows


def test_row_only_reading_convicts_the_walkover():
    # The shape that was logged: the row alone cannot know.
    assert [(e.id, p.id) for e, p in clock_runs_backwards(_day(), TZ)] == [(1437, 1425)]


def test_the_bracket_walkover_is_not_convicted():
    wo = {5437}
    got = clock_runs_backwards(
        _day(), TZ, walked_over=lambda r: _walked_over(r) or r.match_id in wo)
    assert got == []


def test_a_played_bracket_match_is_still_judged():
    # Only the walkover is excused — a played singles out of order is not.
    wo = {5438}
    got = clock_runs_backwards(
        _day(), TZ, walked_over=lambda r: _walked_over(r) or r.match_id in wo)
    assert [(e.id, p.id) for e, p in got] == [(1437, 1425)]
