"""When a slot the sheet stopped printing becomes a fault.

SP Open, 2026-09-14: document 253 printed a doubles R16 on QUADRA CENTRAL,
document 254 dropped it, the invariant sweep raised an error — and document
255 retired the row thirteen minutes later, exactly as `_retire_pulled_slots`
is designed to. One revision of silence is the window that fix runs in, so
alarming on it reports the fix working.

Two revisions means nothing restated the slot and nothing retired it either.
"""
from app.services.schedule_invariants import UNCONFIRMED_GRACE, revisions_since

# The day's own sheets, in the order SP Open published them.
DAY = [251, 252, 253, 254, 255]


def test_the_sp_open_window_is_not_a_fault():
    # Where the error actually fired: 254 out, 253 was the last to print it.
    assert revisions_since([251, 252, 253, 254], 253) == 1
    assert revisions_since([251, 252, 253, 254], 253) < UNCONFIRMED_GRACE


def test_two_revisions_of_silence_is_a_fault():
    assert revisions_since(DAY, 253) == 2
    assert revisions_since(DAY, 253) >= UNCONFIRMED_GRACE


def test_a_slot_the_newest_sheet_restated_is_never_counted():
    assert revisions_since(DAY, 255) == 0


def test_ids_are_counted_not_subtracted():
    """Document ids are global. Subtracting them counts other tournaments'
    sheets: 255 - 253 is 2 here only because nothing else was fetched in
    between, and on a busy afternoon the same one-revision gap reads as five.
    """
    busy = [251, 253, 254]           # 252 belonged to another tournament
    assert 254 - 253 == 1
    assert revisions_since(busy, 253) == 1
    # And the reverse: a wide id gap that is still one of THIS day's sheets.
    assert revisions_since([253, 299], 253) == 1
    assert 299 - 253 == 46


def test_no_last_document_counts_every_sheet():
    """A row that never recorded which sheet printed it has been unconfirmed
    by all of them, not none."""
    assert revisions_since(DAY, None) == len(DAY)
