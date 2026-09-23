"""Which dropped slot may be DELETED — `schedule._slot_was_pulled`.

Every order-of-play sheet restates the whole day, so a slot the newest
revision does not print was dropped by it. Two things look identical
afterwards and only one may be deleted:

* SP Open 2026-09-14 — the 2:05 PM revision moved the day's start to 3:30 PM
  and took the doubles R16 off QUADRA CENTRAL. The row stayed, so the site
  printed a match nobody was going to play AND pushed the two slots behind it
  down the court's chain: a printed "Not before 5:30 PM" rendered "~7:15 PM".
* Cincinnati 2026-08-19 — the 7:43 PM revision simply stopped listing four
  slots from the morning sheet. Two were finished singles; two were doubles,
  which ESPN never covered, so they carry no result anywhere and look exactly
  like a pull. Deleting those erases a real match.

The discriminator is the clock: a court whose first printed start on the new
sheet was still ahead when that sheet was published cannot have played
anything yet. The cases below are those real rows, with the instants they
actually carry in the database.

    .venv/bin/python tests/test_pulled_slot.py
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.schedule import _slot_was_pulled                # noqa: E402


class Row:
    """A stored slot, as much of one as the rule reads."""

    def __init__(self, **kw):
        for field in ("started_at", "completed_at", "winner_side",
                      "live_scores_json", "scores_json", "printed_score",
                      "printed_status"):
            setattr(self, field, kw.pop(field, None))
        self.status = kw.pop("status", "scheduled")
        self.match_id = kw.pop("match_id", None)
        assert not kw, f"unknown field(s): {sorted(kw)}"


def at(text):
    return datetime.fromisoformat(text)


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    return cond


def main():
    ok = True

    # SP Open, QUADRA CENTRAL. Document 254 published 17:08 UTC; the court's
    # first printed start on that sheet is 3:30 PM São Paulo = 18:30 UTC.
    sp_published, sp_anchor = at("2026-09-14 17:08:51"), at("2026-09-14 18:30")
    ok &= check(
        "the pulled doubles row is deleted",
        _slot_was_pulled(Row(), sp_anchor, sp_published, False) is True)

    # Cincinnati. Document 2 published 19:43 UTC, TONY TRABERT's first printed
    # start 2:00 PM New York = 18:00 UTC — the court had been playing for an
    # hour and three quarters, so a missing slot may be one that FINISHED.
    cin_published, cin_anchor = at("2026-08-19 19:43:41"), at("2026-08-19 18:00")
    ok &= check(
        "a doubles row dropped by a mid-session reissue is kept",
        _slot_was_pulled(Row(), cin_anchor, cin_published, False) is False)
    ok &= check(
        "...and so is one on a court starting the same minute",
        _slot_was_pulled(Row(), cin_published, cin_published, False) is False)

    # The play tests, each of which alone disqualifies a row. The last two are
    # the only sighting of play a doubles or qualifying slot ever gets, and the
    # match one is how a SINGLES row carries its result — on `matches`, not
    # here, which is why the row above looks untouched.
    ok &= check("a linked match that was played is kept",
                _slot_was_pulled(Row(), sp_anchor, sp_published, True) is False)
    for field, value in (("started_at", at("2026-09-14 18:35")),
                         ("completed_at", at("2026-09-14 20:00")),
                         ("winner_side", "a"),
                         ("live_scores_json", [[6, 4, None, None]]),
                         ("scores_json", [[6], [4]]),
                         ("printed_score", "6-4 6-2"),
                         ("printed_status", "Completed")):
        ok &= check(f"a row carrying {field} is kept",
                    _slot_was_pulled(Row(**{field: value}), sp_anchor,
                                     sp_published, False) is False)
    for status in ("live", "completed"):
        ok &= check(f"a row at status={status} is kept",
                    _slot_was_pulled(Row(status=status), sp_anchor,
                                     sp_published, False) is False)

    # SP Open 2026-09-15. Document 263 published 20:58 UTC, mid-session: every
    # court began 10:30 AM São Paulo = 13:30 UTC, so the clock cannot answer.
    # Rain had stopped Lys/Ce (started 16:09) on QUADRA CENTRAL and the sheet
    # cut Lamens/Alves from behind it — a singles row whose bracket match never
    # started, on a court the feed was watching.
    tue_published, tue_anchor = at("2026-09-15 20:58:24"), at("2026-09-15 13:30")
    ok &= check(
        "a mid-session pull of an unplayed bracket match is deleted",
        _slot_was_pulled(Row(match_id=5351), tue_anchor, tue_published, False,
                         court_in_play=True) is True)
    ok &= check(
        "...but not when nothing on the court was in play at publication",
        _slot_was_pulled(Row(match_id=5351), tue_anchor, tue_published, False,
                         court_in_play=False) is False)
    ok &= check(
        "...nor when its bracket match had been played",
        _slot_was_pulled(Row(match_id=5351), tue_anchor, tue_published, True,
                         court_in_play=True) is False)
    # Cincinnati's dropped doubles have no bracket match: nothing can prove
    # them unplayed mid-session, however live the court was.
    ok &= check(
        "a mid-session doubles row with no bracket match is kept",
        _slot_was_pulled(Row(), cin_anchor, cin_published, False,
                         court_in_play=True) is False)

    # No clock to reason from — a court printed entirely as "Followed by", or
    # a tournament whose draws carry no venue timezone. Silence is not proof.
    ok &= check("no printed anchor on the court means no deletion",
                _slot_was_pulled(Row(), None, sp_published, False) is False)
    ok &= check("no publication time means no deletion",
                _slot_was_pulled(Row(), sp_anchor, None, False) is False)

    # Singapore 2026-09-23. Document 458 published 06:36 UTC; CENTER COURT's
    # first printed start is 11:00 AM Singapore = 03:00 UTC, so the clock is
    # mute, and nothing was on court, so the mid-session proof is mute too.
    # The court's 1:00 PM match (5438) finished 06:09 and the next the sheet
    # prints there is "Not before 2:40 PM" = 06:40 — empty, watched, not yet
    # due — while the dropped row, Mertens vs Krejcikova, is printed "Not
    # before 2:30 PM" = 06:30, inside that stretch, bracket match never begun.
    sg_published, sg_anchor = at("2026-09-23 06:36:09"), at("2026-09-23 03:00")
    sg_idle, sg_row = at("2026-09-23 06:09:18"), at("2026-09-23 06:30")
    ok &= check(
        "a pull on a court standing empty between matches is deleted",
        _slot_was_pulled(Row(match_id=5437), sg_anchor, sg_published, False,
                         court_idle_since=sg_idle, row_start=sg_row) is True)
    ok &= check(
        "...but not a row whose own start is BEFORE the court fell idle",
        _slot_was_pulled(Row(match_id=5437), sg_anchor, sg_published, False,
                         court_idle_since=sg_idle,
                         row_start=at("2026-09-23 05:00")) is False)
    ok &= check(
        "...nor a row with no printed clock of its own",
        _slot_was_pulled(Row(match_id=5437), sg_anchor, sg_published, False,
                         court_idle_since=sg_idle, row_start=None) is False)
    ok &= check(
        "...nor a doubles row, which has no bracket match to be blank",
        _slot_was_pulled(Row(), sg_anchor, sg_published, False,
                         court_idle_since=sg_idle, row_start=sg_row) is False)
    ok &= check(
        "...nor when its bracket match had been played",
        _slot_was_pulled(Row(match_id=5437), sg_anchor, sg_published, True,
                         court_idle_since=sg_idle, row_start=sg_row) is False)
    # The caller sets `court_idle_since` only for a court standing empty with
    # its next printed match still to come. Unset is every other state,
    # Cincinnati's included — a court playing since 2:00 PM may well have
    # finished the slot that went missing.
    ok &= check(
        "a court not proven idle is left alone",
        _slot_was_pulled(Row(match_id=5437), cin_anchor, cin_published, False,
                         court_idle_since=None, row_start=sg_row) is False)

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def test_pulled_slot():
    """Run by the suite. A file with only a main() is collected as zero tests."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
