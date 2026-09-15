"""Facts about a match's live state that more than one poller has to agree on.

Both writers of Match.live_scores_json — the Sofascore poller and the ESPN
monitor — observe the same transitions, and a rule implemented twice is a rule
that will eventually be implemented differently.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional


def is_suspended(live) -> bool:
    """Does this live_scores payload say play has stopped?

    The status is the fifth element of the ESPN-shaped list. Absent means
    "playing" — the flag is only ever appended when there is something to say.
    """
    return (isinstance(live, (list, tuple)) and len(live) > 4
            and live[4] == "suspended")


# HOW LONG A STOP MUST LAST TO BE A RESUMPTION. "Resumed at" is for a rain
# delay or a match carried over from the day before — a stop the reader
# remembers. The two live-score writers disagree for seconds at a time (ESPN
# lags Sofascore by about a minute and reports a just-started match as
# scheduled, which its monitor reads as suspended), and a set break or a
# medical timeout is a few minutes: none of those is a resumption, and on one
# US Open day the flag stamped 23 matches, three of them on a court with a
# roof. Fifteen minutes is longer than any changeover and shorter than any
# weather stop worth naming.
MIN_STOP = timedelta(minutes=15)


# ── WHAT SOFASCORE'S STOPPED WORDS MEAN, FOR BOTH SOFASCORE WRITERS ──────────
# The doubles/qualifying sweep learned these words one delay at a time (see the
# notes beside its _STOPPED); the singles live poller never read them at all.
# On SP Open 2026-09-15 rain stopped three R32 singles matches, Sofascore
# dropped the "interrupted" events from its live list, and the poller took the
# silence for the end of the match: the score came off the page and none of
# the three ever said Suspended. One list, here, so the two cannot drift again.
SOFA_STOPPED = ("interrupted", "suspended", "willcontinue")
SOFA_SUSPENDED = ("suspended", "willcontinue")


def stop_began(event: dict, prev_snap: Optional[dict], now: datetime) -> datetime:
    """When play on a stopped Sofascore event stopped, as near as we can say.

    The previous snapshot's onset wins: every later read of the same stop
    carries it, so the stored state does not change on each poll. Failing
    that, the feed's `changes` block — it dates the last change and lists what
    changed, and a STATUS change is the stop itself. Failing that, now, which
    can only make a stop look shorter than it is.
    """
    prev = (prev_snap or {}).get("stopped_since")
    if prev:
        try:
            at = datetime.fromisoformat(prev)
            return at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    ch = (event or {}).get("changes") or {}
    ts = ch.get("changeTimestamp")
    if ts and any(str(c).startswith("status") for c in (ch.get("changes") or [])):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return now


def stop_reads_suspended(status: Optional[str], since: Optional[datetime],
                         now: datetime) -> bool:
    """Should a reader be TOLD this stopped match is suspended?

    `suspended` and `willcontinue` say so outright. `interrupted` is the word
    for ANY halt — Cerundolo's three-minute medical timeout (2026-09-07, where
    a "Suspended" badge told everyone play was off for the day) and SP Open's
    afternoon of rain (2026-09-15) alike. What tells them apart is how long it
    lasts, and MIN_STOP is already this module's line between a pause and a
    stop the reader remembers.
    """
    if status in SOFA_SUSPENDED:
        return True
    if status != "interrupted" or since is None:
        return False
    return now - since >= MIN_STOP


# ── "IS ANYTHING ON COURT?" — ESPN's answer, kept here for the Sofascore poller.
# The Sofascore live poller spends a request only while a match is on court,
# and ESPN's scoreboard — already fetched every minute for pick locking, never
# rate-limited — is the free way to know. That signal used to be ESPN WRITING
# live_scores_json; when ESPN became the standby and stopped writing, nothing
# lit the first match of the day and Sofascore idled through a US Open morning
# while reporting itself healthy. ESPN now just SAYS what it sees, here, and
# writes nothing.
_espn_live_seen_at: Optional[float] = None
ESPN_LIVE_FRESH = 240.0   # ESPN polls every 60 s; four misses means it really stopped


def note_espn_live(seen: bool) -> None:
    global _espn_live_seen_at
    if seen:
        import time
        _espn_live_seen_at = time.monotonic()


def espn_sees_live() -> bool:
    import time
    return _espn_live_seen_at is not None and (time.monotonic() - _espn_live_seen_at) <= ESPN_LIVE_FRESH


def note_resumption(match, new_live) -> Optional[datetime]:
    """Track the suspended edges of a match and stamp resumed_at when a REAL
    stop ends. Returns the resumption time when one was stamped.

    Called with the payload about to be written, BEFORE it is assigned, so the
    match still holds the previous one to compare against. started_at is the
    first point of the match and must not move, or a resumed match would lose
    the fact that it began yesterday, which is the whole reason its row is on
    today's sheet.

    playing -> suspended stamps suspended_at, the start of the stop. Only the
    suspended -> playing edge can stamp resumed_at, and only when the stop it
    ends has lasted MIN_STOP: a flap between the writers, or a break between
    sets, comes back within minutes and is nothing to announce. A stop whose
    start was never seen (the flag predates the column) is not trusted either
    — better a row that says "Started at" than one that invents a delay.

    Stamped once per resumption. A match that goes out and comes back twice in
    a day keeps the latest, which is the one its row should be printing.
    """
    was = is_suspended(getattr(match, "live_scores_json", None))
    now_stopped = is_suspended(new_live)
    now = datetime.now(timezone.utc)
    if not was and now_stopped:
        match.suspended_at = now
        return None
    if not was or now_stopped:
        return None
    since = getattr(match, "suspended_at", None)
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    if since is None or now - since < MIN_STOP:
        return None
    match.resumed_at = now
    return now
