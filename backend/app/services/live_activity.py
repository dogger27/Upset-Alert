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
# PRIORITY 5 IS THE UNLIMITED CHANNEL. Apple's own session (WWDC23 10185):
# priority 5 is "opportunistic delivery … no limit" and never spends the
# budget; only priority 10 does. The old 45 s here was OUR throttle on the
# unlimited channel — every point arrived up to a minute late for nothing.
# The poller reads Sofascore every 10 s, so 8 s lets back-to-back snapshots
# through and the card moves as fast as the feed does.
MIN_INTERVAL_P5 = 8.0
# Two set-wins three seconds apart is a feed glitch, not tennis.
MIN_INTERVAL_P10 = 3.0
# Apple's budget is not published as a number, so this is a ceiling we can
# defend rather than one they gave us: beyond it, everything degrades to
# priority 5 instead of the activity dying.
MAX_HIGH_PRIORITY_PER_HOUR = 30
# With NSSupportsLiveActivitiesFrequentUpdates the device grants a higher
# priority-10 budget ("can still get throttled" — Apple). The one measurement
# on record (developer forums, thread 731715): priority 10 every ~8 s WITH the
# flag froze the activity, and budget can take 24 h to return. So the flag
# buys a doubling here, not a licence: a break, a set, a match point every
# minute is already more than a match produces.
MAX_HIGH_PRIORITY_PER_HOUR_FREQUENT = 90
# And no closer than this. Measured 2026-09-02 on the user's phone: every
# point at priority 10 (~1 a minute) plus a handful of test pushes, and
# after ~25 minutes iOS stopped showing ANY update to the app's activities —
# the budget freeze Apple warns of, which it says can take hours to lift.
# Fifteen seconds, at the user's request (2026-09-02): the poll is 10 s, so
# this is at most every other snapshot. If the freeze recurs, 30 s is the
# value that was in place before and the first thing to go back to.
MIN_INTERVAL_P10_FREQUENT = 15.0
# PRIORITY 5 IS HELD, NOT DELIVERED. Measured 2026-09-02 on the user's own
# phone: six priority-5 point updates in four minutes, all accepted by APNs,
# none shown; a forced priority-10 push showed at once. "Opportunistic" means
# the phone delivers when it feels like it, which on a Lock Screen someone is
# watching is never. So on a device that granted frequent updates EVERY change
# goes at priority 10 — that budget is what the flag buys — up to the cap
# above (a point every 24 s, sustained, is more than tennis produces), and
# only past it does anything fall back to 5. Without the flag the old split
# stands: the moments that matter immediate, the rest opportunistic.
# A circuit breaker in the spirit of score_history's PER_MATCH_CAP. If we ever
# send this many for one match, something is looping and the activity is ended
# rather than left to burn the budget for every OTHER match too.
# Sized for a point-per-snapshot five-setter: one priority-5 push per 10 s
# poll for four hours is ~1400. Still a circuit breaker, not a budget.
MAX_TOTAL_PER_MATCH = 1500

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
    # Nothing is draining this when the feature is off, so collecting would be
    # an accumulation with no reader — small, but pointless, and it would make
    # the first push after enabling the feature a flood of everything that had
    # changed since boot.
    if not settings.live_activity_enabled:
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
    p10_total: int = 0        # lifetime priority-10 sends, persisted as high_priority_count
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
                now: Optional[float] = None, frequent: bool = False) -> Decision:
    """Apply the budget to a classification. Returns a possibly-downgraded copy.

    The end push never reaches here — see dispatch() — because it is the one
    push the feature cannot survive losing.
    """
    # THE CLASSIFIER'S "NO" IS FINAL. This function only knows how to say
    # "not yet" — it applies a budget, and a budget cannot turn a change nobody
    # would notice into one worth sending. Without this line a
    # Decision(False, "no_visible_change") fell straight through every branch
    # below and came out as Decision(True, ..., "no_visible_change"), which is
    # exactly what the dry run logged: seven of twenty pushes whose own stated
    # reason was that nothing had changed.
    if not decision.send:
        return decision

    now = now or time.time()
    st = state_for(activity_id)

    h = content_hash(state)
    if h == st.last_hash:
        return Decision(False, decision.priority, "unchanged")

    if st.sent_count >= MAX_TOTAL_PER_MATCH:
        return Decision(False, decision.priority, "runaway")

    prio = decision.priority
    if frequent and prio == PRIORITY_OPPORTUNISTIC:
        prio = PRIORITY_IMMEDIATE
    if prio == PRIORITY_IMMEDIATE:
        recent = [t for t in st.p10_times if now - t < 3600]
        cap = MAX_HIGH_PRIORITY_PER_HOUR_FREQUENT if frequent else MAX_HIGH_PRIORITY_PER_HOUR
        if len(recent) >= cap:
            # Degrade rather than drop: the content is still worth having, it
            # just is not worth interrupting for.
            prio = PRIORITY_OPPORTUNISTIC
        elif now - st.last_p10_at < (MIN_INTERVAL_P10_FREQUENT if frequent else MIN_INTERVAL_P10):
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
        st.p10_total += 1
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


# ── The dispatcher ──────────────────────────────────────────────────────────
#
# Reads, then sends, then writes — in three separate steps, never nested.
# SQLite has one writer and this database has already had lock storms; holding
# a write transaction open across a round trip to Cupertino is the exact shape
# of the app_log deadlock that took down saving picks for a day. So the session
# is closed before the first push goes out, and re-opened afterwards for the
# handful of rows that changed.

# The last point state we classified per match, so a change can be recognised.
# In memory because it is a comparison cache, not a fact — losing it in a
# restart costs one redundant push per activity.
_last_point: dict = {}


async def dispatch(match_ids: set) -> dict:
    """Push one round of updates for these matches. Never raises."""
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.app_device import AppDevice
    from app.models.live_activity import LiveActivity, STATE_ACTIVE
    from app.models.tournament import Match
    from app.services import apns
    from app.services.live_activity_content import (
        CONTENT_VERSION, STATUS_FINAL, STATUS_IN_PROGRESS, STATUS_SUSPENDED,
        build_content_state, build_payload, final_line,
    )
    from app.services.sofascore_live import live_point_for

    if not match_ids or not enabled():
        return {"sent": 0}

    # ── 1. READ ──────────────────────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(LiveActivity, AppDevice)
            .join(AppDevice, AppDevice.id == LiveActivity.device_id)
            .where(LiveActivity.match_id.in_(match_ids),
                   LiveActivity.state == STATE_ACTIVE,
                   AppDevice.disabled_at.is_(None))
        )).all()
        if not rows:
            return {"sent": 0}
        matches = {
            m.id: m for m in (await db.execute(
                select(Match).where(Match.id.in_(match_ids)))).scalars().all()
        }

        # THE PICK IS THE POINT, and it was being dropped. Every update built a
        # content state with no pick_side, so pick came out {side: null,
        # correct: null} — the first real push would have ERASED the highlight
        # that makes this different from a scores app. The activity looked right
        # only because the CLIENT's initial state carried it.
        #
        # Loaded here, in the read phase, because dispatch deliberately holds no
        # database session open across the APNs calls.
        from app.models.prediction import UserPrediction
        picks = {}
        user_ids = {la.user_id for la, _ in rows}
        if user_ids:
            for pr in (await db.execute(
                select(UserPrediction).where(
                    UserPrediction.user_id.in_(user_ids),
                    UserPrediction.match_id.in_(match_ids),
                )
            )).scalars().all():
                picks[(pr.user_id, pr.match_id)] = pr.predicted_winner_id

    # ── 2. BUILD, once per match rather than once per activity ───────────
    # A final can carry hundreds of activities; rendering per row would repeat
    # the same work for every one of them.
    per_match = {}
    priorities: list = []
    for mid, m in matches.items():
        point = live_point_for(m)
        finished = m.winner_id is not None
        prev = _last_point.get(mid)
        if not finished:
            _last_point[mid] = point

        if finished:
            status, event, ending = STATUS_FINAL, "end", True
            # THE FINAL SCORE COMES FROM scores_json, NOT FROM THE LIVE FEED.
            # renderable_point() returns None for a finished match — correctly,
            # since a live point on a match that is over is exactly the stale
            # state it exists to suppress. So the end push, the one the whole
            # feature is for, would have carried no score at all. The result is
            # written to scores_json on completion in the same shape `games`
            # already uses, so it drops straight in.
            if m.scores_json:
                point = {"games": m.scores_json, "point": None,
                         "tiebreak": False, "match_tiebreak": False,
                         "serving": None}
            elif prev:
                # Nothing recorded yet — the sweep that writes scores_json runs
                # on its own clock. The last live state we saw is a better
                # answer than a blank card.
                point = prev
        elif point and point.get("suspended"):
            status, event, ending = STATUS_SUSPENDED, "update", False
        else:
            status, event, ending = STATUS_IN_PROGRESS, "update", False

        per_match[mid] = {
            "point": point, "prev": prev, "status": status,
            "event": event, "ending": ending,
            "decision": classify(prev, point),
            "final_line": final_line((point or {}).get("games")) if ending else None,
        }

    # ── 3. SEND, with no database session open ───────────────────────────
    outcomes = []
    for la, device in rows:
        info = per_match.get(la.match_id)
        if info is None or not device.device_token:
            continue

        # Per activity, not per match: two users watching the same match picked
        # different players, and the whole value of the card is whose side the
        # score is going.
        m = matches.get(la.match_id)
        predicted = picks.get((la.user_id, la.match_id))
        pick_side = None
        if m is not None and predicted is not None:
            pick_side = (1 if predicted == m.player1_id
                         else 2 if predicted == m.player2_id else None)
        pick_correct = (None if (m is None or m.winner_id is None or predicted is None)
                        else predicted == m.winner_id)

        state = build_content_state(
            info["point"], status=info["status"],
            final_line=info["final_line"], version=la.content_version or CONTENT_VERSION,
            pick_side=pick_side, pick_correct=pick_correct,
        )

        if info["ending"]:
            # THE ONE PUSH THAT IS NEVER THROTTLED. Final score, your pick,
            # right or wrong — the payoff the whole feature exists for.
            priority, reason = PRIORITY_IMMEDIATE, "end"
        else:
            # The device reported ActivityAuthorizationInfo().frequentPushesEnabled
            # at registration; the user can switch it off per app in Settings.
            decided = should_send(la.id, info["decision"], state,
                                  frequent=bool(getattr(device, 'frequent_pushes', False)))
            if not decided.send:
                continue
            priority, reason = decided.priority, decided.reason

        ts = note_sent(la.id, priority, state)
        payload = build_payload(
            state, event=info["event"], timestamp=ts,
            dismissal_seconds=3600 if info["ending"] else None,
        )
        expiry = int(time.time()) + (
            EXPIRY_END if info["ending"]
            else EXPIRY_P10 if priority == PRIORITY_IMMEDIATE else EXPIRY_P5)

        if settings.live_activity_dry_run:
            logger.info("DRY RUN live activity %s match=%s p%s %s %s",
                        la.activity_id, la.match_id, priority, reason,
                        json.dumps(state, separators=(",", ":"))[:200])
            outcomes.append((la.id, None, info["ending"]))
            continue

        result = await apns.send(
            token=la.push_token, payload=payload, push_type="liveactivity",
            env=device.apns_env, priority=priority, expiration=expiry,
            # An undelivered update is REPLACED by the next rather than both
            # landing later — which is what makes coalescing real rather than
            # just local.
            collapse_id=f"la-{la.match_id}",
        )
        outcomes.append((la.id, result, info["ending"]))
        priorities.append(priority)

    # ── 4. WRITE what changed, in one short transaction ──────────────────
    await _record(outcomes)

    ok = sum(1 for _, r, _ in outcomes if r is None or r.ok)
    bad = [(i, r) for i, r, _ in outcomes if r is not None and not r.ok]

    # A SUCCESSFUL PUSH USED TO LOG NOTHING AT ALL. Only failures spoke, so
    # "delivering fine" and "not running" were the same silence — which is
    # exactly the question that could not be answered the first time this was
    # switched on for real.
    if outcomes:
        logger.info("live activity dispatch: %d sent (%d at p10), %d failed (matches %s)",
                    ok, sum(1 for p in priorities if p == PRIORITY_IMMEDIATE),
                    len(bad), sorted(match_ids))

    # system_logs is what /issues reads, so anything worth investigating has to
    # land there rather than only in a file. Failures only: a healthy round is
    # in the log above and does not need a row each time.
    # An activity the phone has already ended answers with a dead token: the
    # push raced the user's own removal (2026-09-04 06:03, activity 34, ended
    # by the client the same second). Normal, recorded as info — a warning is
    # for something someone should act on.
    over = [(i, r) for i, r in bad if r.activity_is_over]
    bad = [(i, r) for i, r in bad if not r.activity_is_over]
    if over:
        try:
            from app.services.system_log import app_log
            await app_log("info", "live_activity",
                          f"{len(over)} Live Activity push(es) landed on an activity that had "
                          f"already ended: " + ", ".join(f"#{i} {r.reason}" for i, r in over),
                          detail={"activities": [i for i, _ in over]})
        except Exception:                                            # noqa: BLE001
            pass
    if bad:
        try:
            from app.services.system_log import app_log
            reasons = {}
            for _, r in bad:
                reasons[r.reason or f"http_{r.status}"] = reasons.get(r.reason or f"http_{r.status}", 0) + 1
            # Per-activity detail: the 2026-09-04 row said "BadDeviceToken=1"
            # across three matches, and which token Apple had refused could
            # not be recovered afterwards.
            la_match = {la.id: (la.match_id, la.activity_id) for la, _ in rows}
            failed = [{"activity": i, "match": la_match.get(i, (None, None))[0],
                       "activity_id": la_match.get(i, (None, None))[1],
                       "reason": r.reason, "status": r.status}
                      for i, r in bad]
            await app_log(
                "warning", "live_activity",
                f"{len(bad)} Live Activity push(es) failed: "
                + ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())),
                detail={"matches": sorted(match_ids), "reasons": reasons,
                        "failed": failed},
                # One row per distinct failure shape per hour. A match that
                # keeps failing every ten seconds would otherwise bury every
                # other issue in /issues within a minute.
                dedup_key="live_activity:" + ",".join(sorted(reasons)),
                dedup_hours=1.0,
            )
        except Exception:                                            # noqa: BLE001
            # Logging must never be able to break dispatch. app_log is
            # fire-and-forget by design here for the same reason it is
            # everywhere else in this codebase.
            logger.warning("could not write live_activity failure to system_logs",
                           exc_info=True)

    return {"sent": ok}


async def _record(outcomes: list) -> None:
    """Persist the handful of rows that actually changed."""
    from datetime import datetime, timezone
    from sqlalchemy import update
    from app.database import AsyncSessionLocal
    from app.models.app_device import AppDevice
    from app.models.live_activity import LiveActivity, STATE_DEAD, STATE_ENDED

    if not outcomes:
        return
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        for la_id, result, ending in outcomes:
            st = _state.get(la_id)
            values = {"updated_at": now}
            if st:
                values.update(last_sent_at=now, last_sent_hash=st.last_hash,
                              last_sent_timestamp=st.last_timestamp,
                              sent_count=st.sent_count,
                              # Was never written before, so the column read 0 for
                              # every activity and could not answer "did the points
                              # go at 10?" — the question that mattered on 2026-09-02.
                              high_priority_count=st.p10_total)
            if ending:
                values.update(state=STATE_ENDED, ended_at=now,
                              end_reason="match_complete")
                forget(la_id)
            elif result is not None and result.activity_is_over:
                # The user dismissed it, it aged out, or Apple no longer knows
                # its token (BadDeviceToken on a liveactivity push is THIS
                # activity, not the phone). Normal, and it must never disable
                # the device — one did, on 2026-09-04, and froze every card.
                values.update(state=STATE_DEAD, ended_at=now,
                              end_reason=f"apns_{result.reason}")
                forget(la_id)
            await db.execute(
                update(LiveActivity).where(LiveActivity.id == la_id).values(**values))

            if result is not None and result.token_is_dead:
                # Unreachable from a liveactivity push by construction
                # (ApnsResult.token_is_dead); kept for the day an alert push
                # to the DEVICE token is added, which is the only push that
                # can prove a device gone.
                la = await db.get(LiveActivity, la_id)
                if la is not None:
                    await db.execute(
                        update(AppDevice).where(AppDevice.id == la.device_id)
                        .values(disabled_at=now, disabled_reason=result.reason))
            elif result is not None and result.reason == "env_corrected":
                la = await db.get(LiveActivity, la_id)
                if la is not None:
                    dev = await db.get(AppDevice, la.device_id)
                    if dev is not None:
                        dev.apns_env = ("sandbox" if dev.apns_env == "production"
                                        else "production")
        await db.commit()


async def end_now(la, device, match=None) -> bool:
    """End ONE activity on the device, right now — the user took the match off
    their Lock Screen. An end push with immediate dismissal, addressed like
    the dispatcher's; the content state is the match's current point so the
    card's last frame is true. Never raises. Older app builds have no native
    per-activity end, so this push is what removes their card."""
    from app.services import apns
    from app.services.live_activity_content import (STATUS_IN_PROGRESS, build_content_state,
                                                     build_payload)
    from app.services.sofascore_live import live_point_for
    if not la or not la.push_token or la.push_token == "pending" or device is None:
        return False
    try:
        point = live_point_for(match) if match is not None else None
        state = build_content_state(point, status=STATUS_IN_PROGRESS)
        payload = build_payload(state, event="end", timestamp=int(time.time()),
                                dismissal_seconds=0)
        result = await apns.send(
            token=la.push_token, payload=payload, push_type="liveactivity",
            env=device.apns_env, priority=PRIORITY_IMMEDIATE, expiration=EXPIRY_END,
            collapse_id=f"la-{la.match_id}")
        forget(la.id)
        return bool(getattr(result, "ok", False))
    except Exception as exc:  # noqa: BLE001 — a failed end push is a card that lingers, not an outage
        logger.warning("end push failed for activity %s: %s", la.activity_id, exc)
        return False


async def reap() -> int:
    """End activities the dispatcher will never hear about again.

    The safety net, and it has to exist because nothing guarantees we are told
    an activity is over: the app is killed, the phone dies, a deploy loses the
    pending set. Also the only thing that ends an activity whose match finished
    while this process was restarting.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select, update
    from app.database import AsyncSessionLocal
    from app.models.live_activity import LiveActivity, STATE_ACTIVE, STATE_ENDED
    from app.models.tournament import Match

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=8)
    ended = 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(LiveActivity).where(LiveActivity.state == STATE_ACTIVE)
        )).scalars().all()
        stale_ids, done_ids = [], []

        def _aware(dt):
            # SQLite hands back NAIVE datetimes regardless of what was written,
            # so comparing one to an aware `cutoff` raises and takes the whole
            # reaper round with it. Same helper and same convention as
            # sofa_compare._aware — stored times are UTC, they just lose the
            # tzinfo on the way through the driver.
            return None if dt is None else (dt if dt.tzinfo
                                            else dt.replace(tzinfo=timezone.utc))

        for la in rows:
            if (_aware(la.updated_at) or _aware(la.created_at)) < cutoff:
                # ActivityKit's own ceiling is a few hours; past this the
                # activity is gone from the device whatever we believe.
                stale_ids.append(la.id)
            elif la.match_id:
                m = await db.get(Match, la.match_id)
                if m is not None and m.winner_id is not None:
                    done_ids.append(la.id)
        for ids, reason in ((stale_ids, "stale"), (done_ids, "match_complete")):
            if ids:
                await db.execute(
                    update(LiveActivity).where(LiveActivity.id.in_(ids))
                    .values(state=STATE_ENDED, ended_at=now,
                            end_reason=reason, updated_at=now))
                ended += len(ids)
                for i in ids:
                    forget(i)
        await db.commit()
    return ended


async def worker() -> None:
    """Drain the queue and reap, forever. Started from main.py's lifespan.

    Deliberately not an APScheduler job. A score change is an EDGE — poll_once
    already knows exactly which matches changed — and a scheduled job would
    have to re-derive that by diffing a column the poller is concurrently
    rewriting, which is a second source of truth for the same fact. Its useful
    floor here is also two minutes, against a ten-second poll.
    """
    logger.info("live activity worker started (enabled=%s dry_run=%s)",
                settings.live_activity_enabled, settings.live_activity_dry_run)
    last_reap = 0.0
    while True:
        try:
            try:
                await asyncio.wait_for(_wake.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                pass
            batch = drain()
            if batch and enabled():
                await dispatch(batch)
            now = time.time()
            if enabled() and now - last_reap > 30.0:
                last_reap = now
                await reap()
        except asyncio.CancelledError:
            raise
        except Exception:                                          # noqa: BLE001
            # Never let one bad round kill the loop; the pollers depend on
            # nothing here, but a dead worker is a silently frozen Lock Screen.
            logger.exception("live activity worker round failed")
            await asyncio.sleep(5.0)
