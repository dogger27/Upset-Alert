"""
Upset-pick detection.

Mirrors the frontend's BracketView/CombinedView logic (computeDrawRanks +
isUpsetPick, "picks" mode) exactly, so a user's "did they pick at least one
upset" status always agrees with the Upset Alert bell they see in their own
bracket. Round 1 entrants come from the real draw; round 2+ entrants cascade
from the user's own predicted winners (not the DB's actual results), since a
draw can still be open/in-progress when this is evaluated.
"""

from typing import Optional

from app.models.prediction import UserPrediction
from app.models.tournament import DrawEntry, Match


def _compute_draw_ranks(entries: list[DrawEntry]) -> dict[int, int]:
    ranks: dict[int, int] = {}
    seeded = [e for e in entries if e.seed is not None]
    for e in seeded:
        ranks[e.id] = e.seed

    # THE SEEDING WEEK, for both halves of the scale. `ranking` is the ENTRY
    # week — the cutoff that decided who got in — and ordering the unseeded by
    # it put them on a ranking a fortnight older than the seeds were drawn
    # from. Fifteen of Guadalajara's field moved between those two weeks, and
    # eight of its twenty unseeded would have taken a different badge.
    # Falls back to `ranking` for draws scraped before seed_week_ranking
    # existed, then to bracket position for a player TE never matched.
    def sort_key(e: DrawEntry):
        r = e.seed_week_ranking if e.seed_week_ranking is not None else e.ranking
        if r is not None:
            return (0, r)
        return (1, e.bracket_position)

    unseeded = sorted((e for e in entries if e.seed is None), key=sort_key)
    offset = max((e.seed for e in seeded), default=0)
    for i, e in enumerate(unseeded):
        ranks[e.id] = offset + i + 1
    return ranks


def _resolve_match_entrants(
    matches: list[Match], picks: dict[int, int]
) -> dict[int, tuple[Optional[int], Optional[int]]]:
    by_key = {(m.round_number, m.match_number): m for m in matches}
    resolved: dict[int, tuple[Optional[int], Optional[int]]] = {}

    def get_winner(m: Optional[Match]) -> Optional[int]:
        if m is None:
            return None
        if m.is_bye:
            return m.player1_id
        return picks.get(m.id)

    def resolve(m: Match) -> tuple[Optional[int], Optional[int]]:
        if m.id in resolved:
            return resolved[m.id]
        p1 = m.player1_id if m.round_number == 1 else None
        p2 = m.player2_id if m.round_number == 1 else None
        if m.round_number > 1:
            f1 = by_key.get((m.round_number - 1, m.match_number * 2 - 1))
            f2 = by_key.get((m.round_number - 1, m.match_number * 2))
            if f1 is not None:
                resolve(f1)
            if f2 is not None:
                resolve(f2)
            if p1 is None:
                p1 = get_winner(f1)
            if p2 is None:
                p2 = get_winner(f2)
        resolved[m.id] = (p1, p2)
        return resolved[m.id]

    for m in matches:
        resolve(m)
    return resolved


def has_upset_pick(
    predictions: list[UserPrediction],
    matches: list[Match],
    entries: list[DrawEntry],
) -> bool:
    """True if any prediction picks the lower-ranked entrant to win."""
    picks = {
        p.match_id: p.predicted_winner_id
        for p in predictions
        if p.predicted_winner_id is not None
    }
    if not picks:
        return False
    ranks = _compute_draw_ranks(entries)
    entrants = _resolve_match_entrants(matches, picks)
    for match_id, predicted_winner_id in picks.items():
        p1, p2 = entrants.get(match_id, (None, None))
        if p1 is None or p2 is None:
            continue
        rank1 = ranks.get(p1, float("inf"))
        rank2 = ranks.get(p2, float("inf"))
        expected_winner_id = p1 if rank1 <= rank2 else p2
        if predicted_winner_id != expected_winner_id:
            return True
    return False
