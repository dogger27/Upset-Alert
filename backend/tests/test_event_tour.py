"""A schedule row's tour when the sheet that wrote it names none.

Korea Open 2026-09-20 (doc 345): the WTA feed wrote the two 11:00 AM Q2 slots
with tour WTA, the PDF wrote the two "Time TBC" slots with NULL — a single-tour
sheet prints no tour. Half the day's cards wore the WTA tag and tint, and the
H2H popup labelled a women's match "Rank (ATP)". The event decides: the linked
draw's gender, else the tournament's only one; never mixed, never a guess on a
combined event.

    PYTHONPATH=. .venv/bin/pytest tests/test_event_tour.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.schedule import event_tour   # noqa: E402

KOREA = [NS(id=146, gender="F")]
ATP_250 = [NS(id=200, gender="M")]
US_OPEN = [NS(id=1, gender="M"), NS(id=2, gender="F")]


def test_single_tour_event_decides_an_unlinked_row():
    # The incident: qualifying singles, no draw link, one women's draw.
    assert event_tour(KOREA, None, "singles") == "WTA"
    assert event_tour(KOREA, None, "doubles") == "WTA"
    assert event_tour(ATP_250, None, "singles") == "ATP"


def test_linked_draw_decides_on_a_combined_event():
    assert event_tour(US_OPEN, 2, "singles") == "WTA"
    assert event_tour(US_OPEN, 1, "singles") == "ATP"


def test_combined_event_unlinked_row_stays_unstated():
    # Doubles on a combined event has no draw link; the host of the file is
    # not evidence (that fallback once stamped men's doubles as WTA).
    assert event_tour(US_OPEN, None, "doubles") is None


def test_mixed_doubles_belongs_to_no_tour():
    assert event_tour(US_OPEN, None, "mixed") is None
    assert event_tour(KOREA, None, "mixed") is None


def test_no_draws_or_no_gender_says_nothing():
    assert event_tour([], None, "singles") is None
    assert event_tour([NS(id=5, gender=None)], None, "singles") is None
