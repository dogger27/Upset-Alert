"""The client's model of the server's answer, held to the server.

frontend/src/utils/drawStatus.rehearsal.test.mjs walks a synthetic season and
asserts where every draw lands on every day. It cannot import
`Draw.computed_status` — that is Python — so it MODELS it in four lines:

    if (day > draw.end_date) return 'completed'      // the scrapers stamp it
    if (day > draw.start_date) return 'active'
    if (day >= draw.released_on) return 'open'       // incl. the start date
    return 'upcoming'

A harness whose model of the server is wrong tests a fiction, confidently. This
suite is what stops that: it walks the real property across the same shapes and
asserts it agrees with those four lines. Change `computed_status` and this fails
with the day it diverged, which is the signal to update the model over there.

WRITING IT FOUND THE EIGHT PHANTOM DAYS. Walking the property instead of
reading it showed that the fallback retiring an unupdated draw is
`(today - start_date) > 14 days`, which owes nothing to end_date — so a scrape
that dies after the semi-finals leaves a finished 6-day event reading 'active'
for eight more days. That is now repaired by draw_invariants.finish_decided_draws
and checked by not_completed_after_its_end; the model deliberately assumes a
draw IS stamped, because no client rule could ever repair one that is not.
"""
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.models.tournament import Draw

RELEASE_LEAD_DAYS = 7


def client_model(day: date, start: date, end: date, released_on: date) -> str:
    """The four lines above, in Python. Keep in step with the rehearsal."""
    if day > end:
        return "completed"
    if day > start:
        return "active"
    if day >= released_on:
        return "open"
    return "upcoming"


def scraper_status(day: date, start: date, end: date) -> str:
    """What the scrapers leave in the status column on a healthy draw.

    This is the assumption the model rests on, and draw_invariants'
    finish_decided_draws is what now makes it true even when a scrape dies.
    """
    if day > end:
        return "completed"
    if day >= start:
        return "active"
    return "upcoming"


def draw_for(start: date, end: date, status: str,
             day: date | None = None) -> Draw:
    """The draw as it stood on `day`.

    `draw_released_direct_at` IS THE DAY THE DRAW CAME OUT, so before that day
    it is null — the first version of this fixture stamped it always, and the
    parity test duly reported the property "diverging" on days the draw did not
    yet exist. A fixture that describes a state the database never holds
    produces failures that are nobody's bug.
    """
    released_on = start - timedelta(days=RELEASE_LEAD_DAYS)
    return Draw(
        name="Rehearsal Open", year=start.year, gender="M", draw_size=32,
        num_rounds=5, start_date=start, end_date=end, status=status,
        wiki_page_title="Rehearsal Open",
        draw_released_direct_at=(
            released_on if day is None or day >= released_on else None),
    )


# The shapes the rehearsal's season is built from.
SHAPES = [
    pytest.param(date(2026, 9, 14), 6, id="ordinary-week"),
    pytest.param(date(2026, 9, 14), 7, id="combined-week-womens-half"),
    pytest.param(date(2026, 9, 30), 11, id="eleven-day-1000"),
    pytest.param(date(2026, 10, 12), 14, id="slam-fortnight"),
    pytest.param(date(2026, 9, 21), 5, id="short-week"),
]


@pytest.mark.parametrize("start,length", SHAPES)
def test_the_property_agrees_with_the_clients_model(start, length):
    end = start + timedelta(days=length)
    divergences = []
    for n in range(-RELEASE_LEAD_DAYS - 2, length + 10):
        day = start + timedelta(days=n)
        d = draw_for(start, end, scraper_status(day, start, end), day)
        with patch("app.models.tournament.date") as mdate:
            mdate.today.return_value = day
            actual = d.computed_status
        expected = client_model(day, start, end,
                                start - timedelta(days=RELEASE_LEAD_DAYS))
        if actual != expected:
            divergences.append(f"day {n:+d} ({day}): property {actual!r}, "
                               f"model {expected!r}")
    assert not divergences, (
        "Draw.computed_status no longer matches the model in "
        "frontend/src/utils/drawStatus.rehearsal.test.mjs — update the model "
        "there, then re-run its mutation matrix:\n  " + "\n  ".join(divergences))


def test_the_start_date_reads_open_not_active():
    """The detail the model had wrong until it was walked: until the first ball
    the bracket is still pickable, so day 0 is 'open'."""
    start, end = date(2026, 9, 21), date(2026, 9, 27)
    d = draw_for(start, end, "upcoming", start)
    with patch("app.models.tournament.date") as mdate:
        mdate.today.return_value = start
        assert d.computed_status == "open"


def test_an_unstamped_draw_reads_active_for_eight_days_past_its_final():
    """The fault the repair exists for, pinned so nobody 'fixes' the repair
    believing the property already handles it.

    A 6-day week whose final is on day +6, left at 'active' by a dead scrape:
    the property keeps saying 'active' until 14 days past START.
    """
    start, end = date(2026, 9, 21), date(2026, 9, 27)
    d = draw_for(start, end, "active", end)     # the scraper never finished it
    still_active = []
    for n in range(7, 16):
        day = start + timedelta(days=n)
        with patch("app.models.tournament.date") as mdate:
            mdate.today.return_value = day
            if d.computed_status == "active":
                still_active.append(n)
    assert still_active == [7, 8, 9, 10, 11, 12, 13, 14], still_active
