"""A merge's survivor is placed by the NEWER document.

Hangzhou 2026-09-23 (doc 418): the Sofascore feed wrote the day first as "Taro
Daniel vs Hayato Matsuoka", "Court 1", "Est. 12:00"; the sheet then took the
day back printing "[4] Taro DANIEL JPN vs Arthur WEBER FRA or [6] Hayato
MATSUOKA JPN" on COURT 1 #1, "Starts At 12:00". `_dedupe_day` kept the more
settled feed row — right — with all of the feed's placement — wrong: COURT 1
rendered as two courts.
"""
from types import SimpleNamespace as NS

from app.services.schedule import _take_placement
from app.services.schedule_invariants import (court_spelled_two_ways,
                                              sheet_row_placed_by_feed)


def _p(side, pos, name, nat=None):
    return NS(side=side, position=pos, raw_name=name, nationality=nat,
              draw_entry_id=None)


def _feed_row():
    return NS(id=1415, court="Court 1", court_order=1, stage="qualifying",
              tour="ATP", round_label="Q", printed_score=None,
              start_type="estimated", start_time_local="12:00",
              start_note="Est. 12:00", last_document_id=414,
              started_at=None, completed_at=None, winner_side=None,
              players=[_p("a", 1, "Taro Daniel", "JPN"),
                       _p("b", 1, "Hayato Matsuoka", "JPN")])


def _sheet_row():
    return NS(id=1417, court="COURT 1", court_order=1, stage="qualifying",
              tour="ATP", round_label="Q", printed_score=None,
              start_type="fixed", start_time_local="12:00",
              start_note="Starts At 12:00", last_document_id=418,
              started_at=None, completed_at=None, winner_side=None,
              players=[_p("a", 1, "[4] Taro DANIEL JPN", "JPN"),
                       _p("b", 1, "Arthur WEBER FRA", "FRA"),
                       _p("b", 2, "[6] Hayato MATSUOKA JPN", "JPN")])


def test_the_survivor_takes_the_sheets_placement_and_spelling():
    keep, drop = _feed_row(), _sheet_row()
    _take_placement(keep, drop)
    assert (keep.court, keep.court_order) == ("COURT 1", 1)
    assert (keep.start_type, keep.start_time_local, keep.start_note) == (
        "fixed", "12:00", "Starts At 12:00")
    # Who is in it stays the survivor's (the feed knew the result); only the
    # spelling of those same people moves.
    assert [p.raw_name for p in keep.players] == [
        "[4] Taro DANIEL JPN", "[6] Hayato MATSUOKA JPN"]


def test_a_box_with_no_wording_keeps_the_survivors_start():
    keep, drop = _feed_row(), _sheet_row()
    keep.start_type, keep.start_time_local, keep.start_note = (
        "fixed", "11:00", "Starts At 11:00")
    drop.start_type, drop.start_time_local, drop.start_note = "tba", None, None
    _take_placement(keep, drop)
    assert keep.start_note == "Starts At 11:00" and keep.start_time_local == "11:00"


def test_an_ambiguous_person_is_not_respelled():
    keep, drop = _feed_row(), _sheet_row()
    drop.players.append(_p("b", 3, "Taro DANIEL JPN"))
    _take_placement(keep, drop)
    assert keep.players[0].raw_name == "Taro Daniel"


def test_the_law_sees_the_unmerged_placement():
    feed_row = _feed_row()
    feed_row.last_document_id = 418         # restated by the sheet, via the merge
    opener = NS(id=1418, court="COURT 1", court_order=1)
    second = NS(id=1419, court="COURT 1", court_order=2)
    center = NS(id=1397, court="CENTER COURT", court_order=1)
    hits = court_spelled_two_ways([feed_row, opener, second, center])
    assert [(r.id, other) for r, other in hits] == [(1415, "COURT 1")]
    assert court_spelled_two_ways([opener, second, center]) == []
    # Restated by sheet doc 418, still the feed's estimate.
    assert sheet_row_placed_by_feed([feed_row], feed_docs={414}) == [feed_row]
    # The feed's own document owning it is the feed's rendering, by design.
    feed_row.last_document_id = 414
    assert sheet_row_placed_by_feed([feed_row], feed_docs={414}) == []
    # A played box drops its time band on the sheet and keeps what it had.
    feed_row.last_document_id, feed_row.winner_side = 418, "a"
    assert sheet_row_placed_by_feed([feed_row], feed_docs={414}) == []
