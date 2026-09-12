"""Who is going to win this league draw, as a probability.

Two numbers per bracket, beside the Finish range in the standings: the chance
it finishes first, and the chance it finishes on the podium. Both are EXACT
rather than simulated — the standings already enumerate every future of the
undecided matches to work out the Finish range (see
`scoring.finish_range`), so the only thing missing was a weight for each
future. This module supplies that weight: one probability per match, from
the players actually in it in that future.

    odds = await draw_odds(db, draw, all_matches)
    ranges = await finish_range_async(..., odds=odds)   # (best, worst, p_win, p_podium)

WHY THIS IS NOT A SIMULATION. A Monte Carlo would need tens of thousands of
runs to get the third decimal place of a tail probability, and would give a
slightly different answer on every refresh — a standings column that jitters
while nothing has happened reads as broken. Enumeration is the same cost as
the Finish range it rides along with, and the same answer every time.

THE MODEL is the vendored `winprob` package: Tennis Abstract Elo when both
players have a rating, the fitted rank model otherwise, with best-of-five
handled through set combinatorics. Its coefficients were fitted on twenty-five
years of tour matches; see `winprob/__init__.py` for what it is and is not.

Elo comes from our own weekly table (`te_rankings_snapshots.elo`, refreshed
by `rankings.refresh_elo_ratings`), so nothing here touches the network.

HOW GOOD IS IT? On the 4,213 completed matches in the database as of
2026-09-12: 69.6% accuracy, 0.573 log loss. Without Elo the same model reads
65.0% / 0.620, and simply backing the higher-ranked player gets 65.1% — so
Elo is the whole of the edge and the ranking is worth nothing over the naive
pick. `scripts/winprob_calibration.py` recomputes all of it; its docstring
records the one bias that flatters these numbers.
"""

from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rankings import TeRankingsSnapshot
from app.models.tournament import Draw, DrawEntry
from app.services.winprob import predict

# Bumped whenever anything below changes the number a given draw produces —
# a coefficient, the Elo week, the live-score handling. It rides in the cache
# key so a deploy cannot serve yesterday's arithmetic.
MODEL_VERSION = 1

# HOW OLD A LIVE SET SCORE MAY BE and still be used. Far longer than the 45s
# the point score is allowed, because a set count is a different kind of fact:
# the point moves every twenty seconds, the set score every forty minutes. A
# three-minute-old "two sets to love" is still two sets to love, and ignoring
# it would leave the column claiming a player is favoured while everyone
# watching can see he is being beaten.
LIVE_MAX_AGE = 300.0


class DrawOdds:
    """Per-match win probabilities for one draw. Pure data, no session.

    Built on the event loop (it reads the database), then handed to the
    enumeration, which runs in a worker thread — so nothing here may hold an
    ORM object or a session.
    """

    def __init__(self, ratings: dict, surface: Optional[str], best_of: int,
                 live: dict, cache_key: tuple):
        # entry_id -> (elo or None, world ranking or None)
        self.ratings = ratings
        self.surface = surface or "Hard"
        self.best_of = best_of
        # match_id -> (player1_id, player2_id, sets won by each)
        self.live = live
        self.cache_key = cache_key
        self._memo: dict = {}

    def pair_prob(self, a: int, b: int, match_id: Optional[int] = None) -> float:
        """P(entry `a` beats entry `b`), in `match_id` if that match is live.

        Antisymmetric, and 0.5 for a pair nothing is known about — an unranked
        qualifier against an unranked qualifier is a coin toss, and saying so
        is better than declining to answer, which would blank the column for
        the whole draw.
        """
        key = (a, b, match_id)
        hit = self._memo.get(key)
        if hit is not None:
            return hit
        elo_a, rank_a = self.ratings.get(a, (None, None))
        elo_b, rank_b = self.ratings.get(b, (None, None))
        if (elo_a is None or elo_b is None) and rank_a is None and rank_b is None:
            # predict() refuses this rather than guessing, which is right for a
            # library and wrong for a column: two unrated qualifiers are a coin
            # toss, and one blank pair must not blank the whole draw.
            p = 0.5
        else:
            p = predict(rank_x=rank_a, rank_y=rank_b, elo_x=elo_a, elo_y=elo_b,
                        surface=self.surface, best_of=self.best_of)["p"]
        p = self._live_adjust(p, a, b, match_id)
        self._memo[key] = p
        return p

    def live_override(self, match_id: int) -> Optional[tuple]:
        """(player1, player2, P(player1 wins)) for a match in progress.

        The enumeration builds one pairwise table for the whole tail and then
        asks this for the handful of matches where the table's pre-match answer
        is out of date.
        """
        live = self.live.get(match_id)
        if not live:
            return None
        p1, p2, _ = live
        return (p1, p2, self.pair_prob(p1, p2, match_id))

    def _live_adjust(self, p: float, a: int, b: int, match_id) -> float:
        """Fold the set score of a match in progress into its pre-match odds.

        Only for the two players who are ACTUALLY on court in that match: the
        enumeration asks about hypothetical pairings in later rounds too, and a
        set score belongs to the pair that earned it.
        """
        live = self.live.get(match_id) if match_id is not None else None
        if not live:
            return p
        p1, p2, won = live
        if {a, b} != {p1, p2}:
            return p
        from app.services.winprob import live_win_prob
        sets_a, sets_b = (won[0], won[1]) if a == p1 else (won[1], won[0])
        if sets_a == 0 and sets_b == 0:
            return p
        return live_win_prob(p_match=p, sets_x=sets_a, sets_y=sets_b,
                             best_of=self.best_of)


def best_of(draw: Draw) -> int:
    """Sets to win a match. Stated by the tournament feed where we have it."""
    n = getattr(draw, "sofa_number_of_sets", None)
    if n in (3, 5):
        return n
    # Men's Grand Slam singles is the only best-of-five left on either tour.
    return 5 if (draw.gender == "M" and (draw.category or "").lower().startswith("grand")) else 3


def _live_sets(match) -> Optional[tuple]:
    """Completed sets won by each side of a match in progress, or None.

    Reads through the same two shared helpers every other surface uses, so a
    set is "complete" here exactly when the bracket draws it as complete.
    """
    from app.services.live_activity_content import _sets_won
    from app.services.sofascore_live import renderable_point
    snap = renderable_point(getattr(match, "sofa_live_json", None),
                            getattr(match, "winner_id", None) is not None,
                            max_age=LIVE_MAX_AGE)
    games = (snap or {}).get("games")
    if not games:
        return None
    won = _sets_won(games)
    return tuple(won) if any(won) else None


async def draw_odds(db: AsyncSession, draw: Draw, all_matches: list) -> Optional[DrawOdds]:
    """The odds source for one draw, or None when there is no field to rate."""
    rows = (await db.execute(
        select(DrawEntry.id, DrawEntry.te_player_id, DrawEntry.ranking)
        .where(DrawEntry.draw_id == draw.id))).all()
    if not rows:
        return None

    te_ids = [r.te_player_id for r in rows if r.te_player_id]
    elo_by_te: dict[int, int] = {}
    week: Optional[date] = None
    if te_ids:
        # THE LATEST ELO, not the entry week's. Elo is a statement about form
        # now, which is what a prediction wants; the entry ranking is a
        # statement about who got into the draw, which is what seeding wants.
        # One consequence worth naming: replaying the Finish slider on a draw
        # that finished months ago rates it with today's Elo. Harmless — the
        # only positions where any match is still open are the live ones.
        week = (await db.execute(
            select(TeRankingsSnapshot.week_date)
            .where(TeRankingsSnapshot.elo.isnot(None))
            .order_by(TeRankingsSnapshot.week_date.desc()).limit(1))).scalar_one_or_none()
        if week is not None:
            for pid, elo in (await db.execute(
                    select(TeRankingsSnapshot.player_id, TeRankingsSnapshot.elo)
                    .where(TeRankingsSnapshot.player_id.in_(te_ids),
                           TeRankingsSnapshot.week_date == week,
                           TeRankingsSnapshot.elo.isnot(None)))).all():
                elo_by_te[pid] = elo

    ratings = {r.id: (elo_by_te.get(r.te_player_id) if r.te_player_id else None, r.ranking)
               for r in rows}
    live = {}
    for m in all_matches:
        if m.winner_id is not None or m.is_bye or not m.player1_id or not m.player2_id:
            continue
        won = _live_sets(m)
        if won:
            live[m.id] = (m.player1_id, m.player2_id, won)

    surface = draw.surface
    key = (MODEL_VERSION, draw.id, week, surface, best_of(draw),
           tuple(sorted(live.items())))
    return DrawOdds(ratings, surface, best_of(draw), live, key)


# What the column credits, once, wherever it is drawn.
ATTRIBUTION = "Elo ratings from Tennis Abstract (CC BY-NC-SA 4.0)"
