"""Tennis Explorer's qualifying rounds, read one way on every page."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.te_rounds import normalize_qual_round as n, normalize_rounds  # noqa: E402


def test_numbered_rounds_are_taken_as_stated():
    assert n("Q-1R", "Washington") == "Q1"
    assert n("Q-3R", "US Open") == "Q3"


def test_the_quarter_final_of_qualifying_is_its_last_round():
    # owner's screenshot, 2026-09-24: "Washington · Q QF"
    assert n("Q-QF", "Washington") == "Q2"
    assert n("Q-R8", "Washington") == "Q2"


def test_sizes_by_event():
    assert n("Q-R32", "Tokyo") == "Q1"
    assert n("Q-R16", "Tokyo") == "Q2"
    assert n("Q-R128", "Wimbledon") == "Q1"
    assert n("Q-R32", "US Open") == "Q3"


def test_main_draw_and_unknown_are_untouched():
    assert n("QF", "Washington") == "QF"
    assert n("R16", "Washington") == "R16"
    assert n("Q-XX", "Washington") == "Q-XX"
    assert n(None, None) is None


def test_cached_payloads_are_read_the_same_way():
    d = {"wins_a": 1, "matches": [{"round": "Q-QF", "tournament": "Washington"}, {"round": "SF"}]}
    assert [m["round"] for m in normalize_rounds(d)["matches"]] == ["Q2", "SF"]
