"""When a replaced side counts as gone from the sheet — `_superseded`.

Singapore 2026-09-23, COURT 1. Krejcikova withdrew, so the alternates
Friedsam/Sasnovich took over her doubles R16 against Routliffe/Sutjiadi. The
supersede was refused because the guard asked whether each departing PLAYER
was still printed anywhere on the latest revision, and Chwalinska was — in her
own singles, earlier the same day. The dead pairing stayed on COURT 1 as a
third box on a two-match court and chained a "~4:55 PM" onto it.

A doubles team is replaced as a TEAM. The guard now reads the departure at
both levels: the side must not be printed as a side on the latest revision,
AND at least one of its players must be gone from it altogether. For singles a
side is one player and both readings collapse to the original test.

    .venv/bin/python tests/test_superseded_team.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.schedule import _side_tokens, _superseded    # noqa: E402


class P:
    def __init__(self, raw_name, side, position):
        self.raw_name, self.side, self.position = raw_name, side, position


class Row:
    """A stored slot, as much of one as the rule reads."""

    def __init__(self, a, b, doc, stage="main", match_id=None):
        self.players = ([P(n, "a", i) for i, n in enumerate(a)]
                        + [P(n, "b", i) for i, n in enumerate(b)])
        self.last_document_id, self.stage, self.match_id = doc, stage, match_id
        self.is_tbd, self.tbd_side = False, None


def sheet(*rows):
    """The latest revision's sides and the flat pool of names in them — the
    two readings `_dedupe_day` builds and hands to the rule."""
    sides = [_side_tokens(r, s) for r in rows for s in ("a", "b")]
    return [t for side in sides for t in side], sides


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    return cond


def main():
    ok = True

    # The incident. Document 451's COURT 1 doubles against the same opponents
    # document 458 now gives to the alternates.
    old = Row(["Maja CHWALINSKA POL", "Barbora KREJCIKOVA CZE"],
              ["Erin ROUTLIFFE NZL", "Aldila SUTJIADI INA"], 451)
    new = Row(["[ALT] Anna-Lena FRIEDSAM GER", "Aliaksandra SASNOVICH"],
              ["Erin ROUTLIFFE NZL", "Aldila SUTJIADI INA"], 458)
    # Chwalinska IS on the new sheet — she plays her singles at 1:00 PM — and
    # Krejcikova, who withdrew, is nowhere on it.
    singles = Row(["Oleksandra OLIYNYKOVA UKR"], ["[5] Maja CHWALINSKA POL"], 458)
    pool, sides = sheet(new, singles)
    ok &= check("a doubles team replaced by alternates is superseded",
                _superseded(old, new, pool, sides) is True)

    # The look-alike the guard exists for: a rain backlog where the same team
    # has two matches on the day and the finished one drops off the sheet. The
    # team is still printed as a side, so nothing is superseded.
    again = Row(["Maja CHWALINSKA POL", "Barbora KREJCIKOVA CZE"],
                ["Someone ELSE FRA", "Another PERSON GER"], 458)
    pool2, sides2 = sheet(new, singles, again)
    ok &= check("a team still printed as a side is not superseded",
                _superseded(old, new, pool2, sides2) is False)

    # Both partners still on the sheet, split across two other teams: a
    # re-pairing, not a withdrawal. The side is gone but nobody has left.
    split_a = Row(["Maja CHWALINSKA POL", "New PARTNER USA"],
                  ["X ONE FRA", "Y TWO GER"], 458)
    split_b = Row(["Barbora KREJCIKOVA CZE", "Other PARTNER ESP"],
                  ["X THREE FRA", "Y FOUR GER"], 458)
    pool3, sides3 = sheet(new, split_a, split_b)
    ok &= check("a team whose players are all still printed is not superseded",
                _superseded(old, new, pool3, sides3) is False)

    # SINGLES is unchanged by all of this — Winston-Salem 2026-08-24, the case
    # the rule was written for. A side of one is one player either way.
    s_old = Row(["Lorenzo SONEGO ITA"], ["Vit KOPRIVA CZE"], 61)
    s_new = Row(["Lorenzo SONEGO ITA"], ["[LL] Pierre-Hugues HERBERT FRA"], 77)
    pool4, sides4 = sheet(s_new)
    ok &= check("a singles withdrawal is still superseded",
                _superseded(s_old, s_new, pool4, sides4) is True)
    still_here = Row(["Vit KOPRIVA CZE"], ["Someone ELSE ARG"], 77)
    pool5, sides5 = sheet(s_new, still_here)
    ok &= check("...and a singles player still on the sheet still is not",
                _superseded(s_old, s_new, pool5, sides5) is False)

    # A side whose names reduce to nothing — a failed text extraction, not a
    # departed player. Stronger evidence than a withdrawal, and neither level
    # of the guard may block it.
    w_old = Row(["R i n k y", "H I JI K A TA"],
                ["Erin ROUTLIFFE NZL", "Aldila SUTJIADI INA"], 451)
    ok &= check("a side naming nobody is superseded by one that names people",
                _superseded(w_old, new, pool, sides) is True)

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def test_superseded_team():
    """Run by the suite. A file with only a main() is collected as zero tests."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
