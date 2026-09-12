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

HOW GOOD IS IT? Measured honestly — every match rated as of its tournament's
first Monday, so nothing the model sees postdates the result (1,443 matches,
2026-06-22 on; `scripts/fit_winprob.py`): the shipped blend reads 0.591 log
loss / 68% accuracy out of sample, against 0.598 for textbook Elo and 0.595
for the rank model alone. Modest, and the calibration is what matters for a
column: stated 65% favourites win 65%, stated 85% favourites win 86%. The
same script scored with TODAY'S Elo reads 0.573, which is the number to
distrust — September's rating knows how July went.

WHAT MOVES IT MOST is the surface figure (hElo/cElo/gElo, captured weekly
since 2026-09-12 and read here first): under the same leak it is worth 0.028
of log loss over the overall rating, and 0.079 on grass. Its own slope cannot
be fitted until the snapshots hold a season of it; until then it carries the
honest overall slope scaled by the ratio measured on today's page.
"""

from datetime import date
from typing import NamedTuple, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rankings import TeRankingsSnapshot
from app.models.tournament import Draw, DrawEntry
from app.services.winprob import predict

# Bumped whenever anything below changes the number a given draw produces —
# a coefficient, the Elo week, the live-score handling. It rides in the cache
# key so a deploy cannot serve yesterday's arithmetic.
MODEL_VERSION = 2   # surface Elo, the rank blend, and the game score (2026-09-12)

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
        # entry_id -> (overall elo, elo for THIS draw's surface, world ranking) — any None
        self.ratings = ratings
        self.surface = surface or "Hard"
        self.best_of = best_of
        # match_id -> (player1_id, player2_id, LiveScore)
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
        elo_a, selo_a, rank_a = self.ratings.get(a, (None, None, None))
        elo_b, selo_b, rank_b = self.ratings.get(b, (None, None, None))
        if (elo_a is None or elo_b is None) and rank_a is None and rank_b is None:
            # predict() refuses this rather than guessing, which is right for a
            # library and wrong for a column: two unrated qualifiers are a coin
            # toss, and one blank pair must not blank the whole draw.
            p = 0.5
        else:
            p = predict(rank_x=rank_a, rank_y=rank_b, elo_x=elo_a, elo_y=elo_b,
                        selo_x=selo_a, selo_y=selo_b,
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
        p1, p2, _score = live
        return (p1, p2, self.pair_prob(p1, p2, match_id))

    def _live_adjust(self, p: float, a: int, b: int, match_id) -> float:
        """Fold the scoreboard of a match in progress into its pre-match odds.

        Sets AND the games of the set in progress: a set down but 5-2 up is
        most of the way back, and a column that only counted sets would call
        it grief. Only for the two players who are ACTUALLY on court in that
        match — the enumeration asks about hypothetical pairings in later
        rounds too, and a score belongs to the pair that earned it.
        """
        live = self.live.get(match_id) if match_id is not None else None
        if not live:
            return p
        p1, p2, sc = live
        if {a, b} != {p1, p2}:
            return p
        from app.services.winprob import live_win_prob_games
        flip = a != p1
        sets_a, sets_b = (sc.sets[1], sc.sets[0]) if flip else sc.sets
        games_a, games_b = (sc.games[1], sc.games[0]) if flip else sc.games
        if not any((sets_a, sets_b, games_a, games_b, sc.tiebreak)):
            return p
        return live_win_prob_games(p_match=p, sets_x=sets_a, sets_y=sets_b,
                                   games_x=games_a, games_y=games_b,
                                   in_tiebreak=sc.tiebreak, best_of=self.best_of)


def best_of(draw: Draw) -> int:
    """Sets to win a match. Stated by the tournament feed where we have it."""
    n = getattr(draw, "sofa_number_of_sets", None)
    if n in (3, 5):
        return n
    # Men's Grand Slam singles is the only best-of-five left on either tour.
    return 5 if (draw.gender == "M" and (draw.category or "").lower().startswith("grand")) else 3


class LiveScore(NamedTuple):
    """A scoreboard as the odds see it: sets won, the set in progress, tiebreak?"""
    sets: tuple
    games: tuple
    tiebreak: bool


def _live_score(match) -> Optional[LiveScore]:
    """The scoreboard of a match in progress, or None when there is none.

    Reads through the same shared helpers every other surface uses, so a set
    is "complete" here exactly when the bracket draws it as complete, and the
    set in progress is the last column the grid holds that is not. A tiebreak
    is flagged rather than counted: `renderable_point` keeps the tiebreak out
    of the games grid, so 6-6 with a tiebreak on is the state to report.
    """
    from app.services.live_activity_content import _sets_won
    from app.services.sofascore_live import renderable_point
    snap = renderable_point(getattr(match, "sofa_live_json", None),
                            getattr(match, "winner_id", None) is not None,
                            max_age=LIVE_MAX_AGE)
    games = (snap or {}).get("games")
    if not games or len(games) != 2:
        return None
    won = _sets_won(games)
    cur = (0, 0)
    try:
        ga, gb = int(games[0][-1]), int(games[1][-1])
        # The last column is the set in progress unless it is already over.
        if not ((max(ga, gb) >= 6 and abs(ga - gb) >= 2) or max(ga, gb) == 7):
            cur = (ga, gb)
    except (TypeError, ValueError, IndexError):
        pass
    tb = bool(snap.get("tiebreak")) and not snap.get("match_tiebreak")
    if not any(won) and cur == (0, 0) and not tb:
        return None
    return LiveScore(tuple(won), cur, tb)


async def draw_odds(db: AsyncSession, draw: Draw, all_matches: list) -> Optional[DrawOdds]:
    """The odds source for one draw, or None when there is no field to rate."""
    rows = (await db.execute(
        select(DrawEntry.id, DrawEntry.te_player_id, DrawEntry.ranking)
        .where(DrawEntry.draw_id == draw.id))).all()
    if not rows:
        return None

    te_ids = [r.te_player_id for r in rows if r.te_player_id]
    by_te: dict[int, tuple] = {}   # te_player_id -> (elo, surface elo, rank)
    week: Optional[date] = None
    surface_col = _SURFACE_COLUMN[_norm_surface(draw.surface)]
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
            # THE SURFACE FIGURE FIRST. hElo / cElo / gElo is the overall Elo
            # blended with a rating built from that surface's results alone,
            # and on our own matches it is worth three times more than any
            # recalibration of the overall figure — most of all on grass.
            # The latest RANK too: the entry's `ranking` is the week it got
            # into the draw, and the fallback model wants the current one.
            for pid, elo, selo, rank in (await db.execute(
                    select(TeRankingsSnapshot.player_id, TeRankingsSnapshot.elo,
                           surface_col, TeRankingsSnapshot.rank)
                    .where(TeRankingsSnapshot.player_id.in_(te_ids),
                           TeRankingsSnapshot.week_date == week))).all():
                by_te[pid] = (elo, selo, rank)

    def _rating(r):
        elo, selo, rank = by_te.get(r.te_player_id, (None, None, None)) if r.te_player_id else (None, None, None)
        return (elo, selo, rank or r.ranking)

    ratings = {r.id: _rating(r) for r in rows}
    live = {}
    for m in all_matches:
        if m.winner_id is not None or m.is_bye or not m.player1_id or not m.player2_id:
            continue
        score = _live_score(m)
        if score:
            live[m.id] = (m.player1_id, m.player2_id, score)

    surface = draw.surface
    key = (MODEL_VERSION, draw.id, week, surface, best_of(draw),
           tuple(sorted(live.items())))
    return DrawOdds(ratings, surface, best_of(draw), live, key)


def _norm_surface(surface: Optional[str]) -> str:
    s = (surface or "Hard").strip().lower()
    return "Clay" if s.startswith("clay") else "Grass" if s.startswith("grass") else "Hard"


_SURFACE_COLUMN = {
    "Hard": TeRankingsSnapshot.elo_hard,     # indoor hard is hard; carpet is gone
    "Clay": TeRankingsSnapshot.elo_clay,
    "Grass": TeRankingsSnapshot.elo_grass,
}


# What the column credits, once, wherever it is drawn.
ATTRIBUTION = "Elo ratings from Tennis Abstract (CC BY-NC-SA 4.0)"
