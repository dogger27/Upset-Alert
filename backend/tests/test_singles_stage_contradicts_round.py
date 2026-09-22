"""A singles row's stage and round name the same draw.

Hangzhou 2026-09-23 (doc 421): the Court view ranked COURT 1 (qualifying finals
only) above CENTER COURT, which carried the day's two unseeded main-draw R32s
and which the sheet prints first. Courts are now ranked by stage before seed,
so a row filed in the wrong draw would misorder them — and wear the wrong badge.
"""
from types import SimpleNamespace as NS

from app.services.schedule_invariants import singles_stage_contradicts_round


def _row(id, stage, round_label, discipline="singles"):
    return NS(id=id, stage=stage, round_label=round_label, discipline=discipline)


def test_hangzhou_rows_agree():
    rows = [_row(1397, "qualifying", "Q"), _row(1416, "qualifying", "Q"),
            _row(1398, "main", "R32"), _row(1399, "main", "R32")]
    assert singles_stage_contradicts_round(rows) == []


def test_a_qualifying_round_filed_main_is_flagged():
    bad = _row(1, "main", "Q2")
    assert singles_stage_contradicts_round([bad]) == [bad]


def test_a_main_round_filed_qualifying_is_flagged():
    # "QF" starts with Q and is not a qualifying round.
    bad = [_row(1, "qualifying", "R32"), _row(2, "qualifying", "QF")]
    assert singles_stage_contradicts_round(bad) == bad


def test_no_round_and_doubles_are_left_alone():
    rows = [_row(1, "qualifying", None), _row(2, "main", " "),
            _row(3, "main", "Q1", discipline="doubles")]
    assert singles_stage_contradicts_round(rows) == []
