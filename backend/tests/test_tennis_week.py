"""Which week a tournament belongs to — the tour's calendar, not the ISO one.

Guadalajara 2026 began Sunday 13 September and SP Open on Monday the 14th.
That is one tour week. Taking "the Monday on or before" gave them weeks 36 and
37, and the draw-release batcher — which waits for every draw in a week and
sends exactly one email — therefore treated them as two weeks and sent two
emails, fourteen hours apart (owner, 2026-09-12).
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.draw_dates import (compute_entry_ranking_week,      # noqa: E402
                                     compute_seed_ranking_week, tournament_monday)
from app.services.scraper import snap_to_monday                        # noqa: E402
from app.services.tournament_sync import tennis_week                   # noqa: E402


def test_a_sunday_start_belongs_to_the_week_ahead():
    """The case that cost two emails."""
    guadalajara, sp_open = date(2026, 9, 13), date(2026, 9, 14)
    assert guadalajara.strftime('%a') == 'Sun' and sp_open.strftime('%a') == 'Mon'
    assert tournament_monday(guadalajara) == date(2026, 9, 14)
    assert tennis_week(guadalajara, 2026) == tennis_week(sp_open, 2026) == 37


def test_an_extended_event_keeps_its_own_monday():
    """Cincinnati 2026 ran Thursday 13 to Sunday 23 August: the week of the
    10th, not the 17th. Rounding a mid-week start FORWARD would move a Masters
    1000 into the week after the one it is played in."""
    assert tournament_monday(date(2026, 8, 13)) == date(2026, 8, 10)
    assert tennis_week(date(2026, 8, 13), 2026) == 32


def test_every_day_of_the_week_lands_somewhere_sane():
    #        Mon  Tue  Wed  Thu | Fri  Sat  Sun
    # back  ← ← ← ←  ← ← ←  ← ← | → →  → →  → → forward
    expected = {
        date(2026, 9, 14): date(2026, 9, 14),   # Mon
        date(2026, 9, 15): date(2026, 9, 14),   # Tue
        date(2026, 9, 16): date(2026, 9, 14),   # Wed
        date(2026, 9, 17): date(2026, 9, 14),   # Thu
        date(2026, 9, 18): date(2026, 9, 21),   # Fri
        date(2026, 9, 19): date(2026, 9, 21),   # Sat
        date(2026, 9, 20): date(2026, 9, 21),   # Sun
    }
    for d, monday in expected.items():
        assert tournament_monday(d) == monday, d.strftime('%a')
        assert monday.weekday() == 0


def test_the_ranking_weeks_count_from_the_same_monday():
    """Guadalajara's stored weeks are Aug 17 (entry) and Aug 31 (seeding),
    which are 28 and 14 days before Monday the 14th — NOT before the 7th. They
    were right by luck of ordering (discovery seeds the Monday, and the
    event-date refresh later corrects the start to the Sunday); now they are
    right by construction."""
    sunday = date(2026, 9, 13)
    assert compute_entry_ranking_week(sunday, 'WTA 500') == date(2026, 8, 17)
    assert compute_seed_ranking_week(sunday, 'WTA 500') == date(2026, 8, 31)


def test_the_season_edges_are_unchanged():
    # Brisbane 2026 starts Saturday 3 January: still week 1.
    assert tennis_week(date(2026, 1, 3), 2026) == 1
    # A December event belonging to the next season still reports 0.
    assert tennis_week(date(2025, 12, 29), 2026) == 0


def test_there_is_one_rule_not_two():
    """snap_to_monday had its own copy of this. The badge-rank bug earlier the
    same day was four copies of one rule; this is two, and one is enough."""
    for d in (date(2026, 9, 13), date(2026, 8, 13), date(2026, 1, 3),
              date(2026, 9, 18), date(2026, 12, 31)):
        assert snap_to_monday(d) == tournament_monday(d)
