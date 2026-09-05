"""Sofascore's per-match statistics, for the Match Stats tab.

The scrubber's existing figures are computed from OUR OWN snapshots and follow
the slider. These do not: Sofascore keeps no per-point history of them, only a
running total per period (`ALL` plus one entry per set). So this answers "how
has the match gone", never "how had it gone at point 47".

TWO MEASURED BEHAVIOURS SHAPE THIS FILE (2026-09-05, see the sofascore-data-
model memory):

1. **About one read in five comes back STALE** — a cache node serving an older
   copy of the match. It is internally consistent (a real earlier state), so it
   cannot be spotted by inspecting the response; the only test is comparison
   against what we already hold. Since the true counts never fall, ANY read in
   which a count decreases is discarded. Without this the page shows numbers
   running backwards a fifth of the time.
2. **A closed set's figures never change again.** Once a set is over its period
   is frozen, so a cached copy of it stays correct for the life of the match.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Don't ask again this soon. A game is two to four minutes, which is the
# natural cadence for these numbers: they only move when points are played.
MIN_REFETCH = timedelta(seconds=45)

# In PROCESS, never the database — this is read from a GET, and a GET that
# writes takes SQLite's single writer (see the reads-must-not-write memory).
_CACHE: dict = {}                       # event_id -> (fetched_at, final, rows)
_CACHE_MAX = 256

# What we show, in order, and where each comes from. `(group, item)` names the
# Sofascore row; `pair` names a second row supplying the denominator when the
# figure is a bare count that only means something against a total.
SERVE = [
    ("First serve %",            "Service", "First serve",         None),
    ("First serve points won",   "Service", "First serve points",  None),
    ("Second serve points won",  "Service", "Second serve points", None),
    ("Service games won",        "Games",   "Service games won",
     ("Service", "Service games played")),
]
RETURN = [
    ("1st serve return points won", "Return", "First serve return points",  None),
    ("2nd serve return points won", "Return", "Second serve return points", None),
    ("Return games played",         "Return", "Return games played",        None),
]


def _index(payload: dict) -> dict:
    """(period, group, item) -> the raw item dict."""
    out: dict = {}
    for per in (payload or {}).get("statistics") or []:
        p = per.get("period")
        for g in per.get("groups") or []:
            for it in g.get("statisticsItems") or []:
                out[(p, g.get("groupName"), it.get("name"))] = it
    return out


def _fraction(item: dict, side: str) -> tuple:
    """(won, total) for one side, from the display string when it has one.

    `home`/`away` are display strings — "19/40 (48%)" for a ratio, "13" for a
    bare count. `homeValue`/`awayValue` carry only the first number, so the
    denominator has to come from the string. A count returns total None.
    """
    raw = str(item.get(side) or "").strip()
    head = raw.split(" ")[0] if raw else ""
    if "/" in head:
        made, _, tot = head.partition("/")
        try:
            return int(made), int(tot)
        except ValueError:
            return 0, None
    try:
        return int(float(head)), None
    except ValueError:
        val = item.get(f"{side}Value")
        return (int(val) if isinstance(val, (int, float)) else 0), None


def _rows_for(idx: dict, period: str) -> list:
    rows = []
    for section, spec in (("Serve", SERVE), ("Return", RETURN)):
        for label, group, name, pair in spec:
            item = idx.get((period, group, name))
            if item is None:
                continue
            h_won, h_tot = _fraction(item, "home")
            a_won, a_tot = _fraction(item, "away")
            if pair is not None:
                denom = idx.get((period, pair[0], pair[1]))
                if denom is None:
                    continue
                h_tot = _fraction(denom, "home")[0]
                a_tot = _fraction(denom, "away")[0]
            rows.append({"section": section, "label": label,
                         "home": [h_won, h_tot], "away": [a_won, a_tot]})
    return rows


def _counts_fell(old: list, new: list) -> bool:
    """THE STALE-READ GUARD. True when any count went backwards.

    Compares won AND total on both sides. A percentage may legitimately fall;
    a count never does, so a fall means we were served an older copy.
    """
    prev = {(r["section"], r["label"]): r for r in old}
    for r in new:
        was = prev.get((r["section"], r["label"]))
        if was is None:
            continue
        for side in ("home", "away"):
            for now_v, old_v in zip(r[side], was[side]):
                if isinstance(now_v, int) and isinstance(old_v, int) and now_v < old_v:
                    return True
    return False


async def stats_for(event_id: Optional[int], *, finished: bool) -> dict:
    """Curated serve/return figures per period. Never raises."""
    if not event_id:
        return {}

    hit = _CACHE.get(event_id)
    if hit is not None:
        at, was_final, cached = hit
        # A finished match cannot change; a live one is asked at most this often.
        if was_final or datetime.now(timezone.utc) - at < MIN_REFETCH:
            return cached

    from app.services import sofascore as sf
    try:
        payload = await sf._get(f"/event/{event_id}/statistics")
    except Exception as exc:                                       # noqa: BLE001
        logger.info("statistics unavailable for %s: %s", event_id, exc)
        return hit[2] if hit else {}

    idx = _index(payload)
    periods = [p.get("period") for p in (payload.get("statistics") or [])
               if p.get("period")]
    fresh = {p: _rows_for(idx, p) for p in periods}

    # THE GUARD. Keep the period we already had whenever the new copy counts
    # DOWN — that read came off a stale cache node and the next one recovers.
    if hit is not None:
        for period, rows in list(fresh.items()):
            old_rows = (hit[2].get("periods") or {}).get(period)
            if old_rows and _counts_fell(old_rows, rows):
                logger.info("stale statistics read for %s period %s — kept previous",
                            event_id, period)
                fresh[period] = old_rows

    out = {"periods": fresh, "order": periods}
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)), None)
    _CACHE[event_id] = (datetime.now(timezone.utc), bool(finished), out)
    return out
