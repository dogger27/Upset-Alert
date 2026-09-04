"""Per-point labels for a match's scrubber — "Prev Point: Ace".

WHAT SOFASCORE ACTUALLY GIVES US, and it is less than it first appears:
`/event/{id}/point-by-point` returns every point with the score after it and a
`pointDescription` that is 0 for an ordinary point, 1 for an ace and 2 for a
double fault. Nothing names a stroke — "backhand winner" exists only as a match
TOTAL in /statistics, and there is no commentary feed for tennis (both
/comments and /incidents 404). So aces and double faults are the whole of what
can honestly be said about an individual point, which is exactly what this
serves.

COST: one request per MATCH, not per point. The whole list arrives at once.

HOW POINTS ARE MATCHED: BY ORDER, NOT BY SCORE. A score is not unique inside a
game — every deuce cycle revisits 40-40 and 40-A, which made a score-based match
ambiguous for about a fifth of all points. Order is unique: our snapshots and
their points are both in play order, and ours is a SUBSEQUENCE of theirs (the
poller can miss a point, it can never invent one). So the two are walked
together with a greedy two-pointer, which places the first 40-40 against the
first 40-40, the second against the second, and so on. Nothing is left
ambiguous by the deuce case any more.

WHAT IS GENUINELY MISSING, and no algorithm can fix it: **their list omits the
point that ENDS each game.** Verified by walking games against the match's own
statistics — a match with 26 games carried exactly 26 fewer points than the
statistics counted, and every game's rows stop one point short of the game
being won. An ace on game point is therefore invisible here. Tiebreaks, by
contrast, ARE included: a 6-7 set carries all 13 of its games.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional


logger = logging.getLogger(__name__)

# pointDescription → what we print. Anything else is an ordinary point.
LABELS = {1: "Ace", 2: "Double Fault"}

# How stale a LIVE match's point list may be before it is refetched. A point is
# a few seconds of tennis, and this only runs while a reader has the popup
# open, so a short window costs at most one request per reader per minute.
LIVE_TTL = timedelta(seconds=45)


def _key(set_no, game_no) -> str:
    return f"{set_no}-{game_no}"


def normalise(payload: dict) -> dict:
    """Their nested sets → games → points, flattened to one entry per game."""
    out: dict = {}
    for s in (payload or {}).get("pointByPoint") or []:
        set_no = s.get("set")
        for g in s.get("games") or []:
            game_no = g.get("game")
            pts = [{"h": p.get("homePoint"), "a": p.get("awayPoint"),
                    "l": LABELS.get(p.get("pointDescription"))}
                   for p in (g.get("points") or [])]
            if set_no and game_no and pts:
                out[_key(set_no, game_no)] = pts
    return out


async def points_for(db, event_id: Optional[int], *, finished: bool) -> dict:
    """The normalised point list for an event, from cache or freshly fetched.

    Never raises: a blocked feed, a 404 on an event too old to carry points, or
    no event id at all all mean the same thing to the caller — no labels.
    """
    from app.models.score_history import SofaPointsCache
    from app.services import sofascore as sf

    if not event_id:
        return {}

    row = await db.get(SofaPointsCache, event_id)
    if row is not None:
        fresh = row.final or (
            datetime.now(timezone.utc) - row.fetched_at.replace(tzinfo=timezone.utc)
            < LIVE_TTL)
        if fresh:
            return row.data_json or {}

    try:
        payload = await sf._get(f"/event/{event_id}/point-by-point")
    except Exception as exc:                                       # noqa: BLE001
        # Includes SofascoreBlocked. The popup simply shows no labels; it is
        # never worth failing a score history over a decoration.
        logger.info("point-by-point unavailable for %s: %s", event_id, exc)
        return (row.data_json or {}) if row is not None else {}

    data = normalise(payload)
    now = datetime.now(timezone.utc)
    if row is None:
        db.add(SofaPointsCache(event_id=event_id, fetched_at=now,
                               final=bool(finished), data_json=data))
    else:
        row.fetched_at, row.final, row.data_json = now, bool(finished), data
    return data


def _position(snap) -> Optional[tuple]:
    """The (set, game) a snapshot belongs to, or None if it cannot be placed."""
    games, point = (snap or {}).get("games"), (snap or {}).get("point")
    if not games or len(games) < 2 or not point or len(point) < 2:
        return None
    set_no = len(games[0] or [])
    if set_no < 1:
        return None
    try:
        done = int(games[0][set_no - 1] or 0) + int(games[1][set_no - 1] or 0)
    except (TypeError, ValueError):
        return None
    return (set_no, done + 1)


def _walk(snapshots: list, points: dict, flip: bool) -> tuple:
    """Greedy two-pointer per game. Returns (labels, how many points placed).

    Ours is a subsequence of theirs, so within a game the pointer only ever
    moves forward: for each snapshot, advance through their points until the
    score agrees. That is what makes a deuce cycle unambiguous — the third
    40-40 can only match their third 40-40, never their first.
    """
    out = [None] * len(snapshots)
    placed = 0
    cursor: dict = {}                     # (set, game) -> how far into their list
    for i, snap in enumerate(snapshots):
        pos = _position(snap)
        if pos is None:
            continue
        theirs = points.get(_key(*pos))
        if not theirs:
            continue
        point = snap.get("point")
        h, a = (point[1], point[0]) if flip else (point[0], point[1])
        j = cursor.get(pos, 0)
        while j < len(theirs):
            p = theirs[j]
            j += 1
            if str(p.get("h")) == str(h) and str(p.get("a")) == str(a):
                out[i] = p.get("l")
                placed += 1
                break
        cursor[pos] = j
    return out, placed


def align(snapshots: list, points: dict) -> list:
    """One label per snapshot, or None — parallel to the list handed in.

    Orientation is discovered rather than assumed: the snapshot is stored in
    the MATCH's order (player1 first) while Sofascore keeps its own home/away,
    so both are walked and whichever places more points wins. On a real match
    the two differ by an order of magnitude, so there is nothing marginal about
    the choice.
    """
    if not points or not snapshots:
        return [None] * len(snapshots)
    straight, n_straight = _walk(snapshots, points, flip=False)
    flipped, n_flipped = _walk(snapshots, points, flip=True)
    return flipped if n_flipped > n_straight else straight


async def labels_for(db, snapshots: list, event_id: Optional[int],
                     *, finished: bool) -> list:
    """The whole job: fetch (or reuse) the point list and align it."""
    if not snapshots or not event_id:
        return [None] * len(snapshots)
    return align(snapshots, await points_for(db, event_id, finished=finished))
