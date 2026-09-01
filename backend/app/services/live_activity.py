"""
Turning a score change into a Live Activity push: the classifier, the throttle
and the worker.

THE PROBLEM THIS FILE EXISTS TO SOLVE. A tennis match produces roughly 200-400
content changes over two to four hours. APNs budgets Live Activity updates, and
exceeding the budget does not return an error — it silently stops delivering,
which leaves a WRONG SCORE frozen on someone's Lock Screen. That is the worst
available failure, because the user believes it and blames the app. So the
question is never "did something change" but "is this change worth one of a
finite number of pushes".

Answered by EVENT, not by clock. A break of serve at 4-4 in the fifth is worth
an immediate push; the third point of a hold at 5-0 is not, however recently we
last sent one.
"""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Throttle policy ─────────────────────────────────────────────────────────

PRIORITY_IMMEDIATE = 10
PRIORITY_OPPORTUNISTIC = 5

# An ordinary point is worth at most one push every this often. Chosen to match
# the freshness window the rest of the app uses, so an activity is never more
# stale than the website would let a score be.
MIN_INTERVAL_P5 = 45.0
# Two set-wins three seconds apart is a feed glitch, not tennis.
MIN_INTERVAL_P10 = 3.0
# Apple's budget is not published as a number, so this is a ceiling we can
# defend rather than one they gave us: beyond it, everything degrades to
# priority 5 instead of the activity dying.
MAX_HIGH_PRIORITY_PER_HOUR = 30
# A circuit breaker in the spirit of score_history's PER_MATCH_CAP. If we ever
# send this many for one match, something is looping and the activity is ended
# rather than left to burn the budget for every OTHER match too.
MAX_TOTAL_PER_MATCH = 400

# How long a push is worth delivering. A point score is meaningless after a
# minute and a half — the same reasoning as FRESH_SECONDS — while the end push
# is worth an hour because it is the thing the user actually wanted.
EXPIRY_P5 = 90
EXPIRY_P10 = 300
EXPIRY_END = 3600


@dataclass
class Decision:
    send: bool
    priority: int = PRIORITY_OPPORTUNISTIC
    reason: str = ""


def classify(prev: Optional[dict], cur: Optional[dict]) -> Decision:
    """Is this change worth a push, and how urgently?

    Pure, and importable by the budget simulator so the simulation cannot drift
    from what production actually does — importing this rather than
    reimplementing it is the entire reason the policy can be validated against
    real match history before a single push is sent.

    `prev` and `cur` are renderable_point() outputs (or None).
    """
    if cur is None:
        return Decision(False, reason="no_state")
    if prev is None:
        # First state we ever had for this activity. Always worth sending: the
        # alternative is a Lock Screen showing whatever the client guessed.
        return Decision(True, PRIORITY_IMMEDIATE, "first")

    # Play stopping or restarting changes what the row MEANS, not just its
    # numbers, and a suspended match may then be silent for hours.
    if bool(prev.get("suspended")) != bool(cur.get("suspended")):
        return Decision(True, PRIORITY_IMMEDIATE,
                        "suspended" if cur.get("suspended") else "resumed")

    pg, cg = prev.get("games"), cur.get("games")
    prev_sets = _sets(pg)
    cur_sets = _sets(cg)

    if cur_sets != prev_sets:
        return Decision(True, PRIORITY_IMMEDIATE, "set_won")

    if not prev.get("tiebreak") and cur.get("tiebreak"):
        return Decision(True, PRIORITY_IMMEDIATE, "tiebreak")
    if not prev.get("match_tiebreak") and cur.get("match_tiebreak"):
        return Decision(True, PRIORITY_IMMEDIATE, "match_tiebreak")

    # A GAME CHANGED HANDS. Whether that is a break is the difference between
    # "the score moved" and "the match turned", and it is the single most
    # valuable thing this feature can put on a Lock Screen.
    broke = _break_of_serve(prev, cur, pg, cg)
    if broke:
        return Decision(True, PRIORITY_IMMEDIATE, "break")

    if _games_changed(pg, cg):
        return Decision(True, PRIORITY_OPPORTUNISTIC, "game")

    # Still in the same game: only the pressure points are worth interrupting
    # for. Break, set and match point are what people look up for.
    pressure = _pressure(cur, cur_sets)
    if pressure and pressure != _pressure(prev, prev_sets):
        return Decision(True, PRIORITY_IMMEDIATE, pressure)

    if prev.get("point") != cur.get("point"):
        return Decision(True, PRIORITY_OPPORTUNISTIC, "point")

    return Decision(False, reason="no_visible_change")


def _sets(games) -> tuple:
    """Completed sets won, as a tuple so it compares cleanly."""
    from app.services.live_activity_content import _sets_won
    return tuple(_sets_won(games))


def _games_changed(pg, cg) -> bool:
    return _flat(pg) != _flat(cg)


def _flat(games):
    if not games or len(games) != 2:
        return ()
    return tuple(zip(games[0], games[1]))


def _break_of_serve(prev: dict, cur: dict, pg, cg) -> bool:
    """Did the side that was NOT serving just win a game?

    Reads the server from the PREVIOUS state, because by the time the score
    updates the serve has already passed to the other player — using the
    current one would report the exact opposite.
    """
    server = prev.get("serving")
    if server not in (1, 2):
        return False
    before, after = _flat(pg), _flat(cg)
    if len(before) != len(after) or not after:
        return False
    # Only the set in progress can gain a game.
    try:
        b, a = before[-1], after[-1]
        gained = [int(a[i] or 0) - int(b[i] or 0) for i in (0, 1)]
    except (TypeError, ValueError):
        return False
    if sum(gained) != 1:
        return False
    winner = 1 if gained[0] == 1 else 2
    return winner != server


_PRESSURE_ORDER = ("match_point", "set_point", "break_point")


def _pressure(state: dict, sets_won) -> Optional[str]:
    """The most consequential thing on offer at this point, or None.

    Deliberately coarse: it answers "is someone a point from something" without
    modelling best-of-five properly, because a false positive costs one push
    and a false negative costs the moment people wanted the feature for.
    """
    point = state.get("point")
    server = state.get("serving")
    if not point or server not in (1, 2) or state.get("tiebreak"):
        return None
    games = state.get("games")
    flat = _flat(games)
    if not flat:
        return None
    try:
        g = [int(x or 0) for x in flat[-1]]
        p = [str(x) for x in point]
    except (TypeError, ValueError):
        return None

    receiver = 2 if server == 1 else 1
    idx = receiver - 1
    # "40" against anything below it, or an advantage, is a point away.
    ahead = (p[idx] == "40" and p[1 - idx] in ("0", "15", "30")) or p[idx] == "AD"
    if not ahead:
        return None

    # The receiver is a point from taking the game — which is a break.
    would_be = list(g)
    would_be[idx] += 1
    if would_be[idx] >= 6 and would_be[idx] - would_be[1 - idx] >= 2:
        # …and that game would take the set.
        if max(sets_won) >= 2:
            return "match_point"
        return "set_point"
    return "break_point"


# ── The queue ───────────────────────────────────────────────────────────────

_pending: set = set()
_wake = asyncio.Event()


def enqueue(match_ids) -> None:
    """Note that these matches changed. SYNCHRONOUS, AND IT MUST STAY THAT WAY.

    Called from inside sofascore_live.poll_once's transaction. Making this
    async and awaiting a push here would hold SQLite's single write lock across
    a round trip to Cupertino — the exact failure the transaction watchdog in
    database.py exists to catch, and the same shape as the app_log deadlock
    that took down saving picks for a day.

    A de-duplicating SET rather than a queue: if the worker is thirty seconds
    behind, the newest state of each match once is worth more than a backlog of
    five stale ones.
    """
    if not match_ids:
        return
    _pending.update(match_ids)
    _wake.set()


def drain() -> set:
    """Take everything pending. Called by the worker, never by a poller."""
    global _pending
    batch, _pending = _pending, set()
    _wake.clear()
    return batch


# ── Per-activity throttle state ─────────────────────────────────────────────

@dataclass
class SendState:
    """In memory on purpose.

    Writing last_sent_at and a hash to SQLite on every push would be about one
    write a second at fifty concurrent activities, against a single-writer
    database that has already had lock storms — and it would only show up
    during a final, which is the worst possible time to find out. Flushed
    periodically and on state transitions instead; losing it in a restart costs
    one redundant push per activity, which is nothing.
    """
    last_sent_at: float = 0.0
    last_p10_at: float = 0.0
    last_timestamp: int = 0
    last_hash: str = ""
    sent_count: int = 0
    p10_times: list = field(default_factory=list)


_state: dict = {}


def state_for(activity_id: int) -> SendState:
    return _state.setdefault(activity_id, SendState())


def content_hash(state: dict) -> str:
    """Identity of a content state, ignoring the timestamps that always move."""
    trimmed = {k: v for k, v in state.items() if k not in ("at", "stale_after")}
    return hashlib.sha1(
        json.dumps(trimmed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def should_send(activity_id: int, decision: Decision, state: dict,
                now: Optional[float] = None) -> Decision:
    """Apply the budget to a classification. Returns a possibly-downgraded copy.

    The end push never reaches here — see dispatch() — because it is the one
    push the feature cannot survive losing.
    """
    now = now or time.time()
    st = state_for(activity_id)

    h = content_hash(state)
    if h == st.last_hash:
        return Decision(False, decision.priority, "unchanged")

    if st.sent_count >= MAX_TOTAL_PER_MATCH:
        return Decision(False, decision.priority, "runaway")

    prio = decision.priority
    if prio == PRIORITY_IMMEDIATE:
        recent = [t for t in st.p10_times if now - t < 3600]
        if len(recent) >= MAX_HIGH_PRIORITY_PER_HOUR:
            # Degrade rather than drop: the content is still worth having, it
            # just is not worth interrupting for.
            prio = PRIORITY_OPPORTUNISTIC
        elif now - st.last_p10_at < MIN_INTERVAL_P10:
            return Decision(False, decision.priority, "p10_too_soon")

    if prio == PRIORITY_OPPORTUNISTIC and now - st.last_sent_at < MIN_INTERVAL_P5:
        return Decision(False, decision.priority, "coalesced")

    return Decision(True, prio, decision.reason)


def note_sent(activity_id: int, priority: int, state: dict,
              now: Optional[float] = None) -> int:
    """Record a send and return the aps.timestamp to use.

    Monotonic per activity, because ActivityKit silently discards an update
    whose timestamp does not exceed the previous one — and with coalescing and
    retries, wall-clock order is not guaranteed.
    """
    now = now or time.time()
    st = state_for(activity_id)
    st.last_sent_at = now
    st.last_hash = content_hash(state)
    st.sent_count += 1
    if priority == PRIORITY_IMMEDIATE:
        st.last_p10_at = now
        st.p10_times = [t for t in st.p10_times if now - t < 3600] + [now]
    ts = max(int(now), st.last_timestamp + 1)
    st.last_timestamp = ts
    return ts


def forget(activity_id: int) -> None:
    _state.pop(activity_id, None)


def enabled() -> bool:
    from app.services.apns import apns_enabled
    return bool(settings.live_activity_enabled and apns_enabled())
