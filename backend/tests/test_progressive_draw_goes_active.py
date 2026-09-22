"""A match-by-match draw joins ACTIVE when play begins, not when picking ends.

Under `pick_lock_mode = 'r1_progressive'` the bracket freezes one match at a
time, and `picks_locked_at` is stamped only once EVERY first-round match has
started. computed_status used that as its bucket rule, so a draw plainly under
way still read Open: 2026 Singapore had TEN of its sixteen first-round matches
already decided and sat in Open, because two of the sixteen had not started
(owner, 2026-09-22).

Every R1 match starting is the last PICK freezing. The first ball is the draw
becoming ACTIVE. They can be a day and a half apart, and the buckets are about
the draw, not about what the buttons allow — so the two facts stop being the
same fact here.

`status` is the observation the bucket now rests on: the results pipeline
stamps "active" off a main-draw match being under way or done, never off the
calendar.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.models.tournament import Draw

START = date(2026, 9, 21)
END = START + timedelta(days=6)
RELEASED = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def draw(**kw) -> Draw:
    """A released draw, mid-week unless the caller says otherwise."""
    base = dict(
        name="Singapore Open", year=2026, gender="F", draw_size=32, num_rounds=5,
        start_date=START, end_date=END, status="active",
        pick_lock_mode="r1_progressive",
        draw_released_direct_at=RELEASED,
        # The first ball, which is also the predicted close on day one.
        closing_time=datetime(2026, 9, 21, 12, 50),
        picks_locked_at=None,
    )
    base.update(kw)
    return Draw(**base)


def at(day: date, d: Draw) -> str:
    with patch("app.models.tournament.date") as dd:
        dd.today.return_value = day
        dd.side_effect = lambda *a, **k: date(*a, **k)
        return d.computed_status


# ── the bug ───────────────────────────────────────────────────────────────

def test_singapores_shape_reads_active_on_day_one():
    """Play under way, ten of sixteen R1 matches decided, two not started —
    so picks_locked_at is still null. This used to read 'open'."""
    assert at(START, draw()) == "active"


def test_and_every_day_after():
    for n in (1, 2, 3):
        assert at(START + timedelta(days=n), draw()) == "active"


# ── what must not change ─────────────────────────────────────────────────

def test_before_play_it_is_still_open():
    """The whole point of the Open bucket: the draw is out and pickable. The
    results pipeline has stamped nothing, because nothing has been played."""
    assert at(START, draw(status="upcoming")) == "open"
    assert at(START - timedelta(days=1), draw(status="upcoming")) == "open"


def test_a_locked_draw_is_active_as_it_always_was():
    """picks_locked_at still means Active — it is now the second route there
    rather than the only one."""
    locked = draw(status="upcoming",
                  picks_locked_at=datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc))
    assert at(START + timedelta(days=1), locked) == "active"


def test_a_completed_progressive_draw_is_not_open():
    assert at(END + timedelta(days=1), draw(status="completed")) == "completed"


def test_an_unreleased_draw_is_upcoming_whatever_its_mode():
    assert at(START - timedelta(days=20),
              draw(status="upcoming", draw_released_direct_at=None)) == "upcoming"


def test_the_classic_mode_is_untouched():
    """A draw_start draw never entered the progressive branch and still does
    not: the same shapes, one field different, same answers."""
    for status, day, want in (("upcoming", START - timedelta(days=1), "open"),
                              ("active", START, "active"),
                              ("active", START + timedelta(days=2), "active")):
        assert at(day, draw(pick_lock_mode="draw_start", status=status)) == want


def test_picking_is_not_what_changed():
    """The bucket moved; the lock did not. A progressive draw that is Active
    with no picks_locked_at is exactly the state the pick rules exist for —
    editable later rounds behind an Active label — so the field this suite
    stopped consulting for the BUCKET must still be null here."""
    d = draw()
    assert at(START, d) == "active"
    assert d.picks_locked_at is None
