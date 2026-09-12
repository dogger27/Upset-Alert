"""The badge's scale: the seeds, then everyone else behind them — all of it
from the OFFICIAL SEEDING WEEK.

`draw_entries.ranking` is the ENTRY week (the direct-acceptance cutoff, and
the answer to "what was this player's ranking in this tournament?" — the
owner's ruling, feedback_entry_ranking_week_for_inferred). The seeds are drawn
from a week two later for a tour event, four for a Slam. Ordering the unseeded
by `ranking` therefore built one scale out of two moments: at Guadalajara 2026
fifteen of the twenty-five players moved between the two weeks and eight of the
twenty unseeded would have taken a different badge.

This is asserted on the server because the server's upset check has to agree
with the badge the reader sees — and that rule now has one copy per surface
(services/upsets.py, frontend/src/utils/drawRanks.js, mobile/drawRanks.js),
where it used to have four.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.upsets import _compute_draw_ranks          # noqa: E402


def entry(eid, *, seed=None, ranking=None, seed_week_ranking=None, pos=1):
    return SimpleNamespace(id=eid, seed=seed, ranking=ranking,
                           seed_week_ranking=seed_week_ranking, bracket_position=pos)


def test_the_seeding_week_orders_the_unseeded():
    """Guadalajara's real inversion: Parks FELL 71 -> 89 while Arango ROSE
    97 -> 84 between the entry week and the seeding week, so the pair swaps —
    Parks led on the old scale, Arango leads on the one the seeds came from."""
    field = [
        entry(1, seed=1, ranking=11),
        entry(2, seed=2, ranking=16),
        entry(10, ranking=71, seed_week_ranking=89, pos=21),    # Parks
        entry(11, ranking=97, seed_week_ranking=84, pos=12),    # Arango
    ]
    ranks = _compute_draw_ranks(field)
    assert ranks[1] == 1 and ranks[2] == 2                      # seeds untouched
    assert ranks[11] == 3, "Arango leads on the seeding week"
    assert ranks[10] == 4
    # And the point of the whole change: the ENTRY week would have said the
    # opposite, which is the badge readers were being shown.
    entry_only = [entry(1, seed=1, ranking=11), entry(2, seed=2, ranking=16),
                  entry(10, ranking=71, pos=21), entry(11, ranking=97, pos=12)]
    old_ranks = _compute_draw_ranks(entry_only)
    assert old_ranks[10] == 3 and old_ranks[11] == 4


def test_it_falls_back_to_the_entry_week_then_to_the_bracket():
    """Draws scraped before the column existed hold nulls, and a player TE
    never matched holds no ranking at all — neither may reorder the field
    arbitrarily or crash the badge."""
    field = [
        entry(1, seed=1, ranking=5),
        entry(20, ranking=40, pos=9),          # old row: entry week only
        entry(21, ranking=60, pos=3),
        entry(22, pos=7),                      # unmatched: no ranking at all
        entry(23, pos=2),
    ]
    ranks = _compute_draw_ranks(field)
    assert ranks[20] == 2 and ranks[21] == 3   # ranked ones first, in order
    # The unranked pair keep the draw's own order, which is stable.
    assert ranks[23] == 4 and ranks[22] == 5


def test_a_mixture_prefers_the_seeding_week_per_player():
    """One backfilled player beside one that is not: each is read on its own
    best available week rather than the whole field falling back together."""
    field = [
        entry(1, seed=1, ranking=5),
        entry(30, ranking=50, seed_week_ranking=95, pos=5),
        entry(31, ranking=60, pos=6),          # no seeding-week figure
    ]
    ranks = _compute_draw_ranks(field)
    # 60 (entry week, the only figure it has) beats 95 (seeding week).
    assert ranks[31] == 2 and ranks[30] == 3


def test_the_offset_is_the_highest_seed_not_the_count():
    """A withdrawn seed leaves a gap rather than colliding two players."""
    field = [entry(1, seed=1), entry(2, seed=4), entry(9, seed_week_ranking=80, pos=1)]
    ranks = _compute_draw_ranks(field)
    assert ranks[9] == 5
