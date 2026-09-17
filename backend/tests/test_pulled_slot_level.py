"""A pulled slot is news, not an alarm — unless the parser may have pulled it.

Four times in two days the self-healing watcher was woken by "N slot(s)
pulled from …", investigated, and correctly changed nothing: rain reissues,
a withdrawal, a supervisor pulling a doubles. Each wake costs money and the
line was a warning only to cover the one case that looks the same from the
outside — the parser losing a box the sheet still prints. `check_parse`
already sees that case (`vs_lines_exceed_matches`), so the level follows it:
info when the parse was clean, warning when it was not (owner, 2026-09-17).
"""
import re
from pathlib import Path

from app.services.alerts import ALERT_LEVELS
from app.services.schedule import _pull_level

SRC = Path(__file__).resolve().parents[1] / "app" / "services" / "schedule.py"

LOST_BOX = [{"code": "vs_lines_exceed_matches", "entry_id": None, "court": None,
             "detail": "the sheet prints 9 match boxes, the parse produced 8: 1 slot(s) lost"}]


def test_a_clean_parse_makes_the_pull_the_tours_and_the_line_info():
    assert _pull_level([]) == "info"
    assert _pull_level(None) == "info"


def test_a_lost_box_keeps_the_warning():
    assert _pull_level(LOST_BOX) == "warning"


def test_info_reaches_neither_the_digest_nor_the_watcher():
    # The digest emails these levels and the watcher wakes on the same two;
    # a clean pull must be neither.
    assert "info" not in ALERT_LEVELS
    assert set(ALERT_LEVELS) == {"error", "warning"}


def test_every_pulled_slot_line_uses_the_rule():
    """Read the source: both places that write "slot(s) pulled" must take
    their level from _pull_level, or one reissue of one sheet is a warning
    again and nothing else in the suite notices."""
    src = SRC.read_text()
    calls = [m.start() for m in re.finditer(r'slot\(s\) pulled from', src)]
    assert len(calls) == 2, "expected the blank-sheet site and the tail site"
    for at in calls:
        window = src[max(0, at - 400):at]
        assert "_pull_level(parse_violations)" in window, src[at - 200:at + 80]
        assert '"warning", "order_of_play"' not in window
