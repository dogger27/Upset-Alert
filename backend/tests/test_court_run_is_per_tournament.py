"""A court's running order belongs to ONE tournament, not to every court of
that name.

Singapore 2026-09-23, doc 463. COURT 1's opener — CASCINO / FENG vs COSTOULAS
/ GIBSON, printed "Not before 2:00 PM" — was served COMPLETED. Nothing about
it had finished: no winner, no score, no linked match, and the sheet released
at 2:35 PM printed no result beside it.

`/schedule/day` fills in the status the feeds cannot give it (ESPN covers
neither doubles nor qualifying) from the running order: a slot under way
proves the slots above it on that court are over. That is a fact about a
court — one tournament's court. The groups were keyed on the court NAME
alone, and the day spans every tournament playing unless the caller narrows
it, so Chengdu's and Hangzhou's live second matches on THEIR "COURT 1"
declared Singapore's first one finished. That afternoon three tournaments
were running a "COURT 1" and four a "CENTER COURT" — generic names are the
rule, not the exception.

The web page passes `tournament_id` and so never saw it; the iOS app and the
all-tournaments view fetch the whole day and did.

    .venv/bin/python tests/test_court_run_is_per_tournament.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers.schedule import court_run_key                    # noqa: E402


def _row(rid, tid, court, order, status="scheduled"):
    return SimpleNamespace(id=rid, tournament_id=tid, court=court,
                           court_order=order, status=status)


# The day as it stood at 07:24 UTC, court by court, with the status each row
# had BEFORE the running-order inference ran (the two live rows are Chengdu's
# and Hangzhou's own second matches; Singapore's two were simply unplayed).
SINGAPORE = 82
DAY = [
    _row(1433, 61, "COURT 1", 1, "completed"),   # Chengdu
    _row(1434, 61, "COURT 1", 2, "live"),
    _row(1415, 62, "COURT 1", 1, "completed"),   # Hangzhou
    _row(1431, 62, "COURT 1", 2, "live"),
    _row(1426, SINGAPORE, "COURT 1", 1),         # CASCINO / FENG vs COSTOULAS / GIBSON
    _row(1438, SINGAPORE, "COURT 1", 2),         # FRIEDSAM / SASNOVICH, printed "TBA"
]


def infer(rows, key):
    """The day endpoint's inference, over whatever key it is given.

    Held here rather than imported because the loop is four lines inside the
    endpoint; what the endpoint owns, and what this passes in, is the KEY.
    """
    statuses = {r.id: r.status for r in rows}
    groups = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    for slots in groups.values():
        highest = None
        for r in sorted(slots, key=lambda x: x.court_order):
            if statuses[r.id] in ("live", "completed"):
                highest = r.court_order
        if highest is None:
            continue
        for r in slots:
            if r.court_order < highest and statuses[r.id] == "scheduled":
                statuses[r.id] = "completed"
    return statuses


def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    return bool(cond)


def main():
    ok = True

    ok &= check("the key names the tournament as well as the court",
                court_run_key(DAY[0]) != court_run_key(DAY[4]))
    ok &= check("two courts of one tournament stay apart",
                court_run_key(_row(1, SINGAPORE, "COURT 1", 1))
                != court_run_key(_row(2, SINGAPORE, "CENTER COURT", 1)))
    ok &= check("a row with no court still groups under its own tournament",
                court_run_key(_row(3, SINGAPORE, None, 1)) == (SINGAPORE, ""))

    # The defect, and the repair, on the same day.
    ok &= check("Singapore's COURT 1 opener is not declared finished by "
                "another venue's COURT 1",
                infer(DAY, court_run_key)[1426] == "scheduled")

    # TEETH: the key is the whole fix, so the old one must still fail here.
    # If this ever passes, the name-only key is back and the check above has
    # stopped meaning anything.
    ok &= check("the name-only key would still convict it (the bug, pinned)",
                infer(DAY, lambda r: r.court or '')[1426] == "completed")

    # And the inference itself is untouched WITHIN a tournament: Chengdu's own
    # live second match still finishes its own first.
    ok &= check("a court's own later slot still proves its earlier ones over",
                infer([_row(9, SINGAPORE, "CENTER COURT", 1),
                       _row(10, SINGAPORE, "CENTER COURT", 2, "live")],
                      court_run_key)[9] == "completed")

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def test_court_run_is_per_tournament():
    """Run by the suite. A file with only a main() is collected as zero tests."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
