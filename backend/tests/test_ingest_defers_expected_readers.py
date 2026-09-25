"""A law that reads expected_start_at cannot be judged at ingest time.

`ingest_document` runs `check_and_log` at its end, but only
`recompute_expected_starts` writes `expected_start_at` — and the caller runs it
in the NEXT statement. So a row the sheet has just created is still NULL there.

2026-09-25, Korea Open doc 549: the QF Joint had begun on 9/25 was carried to
9/26 "Starting at 11:00 AM". The row was inserted at 08:09:54.999 and
`carried_slot_has_no_time` fired 0.5 s later ("no expected_start_at"); the
estimate (02:00 UTC = 11:00 KST) was written a moment after. The code was not
in INGEST_DEFERRED, so the law judged a column nobody had written yet.

This pins the whole class: every check in `check_day` whose own code reads
`expected_start_at` must be in INGEST_DEFERRED, so the next such law cannot
repeat it.
"""
import inspect
import re

from app.services import schedule_invariants as si


def _flag_regions(src: str):
    """(code, source from the end of the previous flag() call to the end of
    this one) for every flag("code", ...) in `src`, comments stripped."""
    src = "\n".join(line.split("#", 1)[0] for line in src.split("\n"))
    prev = 0
    for m in re.finditer(r'flag\(\s*"(\w+)"', src):
        depth, i = 0, m.start() + len("flag")
        while True:
            depth += {"(": 1, ")": -1}.get(src[i], 0)
            i += 1
            if depth == 0:
                break
        yield m.group(1), src[prev:i]
        prev = i


def test_every_expected_reader_is_ingest_deferred():
    readers = {code for code, region in
               _flag_regions(inspect.getsource(si.check_day))
               if "expected_start_at" in region}
    # The scan must actually see the laws it protects, or it proves nothing.
    assert {"carried_slot_has_no_time", "untimed_slot_served_first",
            "expected_contradicts_printed"} <= readers
    assert readers <= si.INGEST_DEFERRED, sorted(readers - si.INGEST_DEFERRED)
