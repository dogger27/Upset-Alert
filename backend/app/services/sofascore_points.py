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

# THE CACHE IS JUDGED ON COVERAGE, NOT ON A CLOCK. A clock is the wrong
# question: a twenty-second TTL meant a new point could appear on the timeline
# with no label and gain one later, which reads as a glitch. What matters is
# whether their list already contains the point we are being asked about. It
# does for every poll where nothing was played, and it does not the moment a
# point lands — so a fetch happens exactly when a point arrives and at no
# other time. In real tennis that is roughly two a minute per WATCHED match,
# against six a minute for a blind twenty-second TTL.
#
# The floor is the only clock left: it stops a match whose points can never be
# matched from asking again on every poll.
MIN_REFETCH = timedelta(seconds=5)


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


# In PROCESS, deliberately not in the database: this is read from a GET, and
# a GET that writes takes SQLite's single writer — the trap recorded in
# feedback_reads_must_not_write. A dict costs nothing, survives as long as the
# worker, and a restart simply refetches on demand.
_CACHE: dict = {}                      # event_id -> (fetched_at, final, data)
_CACHE_MAX = 512


# One fetch per event at a time, shared by every request that wants it. Two
# readers opening the same match must not become two requests to Sofascore.
_INFLIGHT: dict = {}

# HOW LONG A READER WAITS FOR THE LABELS, and it depends on whether there is
# anything on screen yet.
#
# COLD — nothing cached, so this is somebody opening the popup. The response
# IS the popup, so it must not sit behind a network call; past this it goes
# out unlabelled and the fetch keeps running for the next poll.
WAIT_COLD = 1.5
# WARM — a list is already cached, so this is a poll on a match being watched
# and the client is still showing the previous answer. Waiting here costs the
# reader nothing visible and buys the thing that matters: the new point and
# its label arrive in the SAME response, so a score never appears for a
# moment without the "Ace" beside it.
WAIT_WARM = 6.0


async def _fetch(event_id: int, finished: bool) -> dict:
    from app.services import sofascore as sf
    try:
        data = normalise(await sf._get(f"/event/{event_id}/point-by-point"))
    except Exception as exc:                                       # noqa: BLE001
        # Includes SofascoreBlocked. A decoration is never worth an error.
        logger.info("point-by-point unavailable for %s: %s", event_id, exc)
        return _CACHE.get(event_id, (None, False, {}))[2]
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)), None)
    _CACHE[event_id] = (datetime.now(timezone.utc), bool(finished), data)
    return data


# In PROCESS, deliberately not in the database: this is read from a GET, and a
# GET that writes takes SQLite's single writer — the trap recorded in
# feedback_reads_must_not_write. A dict costs nothing, survives as long as the
# worker, and a restart simply refetches on demand.
_CACHE: dict = {}                      # event_id -> (fetched_at, final, data)
_CACHE_MAX = 512


def _covers(data: dict, need: Optional[tuple]) -> bool:
    """Does this list already account for the newest point we hold?

    `need` is (set, game, how many snapshots WE have in that game). Ours counts
    one they never have — the 0-0 that opens a game — and they omit the point
    that ends one, so "caught up" is their count being within one of ours.
    """
    if need is None:
        return True
    set_no, game_no, ours = need
    return len(data.get(_key(set_no, game_no), [])) >= ours - 1


async def points_for(event_id: Optional[int], *, finished: bool,
                     need: Optional[tuple] = None) -> dict:
    """The point list for an event: cached when it covers `need`, else fetched.

    Never raises, and never blocks the caller for long — see WAIT_FOR_LABELS.
    """
    import asyncio

    if not event_id:
        return {}

    hit = _CACHE.get(event_id)
    if hit is not None:
        at, was_final, data = hit
        fresh = was_final or _covers(data, need)
        # The floor: having just asked, do not ask again for this poll even if
        # the answer still does not cover us — some points never will.
        if fresh or datetime.now(timezone.utc) - at < MIN_REFETCH:
            return data

    task = _INFLIGHT.get(event_id)
    if task is None or task.done():
        task = asyncio.create_task(_fetch(event_id, finished))
        _INFLIGHT[event_id] = task
        task.add_done_callback(lambda t, e=event_id: _INFLIGHT.pop(e, None))
    try:
        # shield: the wait may give up, the FETCH must not — it is what makes
        # the next request instant.
        return await asyncio.wait_for(asyncio.shield(task),
                                      WAIT_WARM if hit else WAIT_COLD)
    except asyncio.TimeoutError:
        return hit[2] if hit else {}
    except Exception:                                              # noqa: BLE001
        # _fetch swallows its own errors; this is the belt-and-braces path.
        return hit[2] if hit else {}


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
        # THE CURSOR ONLY MOVES ON A MATCH. Advancing it on a miss burns the
        # rest of the game: our list carries states theirs does not — the 0-0
        # at the start of every game, for one — and the first of those would
        # otherwise consume every remaining point. That bug placed 2 labels on
        # a match with 56 of them.
        j = cursor.get(pos, 0)
        while j < len(theirs):
            p = theirs[j]
            j += 1
            if str(p.get("h")) == str(h) and str(p.get("a")) == str(a):
                out[i] = p.get("l")
                placed += 1
                cursor[pos] = j
                break
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


def _need(snapshots: list) -> Optional[tuple]:
    """(set, game, our snapshots in that game) for the NEWEST point we hold."""
    if not snapshots:
        return None
    pos = _position(snapshots[-1])
    if pos is None:
        return None
    return (pos[0], pos[1], sum(1 for s in snapshots if _position(s) == pos))


async def labels_for(snapshots: list, event_id: Optional[int],
                     *, finished: bool) -> list:
    """The whole job: fetch (or reuse) the point list and align it.

    The newest point we hold is handed down as `need`, so the list is refetched
    exactly when a point has arrived that it does not yet describe — which is
    what makes the label appear WITH the score rather than after it.
    """
    if not snapshots or not event_id:
        return [None] * len(snapshots)
    points = await points_for(event_id, finished=finished,
                              need=None if finished else _need(snapshots))
    return align(snapshots, points)
