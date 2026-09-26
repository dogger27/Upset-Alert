"""Korea Open 2026-09-26: the WTA feed held Saturday, said nothing of Sunday,
and Sofascore was refusing us — so the PDF, which already carried Sunday's
final, was never fetched and the missing-schedule alert fired (system_logs
5139). A day the feeds did not state, today or tomorrow, is the sheet's."""
from datetime import date
from types import SimpleNamespace

from app.services.order_of_play import _days_the_sheet_owes, _pdf_fallback_note

SAT, SUN, MON = date(2026, 9, 26), date(2026, 9, 27), date(2026, 9, 28)


def _draw(start=date(2026, 9, 21), end=SUN):
    return SimpleNamespace(start_date=start, end_date=end, variant=None)


def test_tomorrow_the_feeds_have_not_listed_is_owed_to_the_sheet():
    assert _days_the_sheet_owes(SAT, [_draw()], {SAT: {}}) == [SUN]


def test_a_day_the_feeds_hold_stays_theirs():
    assert _days_the_sheet_owes(SAT, [_draw()], {SAT: {}, SUN: {}}) == []


def test_a_day_past_the_draw_is_owed_nothing():
    # The final's evening: Monday belongs to no running draw.
    assert _days_the_sheet_owes(SUN, [_draw()], {SUN: {}}) == []
    assert _days_the_sheet_owes(SAT, [_draw(end=SAT)], {SAT: {}}) == []


def test_the_day_ahead_sheet_filling_an_unlisted_day_is_a_note():
    t = SimpleNamespace(id=49, name="Korea Open")
    level, msg, key = _pdf_fallback_note(
        t, SUN, {}, {}, {}, {}, {SUN: "the feeds have not listed the day yet"})
    assert (level, key) == ("info", "pdf_unstated_49")
    assert "no feed had a schedule" not in msg
    # Another day unstated says nothing about this one.
    assert _pdf_fallback_note(t, SUN, {}, {}, {}, {}, {MON: "x"})[0] == "warning"
