"""A set decided by a tiebreak is a set, and a read that loses one is stale.

Two faults found on the same match (Medvedev–Tiafoe, US Open 2026, 6-7 4-6
6-7(8)). A minute after the last point Sofascore still carried period3TieBreak
on a period now reading 7-6, which _sets_and_tiebreak took for a MATCH tiebreak
and popped — so the last stored snapshot claimed two sets and a match tiebreak
at 0-0, and the site's sanitizer erased the whole third set to agree with it.
Separately, one live read in five is a cache node's older copy: at a set
boundary the poller wrote the previous set's last game ten seconds after the
set was over.

    .venv/bin/python tests/test_set_tiebreak_decided.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.sofascore_live import (          # noqa: E402
    _HELD, _hold_once, _lost_a_set, _sets_and_tiebreak,
)

fails = 0


def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails += 1


# The decider as Sofascore reported it a minute after the end.
home = {"period1": 6, "period2": 4, "period3": 6, "period3TieBreak": 6}
away = {"period1": 7, "period2": 6, "period3": 7, "period3TieBreak": 8}
sets, tb, match_tb = _sets_and_tiebreak(home, away)
check("a decided set tiebreak keeps its set", sets == [[6, 7], [4, 6], [6, 7]])
check("  the tiebreak flag stands", tb is True)
check("  and it is not a match tiebreak", match_tb is False)

sets, tb, match_tb = _sets_and_tiebreak(
    {"period1": 6, "period1TieBreak": 3}, {"period1": 6, "period1TieBreak": 5})
check("six-all in play is a set tiebreak", sets == [[6, 6]] and tb and not match_tb)

sets, tb, match_tb = _sets_and_tiebreak(
    {"period1": 6, "period2": 3, "period3": 8, "period3TieBreak": 8},
    {"period1": 4, "period2": 6, "period3": 7, "period3TieBreak": 7})
check("8-7 with points in the period is a match tiebreak", sets == [[6, 4], [3, 6]] and match_tb)

sets, tb, match_tb = _sets_and_tiebreak({"period1": 3}, {"period1": 5})
check("no tiebreak key, no tiebreak", sets == [[3, 5]] and not tb and not match_tb)

# The stale-read hold.
_HELD.clear()
before = {"sets": [[6, 7], [0, 0]], "point": ["0", "0"]}
stale = {"sets": [[6, 6]], "point": ["40", "0"]}
check("a set lost is spotted", _lost_a_set(before, stale))
check("a first sighting never counts as lost", not _lost_a_set({}, stale))
check("the same count is not a loss", not _lost_a_set(before, {"sets": [[6, 7], [1, 0]]}))
check("held on first sight", _hold_once(1, stale) is True)
check("let through when it comes straight back", _hold_once(1, stale) is False)
check("  and forgotten", 1 not in _HELD)
check("a different shrink is held afresh", _hold_once(1, {"sets": [[6, 5]], "point": ["0", "0"]}) is True)
_HELD.clear()

print("---", "FAILED" if fails else "all passed")


def test_set_tiebreak_decided():
    """Named so pytest runs the checks above as one test rather than aborting
    the whole suite: a bare sys.exit at import time is a pytest INTERNALERROR,
    which took the other 108 tests down with it."""
    assert not fails, f"{fails} check(s) failed — run this file directly for the list"


if __name__ == "__main__":
    sys.exit(1 if fails else 0)
