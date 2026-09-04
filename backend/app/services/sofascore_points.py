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

WHY THE MATCHING IS BY SCORE AND ONLY WHEN UNAMBIGUOUS. Measured on a real
169-point match: only 148 of the (set, game, score) keys were distinct, because
every deuce cycle repeats 40-40 and 40-A. So roughly a fifth of points share a
score with another point in the same game, and picking one of them would put an
"Ace" against a point that was not an ace. Those are left unlabelled. Silence
is the correct answer when the data cannot tell you.
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


def align(snapshots: list, points: dict) -> list:
    """One label per snapshot, or None — parallel to the list handed in.

    A snapshot knows its set (how many sets are on the board) and its game
    (games played in the current set, plus the one in progress), so the point
    list is narrowed to a single game before any score is compared. Orientation
    is decided by trying both and keeping whichever lands more points, because
    the snapshot is stored in the MATCH's order (player1 first) while Sofascore
    keeps its own home/away and the two need not agree.
    """
    if not points or not snapshots:
        return [None] * len(snapshots)

    best, best_hits = [None] * len(snapshots), -1
    for flip in (False, True):
        got, hits = [], 0
        for snap in snapshots:
            got.append(None)
            games, point = (snap or {}).get("games"), (snap or {}).get("point")
            if not games or len(games) < 2 or not point or len(point) < 2:
                continue
            set_no = len(games[0] or [])
            if set_no < 1:
                continue
            try:
                done = int(games[0][set_no - 1] or 0) + int(games[1][set_no - 1] or 0)
            except (TypeError, ValueError):
                continue
            pts = points.get(_key(set_no, done + 1))
            if not pts:
                continue
            h, a = (point[1], point[0]) if flip else (point[0], point[1])
            hit = [p for p in pts
                   if str(p.get("h")) == str(h) and str(p.get("a")) == str(a)]
            # Exactly one, or nothing: see the note at the top of this file.
            if len(hit) == 1:
                got[-1] = hit[0].get("l")
                hits += 1
        if hits > best_hits:
            best, best_hits = got, hits
    return best


async def labels_for(db, snapshots: list, event_id: Optional[int],
                     *, finished: bool) -> list:
    """The whole job: fetch (or reuse) the point list and align it."""
    if not snapshots or not event_id:
        return [None] * len(snapshots)
    return align(snapshots, await points_for(db, event_id, finished=finished))
