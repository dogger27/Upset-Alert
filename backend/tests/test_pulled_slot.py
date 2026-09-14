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

    # No clock to reason from — a court printed entirely as "Followed by", or
    # a tournament whose draws carry no venue timezone. Silence is not proof.
    ok &= check("no printed anchor on the court means no deletion",
                _slot_was_pulled(Row(), None, sp_published, False) is False)
    ok &= check("no publication time means no deletion",
                _slot_was_pulled(Row(), sp_anchor, None, False) is False)

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def test_pulled_slot():
    """Run by the suite. A file with only a main() is collected as zero tests."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
