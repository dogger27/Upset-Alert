"""A slot the SHEET prints a final score against is not still to come.

Singapore 2026-09-23, doc 468. COURT 1's opener — CASCINO / FENG vs COSTOULAS
/ GIBSON — was printed "7-6(3) 6-1" on the sheet the page's own PDF button
opens, and the page offered it as an upcoming 2:00 PM match all afternoon.

ESPN covers neither doubles nor qualifying, so `winner_side` and
`live_scores_json` are written only where the Sofascore doubles sweep claims
the event. Until it does, the sheet's printed score is the only sighting of
play that exists — which is exactly how `schedule._slot_was_pulled` and
`schedule_invariants.never_played` have always read it. The serve path alone
did not, and its other source, the running order ("a later slot under way
proves the ones above it are over"), can say nothing about the LAST match to
finish on a court that then stands idle. Every court has one of those.

The expensive mistake is the other direction: a sheet prints a match still on
court the same way it prints a finished one ("62 *42 TBF"), and that is what a
rained-off row carried onto the next day looks like. So the reading answers
True only on evidence it can account for character by character.

    .venv/bin/python tests/test_sheet_score_says_finished.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.oop_parser import printed_score_final              # noqa: E402
from app.services.schedule_invariants import _sheet_declared_finished  # noqa: E402
from app.routers.schedule import _status_of                          # noqa: E402


# Every distinct printed score in the stored corpus (43 rows), plus the forms
# a sheet is known to print that none of them happened to contain.
FINISHED = [
    "7-6(3) 6-1",       # doc 468, COURT 1 — the incident
    "6-2 7-6(5)",       # doc 468, CENTER COURT
    "6-0 6-1",
    "6-3 6-2",          # Cincinnati 2026-08-19 doubles
    "6-3 7-5",          # Winston-Salem 2026-08-21 doubles
    "6-2 3-6 6-4",
    "6-4 3-6 10-8",     # a match tiebreak decider
    "6-7(5) 7-6(3) 6-4",
    "6-2, 6-3",
    "6-4 6-2 F",        # F is the ROUND, and the sets already said it
    "6-3 0-0 RET",      # play stopped, the match did not
    "6-1 DEF",
    "w/o",
    "W/O",
]
STILL_OPEN = [
    "16 *00 TBF",       # the five the corpus actually holds …
    "22* TBF",
    "44* TBF",
    "61 57 *22 TBF",
    "63 67(5) 00* TBF",
    "6-2 3-1",          # … and a set still being played, unmarked
    "6-4 6-5",
    "6-4 3-3",
    "6-4",              # one set is not a best-of-three
    "6-2 ABD",          # abandoned says so in the cell
    "3-6 6-4 TBF",
    "",
    None,
]


def _row(printed, **kw):
    """A doubles row: no bracket match, and nothing but the sheet behind it."""
    return SimpleNamespace(printed_score=printed, winner_side=None,
                           live_scores_json=None, status="scheduled",
                           match_id=None, court="COURT 1", court_order=1,
                           **kw)


def _row_columns_only(entry):
    """The serve path as it read a doubles row BEFORE the fix — four lines, so
    held here rather than imported, the way test_court_run_is_per_tournament
    holds the inference it passes a key to."""
    if entry.winner_side:
        return "completed"
    if entry.live_scores_json:
        return "live"
    return entry.status or "scheduled"


def check(label, cond):
    print(("  ok   " if cond else "  FAIL ") + label)
    return cond


def main():
    ok = True

    for s in FINISHED:
        ok &= check(f"the sheet has declared {s!r} over", printed_score_final(s))
    for s in STILL_OPEN:
        ok &= check(f"{s!r} is not a finished match",
                    not printed_score_final(s))

    # THE LAW READS IT SEPARATELY, and must agree on everything seen so far —
    # an alarm sharing its reader's blind spot is not an alarm (Chengdu doc
    # 408). The two are written differently on purpose; this is what says the
    # difference is only in construction.
    for s in FINISHED + STILL_OPEN:
        ok &= check(f"law and parser agree on {s!r}",
                    _sheet_declared_finished(_row(s)) == printed_score_final(s))

    # Best-of-five is a different match: two sets is a lead, not a result.
    ok &= check("a two-set lead in a best-of-five is not final",
                not printed_score_final("6-2 6-3", sets_to_win=3))

    # The incident, and the repair, on the row as it was stored.
    cascino = _row("7-6(3) 6-1")
    ok &= check("COURT 1's printed-final opener is served completed",
                _status_of(cascino, None) == "completed")
    # TEETH: the reading it replaced must still fail here, or the check above
    # has stopped meaning anything.
    ok &= check("the row's own columns would still call it upcoming (the bug)",
                _row_columns_only(cascino) == "scheduled")

    # A CARRIED, RAINED-OFF ROW IS UNTOUCHED. Its partial score is printed the
    # same way, and calling it finished — or live — would strand it out of the
    # "to be completed" branch that owns it.
    ok &= check("a TBF carry is still scheduled",
                _status_of(_row("61 57 *22 TBF"), None) == "scheduled")
    # And a feed that is actually watching still outranks the sheet.
    live = _row("7-6(3) 6-1")
    live.live_scores_json = [["6", "3"], ["4", "2"]]
    ok &= check("a live feed score beats the sheet's snapshot",
                _status_of(live, None) == "live")
    won = _row("6-4 3-3")
    won.winner_side = 1
    ok &= check("the row's own result beats the sheet's snapshot",
                _status_of(won, None) == "completed")

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def test_sheet_score_says_finished():
    """Run by the suite. A file with only a main() is collected as zero tests."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
