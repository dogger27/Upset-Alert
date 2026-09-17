"""A document does not know a result the instant the result happens.

`pending_side_decided_before_document` convicts a slot that still offers a
choice when the document that last restated it arrived after the choice was
decided. Both of its clocks are OBSERVATIONS: `completed_at` is when our
results feed saw the match end, `fetched_at` is when the poller happened to
download the sheet. Neither is a publication, and the tour does not re-issue
an order of play the moment a match ends — a person does it.

SP Open 2026-09-18, document 284: the Friday sheet printed QUADRA 1's first
doubles quarter-final "[WC] V. BARROS / N. LEME DA SILVA vs J. Mikulskyte /
A. Smith OR V. Strakhova / A. Tikhonova". The feeder was timed at 21:21:45
and we downloaded the sheet at 21:24:51 — three minutes — and the row was
convicted of losing a rendering that sheet never carried.

The sheet's own RELEASED stamp cannot settle it: that is the stamp of the
ORIGINAL release and does not move when the tour amends the sheet in place
(documents 280 and 282 re-timed two slots between them under an identical
stamp). So the gap must clear the coarser of the two clocks — our own
15-minute poll — before it is evidence at all.

The check must still convict document 238's real incident (2026-09-13,
Monterrey: a 44-minute gap, `_dedupe_day` keeping the staler row and deleting
the update), which is the whole reason it exists.

    .venv/bin/python tests/test_reissue_latency.py
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from types import SimpleNamespace                               # noqa: E402

from app.services.schedule_invariants import (                  # noqa: E402
    _REISSUE_LATENCY, document_clocks)


def _convicts(gap_minutes):
    """The gate, stated as the check states it."""
    done = datetime(2026, 9, 17, 21, 21, 45)
    fetched = done + timedelta(minutes=gap_minutes)
    return done + _REISSUE_LATENCY < fetched


def test_the_sp_open_false_conviction_is_acquitted():
    """Document 284: three minutes between the result and our download."""
    assert not _convicts(3.1)


def test_a_sheet_downloaded_the_same_moment_is_acquitted():
    assert not _convicts(0)
    assert not _convicts(5)
    assert not _convicts(15)


def test_document_238s_real_incident_is_still_convicted():
    """44 minutes — the gap that caught `_dedupe_day` keeping a stale row."""
    assert _convicts(44)


def test_a_slot_left_unresolved_for_hours_is_still_convicted():
    assert _convicts(60)
    assert _convicts(600)


def _doc(i, when, sha):
    return SimpleNamespace(id=i, fetched_at=when, sha256=sha)


def test_a_forced_reparse_inherits_the_clock_of_the_fetch_it_rereads():
    """The verification harness clears sha256 and re-ingests the archived PDF
    on every run, so ingest mints a document stamped `now` for bytes we already
    held. 2026-09-18: document 284 fetched 21:24:51, re-parsed as 285 at
    21:52:40 — the same bytes as the sheet still live on wtatennis.com."""
    clocks = document_clocks([
        _doc(284, datetime(2026, 9, 17, 21, 24, 51), 'forced-reparse'),
        _doc(285, datetime(2026, 9, 17, 21, 52, 40), '12fcbc9dff0c'),
    ])
    assert clocks[285] == datetime(2026, 9, 17, 21, 24, 51)
    assert clocks[284] == datetime(2026, 9, 17, 21, 24, 51)


def test_a_chain_of_reparses_carries_the_original_clock():
    first = datetime(2026, 9, 17, 21, 24, 51)
    clocks = document_clocks([
        _doc(284, first, 'forced-reparse'),
        _doc(285, datetime(2026, 9, 17, 21, 52, 40), 'forced-reparse'),
        _doc(286, datetime(2026, 9, 17, 22, 30, 0), 'abc123'),
    ])
    assert clocks[286] == first


def test_an_ordinary_revision_keeps_its_own_clock():
    """A real re-fetch of genuinely new bytes is what the check is FOR."""
    a = datetime(2026, 9, 17, 20, 17, 21)
    b = datetime(2026, 9, 17, 21, 24, 51)
    clocks = document_clocks([_doc(282, a, 'fb445cd86e'), _doc(284, b, '12fcbc9dff')])
    assert clocks == {282: a, 284: b}


def test_the_grace_is_the_poll_interval():
    """scheduler.py registers refresh_order_of_play on interval minutes=15.
    Stated so the two cannot drift apart silently."""
    assert _REISSUE_LATENCY == timedelta(minutes=15)
    scheduler = (Path(__file__).resolve().parents[1]
                 / 'app' / 'services' / 'scheduler.py').read_text()
    job = scheduler.split('id="refresh_order_of_play"')[0][-400:]
    assert 'minutes=15' in job, job[-200:]


def main():
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as ex:
                fails += 1
                print(f"  FAIL {name} {ex}")
    print("PASS" if not fails else "FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
