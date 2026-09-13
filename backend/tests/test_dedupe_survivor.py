"""Which of two rows for one slot survives `_dedupe_day`.

SP Open 2026-09-13, QUADRA CENTRAL slot 2. Document 237 printed
"W. Osuigwe OR F. Labrana vs M. Urrutia OR A. Tikhonova". Document 238,
published after Osuigwe had won her Q1, printed "[4] Whitney OSUIGWE USA"
against the still-open pair. `_resolves` correctly saw one slot; the survivor
choice then kept 237's row, because settledness was read as a BOOLEAN and the
tie-break went to whichever row named more players — which an unresolved side
always does. The sheet's own update was deleted.

    .venv/bin/python tests/test_dedupe_survivor.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.schedule import (                        # noqa: E402
    _open_sides, _prefer_challenger, _wreckage,
)


class P:
    """A stored player row, as much of one as the rule reads."""

    def __init__(self, raw_name, side="a"):
        self.raw_name = raw_name
        self.side = side


class Row:
    """Only what the rule reads: how open the row is, and its player rows.

    `players` may be a COUNT — the shape most of these cases care about, where
    every row names an ordinary person — or the names themselves when what is
    on trial is whether they are names at all.
    """

    def __init__(self, is_tbd, tbd_side, players):
        self.is_tbd = is_tbd
        self.tbd_side = tbd_side
        self.players = ([P(f"Firstname SURNAME{i} ESP") for i in range(players)]
                        if isinstance(players, int) else list(players))


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    return cond


def main():
    ok = True

    ok &= check("a settled row has no open sides", _open_sides(Row(False, None, 2)) == 0)
    ok &= check("one open side counts 1", _open_sides(Row(True, "b", 3)) == 1)
    ok &= check("both open count 2", _open_sides(Row(True, "ab", 4)) == 2)
    # is_tbd with no side recorded is read as both, the way every other reader
    # of tbd_side in schedule.py reads it.
    ok &= check("tbd with no side recorded counts 2", _open_sides(Row(True, None, 4)) == 2)

    # THE INCIDENT. doc 237: both sides open, four names. doc 238: side a
    # settled, three names. The newer, more-settled row must win even though
    # it names fewer people.
    d237 = Row(True, "ab", 4)
    d238 = Row(True, "b", 3)
    ok &= check("half-settled challenger beats the fully open row",
                _prefer_challenger(d238, d237) is True)
    ok &= check("...and the fully open row does not beat it",
                _prefer_challenger(d237, d238) is False)

    # The rule the old code got right, unchanged: a settled row beats an
    # unresolved one whichever sheet confirmed it last.
    ok &= check("settled beats unresolved",
                _prefer_challenger(Row(False, None, 2), Row(True, "ab", 4)) is True)
    ok &= check("unresolved never beats settled",
                _prefer_challenger(Row(True, "ab", 4), Row(False, None, 2)) is False)

    # The reason the player count exists at all: two rows settled to the SAME
    # degree, one of which lost a player to a parser bug (a doubles team of
    # one — Winston-Salem 2026-08-24). The fuller row still wins there.
    ok &= check("equally settled: the fuller row wins",
                _prefer_challenger(Row(False, None, 4), Row(False, None, 3)) is True)
    ok &= check("equally settled: the emptier row loses",
                _prefer_challenger(Row(False, None, 3), Row(False, None, 4)) is False)
    ok &= check("equally open: the fuller row wins",
                _prefer_challenger(Row(True, "b", 3), Row(True, "b", 2)) is True)

    # A tie in both is not a preference: the incumbent stays, so a merge can
    # never oscillate between two equal rows on successive sweeps.
    ok &= check("a dead tie keeps the incumbent",
                _prefer_challenger(Row(True, "b", 3), Row(True, "b", 3)) is False)

    # SAO PAULO 2026-09-14. The stored row read "[Q/LL] Qualifier/LL" as three
    # players on a side it never declared open; the corrected parse read it as
    # one open seat. The wreck wins BOTH older tests — it calls itself settled
    # and it names more people — so the fix could not reach the page until the
    # survivor rule stopped taking a shredded row's word for itself.
    wreck = Row(False, None, [P("[Q"), P("LL] Qualifier"), P("LL"),
                              P("[3] Solana SIERRA ARG", "b")])
    fixed = Row(True, "a", [P("[Q/LL] Qualifier/LL"),
                            P("[3] Solana SIERRA ARG", "b")])
    ok &= check("the shredded row is counted as wreckage", _wreckage(wreck) == 3)
    ok &= check("a declared-open seat is not wreckage", _wreckage(fixed) == 0)
    ok &= check("the corrected row beats the wreck it replaces",
                _prefer_challenger(fixed, wreck) is True)
    ok &= check("...and the wreck does not beat it",
                _prefer_challenger(wreck, fixed) is False)
    # The exemption that keeps this off ordinary rows: an unresolved side is
    # ALLOWED to name a role, because that is what the sheet printed there.
    ok &= check("an open seat on an undeclared side is the fault, not the seat",
                _wreckage(Row(False, None, [P("Qualifier")])) == 1)

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def test_dedupe_survivor():
    """Run by the suite. A file with only a main() is collected as zero tests."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
