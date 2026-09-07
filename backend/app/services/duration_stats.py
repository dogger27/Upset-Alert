"""How long a match takes, and how long a set takes, from the timed archive.

COLLECT EVERYTHING, TRIM HERE. `match_duration_samples` keeps every finished
event exactly as Sofascore reported it, and every judgement about what counts
lives in this file. That order matters: a threshold changed here is a query,
where a threshold applied during collection would mean re-fetching a hundred
thousand matches to ask the question a second time.

TWO KINDS OF ROW ARE EXCLUDED, for different reasons.

A SUPER TIEBREAK IS NOT A SET. The tours replace a doubles third set with a
first-to-10, and it lasts a fifth as long. Averaging those into "how long is a
set" drags the figure down and describes nothing that happens on court.
Recognised by shape AND clock together, because neither alone is safe: a
genuine 10-8 set exists, and it takes an hour rather than twelve minutes.

ANOMALIES ARE EXCLUDED BY BOUNDS. A retirement two games in, a clock that
never started, a suspension counted inside a set — all land far outside what
tennis does, and a mean is defenceless against them. The bounds are wide
enough to keep a five-set epic and a 6-0 6-0 rout, which are real.

Every function reports what it threw away. A trimmed average that does not say
how much it trimmed is indistinguishable from a wrong one.
"""

from typing import Optional

from sqlalchemy import select

from app.models.duration_sample import MatchDurationSample

# A whole match. Below the floor is a retirement or a walkover; above the
# ceiling is a delay counted as play. Isner-Mahut would be excluded, correctly:
# it is not a number any schedule should plan around.
MATCH_MIN_MIN, MATCH_MAX_MIN = 30, 300

# One set. The floor keeps out super tiebreaks and abandoned sets; the ceiling
# keeps out a set that swallowed a rain delay. A 6-0 blowout can be twenty
# minutes and a long set an hour and a half, and both belong.
SET_MIN_MIN, SET_MAX_MIN = 15, 95

# A first-to-10 decider: ten or more "games" to the winner, and over inside
# this. A real 10-8 set takes an hour, so the clock is what separates them.
SUPER_TB_MAX_MIN = 25


def is_super_tiebreak(games, seconds, *, is_last: bool) -> bool:
    """Is this 'set' a first-to-10 match tiebreak rather than a set?"""
    if not is_last or not games or len(games) != 2:
        return False
    a, b = games[0] or 0, games[1] or 0
    if max(a, b) < 10:
        return False
    if seconds is None:
        # No clock to judge by. A 10-x score in a FINAL set is far more often
        # a match tiebreak than a genuine 10-8, so call it one.
        return True
    return seconds / 60.0 <= SUPER_TB_MAX_MIN


def _percentiles(values: list, points=(10, 25, 50, 75, 90)) -> dict:
    if not values:
        return {}
    s = sorted(values)
    out = {}
    for p in points:
        # Nearest-rank: no interpolation, so every figure reported is a real
        # match that happened rather than a blend of two.
        k = max(0, min(len(s) - 1, round(p / 100 * len(s) + 0.5) - 1))
        out[f"p{p}"] = s[k]
    return out


async def match_stats(db, **where) -> dict:
    """Whole-match minutes for one group: percentiles, count, what was dropped."""
    q = select(MatchDurationSample.duration_min)
    for col, val in where.items():
        if val is not None:
            q = q.where(getattr(MatchDurationSample, col) == val)
    raw = [v for (v,) in (await db.execute(q)).all() if v]
    kept = [v for v in raw if MATCH_MIN_MIN <= v <= MATCH_MAX_MIN]
    return {"n": len(kept), "dropped": len(raw) - len(kept), **_percentiles(kept)}


async def set_stats(db, **where) -> dict:
    """Minutes per SET for one group, super tiebreaks and anomalies removed."""
    q = select(MatchDurationSample.set_seconds_json, MatchDurationSample.set_games_json)
    for col, val in where.items():
        if val is not None:
            q = q.where(getattr(MatchDurationSample, col) == val)
    rows = (await db.execute(q)).all()

    kept, tiebreaks, out_of_bounds = [], 0, 0
    for seconds, games in rows:
        seconds, games = seconds or [], games or []
        for i, secs in enumerate(seconds):
            g = games[i] if i < len(games) else None
            if is_super_tiebreak(g, secs, is_last=(i == len(seconds) - 1)):
                tiebreaks += 1
                continue
            if secs is None:
                out_of_bounds += 1
                continue
            mins = secs / 60.0
            if SET_MIN_MIN <= mins <= SET_MAX_MIN:
                kept.append(int(round(mins)))
            else:
                out_of_bounds += 1
    return {"n": len(kept), "super_tiebreaks": tiebreaks,
            "out_of_bounds": out_of_bounds, **_percentiles(kept)}


async def sets_distribution(db, *, leader_ahead_by: Optional[int] = None,
                            **where) -> dict:
    """How many sets a match runs, optionally given a lead already established.

    `leader_ahead_by=2` asks the live question: someone is two sets up — how
    often does this finish in three, four or five? That conditional is worth
    more to a schedule than any refinement of the average, because for a match
    on court we already know which case we are in.
    """
    q = select(MatchDurationSample.set_games_json, MatchDurationSample.duration_min)
    for col, val in where.items():
        if val is not None:
            q = q.where(getattr(MatchDurationSample, col) == val)
    counts: dict = {}
    for games, mins in (await db.execute(q)).all():
        games = games or []
        if not games or not (mins and MATCH_MIN_MIN <= mins <= MATCH_MAX_MIN):
            continue
        winners = [1 if (g[0] or 0) > (g[1] or 0) else 2
                   for g in games if g and g[0] is not None]
        if leader_ahead_by is not None:
            need = leader_ahead_by
            if len(winners) < need or len(set(winners[:need])) != 1:
                continue
        counts[len(games)] = counts.get(len(games), 0) + 1
    total = sum(counts.values())
    return {"n": total,
            "by_sets": {k: counts[k] for k in sorted(counts)},
            "share": {k: round(100 * counts[k] / total) for k in sorted(counts)} if total else {}}
