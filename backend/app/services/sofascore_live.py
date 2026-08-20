"""
Sofascore live-score polling — the point score ESPN structurally cannot give us.

WHAT THIS ADDS AND WHAT IT DOES NOT TOUCH. ESPN remains the source of record for
who is playing, who won, and when a match started or finished. This service
writes exactly one column, `matches.sofa_live_json`, and nothing else. It never
sets winner_id, completed_at, live_scores_json or picks_locked_at. That boundary
is deliberate: ESPN has been reliable for singles, and a second writer competing
for the same fields is how two sources become one bug.

WHY THE TOURNAMENT FILTER COMES FIRST, AND WHY PLAYER IDS ALONE ARE A TRAP.
The obvious implementation joins live events to our draws on the stamped
`sofa_player_id`. It is wrong, and it fails in a way that looks like success.
Measured against a real capture on 2026-08-20, four live events matched our
players and ALL FOUR were somebody else's match:

    Cincinnati, USA, Doubles      ut=2553   -> a doubles event, not our singles draw
    Quebec City, Canada           ut=36840  -> players who LOST at Cincinnati and
    Quebec City, Canada, Doubles  ut=36837     flew to the next tournament

A player belongs to our draw permanently; they are only playing *our* match some
of the time. So the (uniqueTournament, season) pair we stamped on the draw is
checked first, and player identity is resolved only inside an event that already
belongs to us. Without that, a Quebec City game score renders on the Cincinnati
bracket and nothing anywhere reports an error.

WHY POINTS ARE NOT ALWAYS POINTS. `homeScore.point` is a STRING whose meaning
depends on context. In a normal game it is "0"/"15"/"30"/"40"/"A". In a tiebreak
it is the raw tiebreak count — "2", "4", "7". Rendering the latter as a game
score shows "2-4" as though someone were losing 15-30. The set's own
`periodNTieBreak` fields are what disambiguate, so they are read rather than
guessed at from the value.

WHY DOUBLES NEEDS subTeams. In singles `homeTeam.id` IS the player id we
stamped. In doubles it is a PAIR id with the two real player ids nested under
`subTeams`. Our tracked draws are singles, so the tournament filter already
excludes doubles events — but the resolver handles both, because the filter is
the thing protecting us and a resolver that silently matches nothing would hide
the day that assumption changes.

SILENCE IS THE FAILURE MODE THAT MATTERS. The reference implementation of this
same API went stale for 26 days without erroring; nothing failed, data just
stopped. For live scores that is the worst available outcome, because a frozen
score looks exactly like a slow match. Hence `_State`, which records the last
successful poll so a watchdog can alarm on staleness rather than on exceptions.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.models.tournament import Draw, DrawEntry, Match
from app.services.sofascore import SofascoreBlocked, _get
from app.services.system_log import app_log

logger = logging.getLogger(__name__)

# Every live tennis match on earth arrives in one response — ITF, UTR,
# challengers, doubles. One request therefore covers every draw we track, no
# matter how many, which is what keeps this at 6 requests/minute rather than
# 6 per match. Measured payload: ~11 KB gzipped quiet, ~30 KB busy.
_LIVE_PATH = "/sport/tennis/events/live"

# A point score has to be fresh to be worth showing. At 60s — espn_monitor's
# cadence — it would sit on 15-30 for an entire game and contradict the set
# score beside it, which is worse than showing no point at all.
POLL_INTERVAL = 10.0

# Readers treat a snapshot older than this as stale and fall back to ESPN.
# Comfortably more than POLL_INTERVAL so an ordinary late response does not
# flicker the UI, comfortably less than a game so nothing lingers when we stop.
FRESH_SECONDS = 45


class _State:
    """Last-success bookkeeping, so staleness can be alarmed on directly.

    An exception counter would not catch the failure that actually happened to
    the reference implementation: requests kept succeeding and simply stopped
    containing anything.
    """

    def __init__(self) -> None:
        self.last_poll_at: Optional[datetime] = None
        self.last_match_seen_at: Optional[datetime] = None
        self.consecutive_errors = 0


state = _State()

# draw_id -> tournament_id, refreshed by _tracked on every poll. Held here
# rather than re-queried at publish time because the broadcaster is keyed by
# tournament and the poller works in draws.
_tournament_of: dict = {}


def _norm_point(raw, tiebreak: bool) -> Optional[str]:
    """The point as it should be displayed, or None when there is nothing to show.

    Sofascore sends "0" for both "no points yet" and "love". They render the
    same, so no distinction is attempted — but None (field absent) does mean
    something different and is preserved.
    """
    if raw is None:
        return None
    s = str(raw)
    if tiebreak:
        return s
    # Guard the documented domain. Anything else is new behaviour rather than a
    # value to pass through to a template.
    return s if s in ("0", "15", "30", "40", "A", "AD") else None


def _sets_and_tiebreak(home: dict, away: dict) -> tuple[list, bool]:
    """Per-set games for both players, plus whether the CURRENT set is a tiebreak.

    Sofascore numbers sets period1..period5. The current set is the highest one
    present; a tiebreak in progress shows periodNTieBreak alongside it.
    """
    sets = []
    current_tb = False
    for n in range(1, 6):
        key = f"period{n}"
        if key not in home and key not in away:
            continue
        sets.append([home.get(key), away.get(key)])
        tb_key = f"{key}TieBreak"
        # Only the LAST set present can be the one being played, so the flag is
        # overwritten rather than or-ed: a completed earlier tiebreak must not
        # make the current game read as one.
        current_tb = tb_key in home or tb_key in away
    return sets, current_tb


def _serving(first_to_serve: Optional[int], sets: list) -> Optional[int]:
    """Who is serving RIGHT NOW. `firstToServe` already is that, despite the name.

    It is not the match's first server, and applying espn_monitor's game-parity
    inference on top of it is wrong — that was the first implementation here and
    it named the wrong player on every odd-numbered game.

    Three consecutive captures of Paul vs Cobolli settle it. The field flips
    with each completed game rather than staying fixed for the match:

        games=0 (even) -> firstToServe=2
        games=1 (odd)  -> firstToServe=1
        games=2 (even) -> firstToServe=2

    Sofascore has already done the parity. `sets` is therefore unused and kept
    only so the signature still documents what the answer depends on — if this
    ever has to be derived again, that is the input it needs.
    """
    return first_to_serve if first_to_serve in (1, 2) else None


def _event_player_ids(team: dict) -> set:
    """The Sofascore PLAYER ids on one side.

    Singles: the team id is the player. Doubles: the team id is a pair, and the
    players are in subTeams — reading the pair id there would match nothing.
    """
    subs = team.get("subTeams")
    if subs:
        return {s["id"] for s in subs if s.get("id")}
    return {team["id"]} if team.get("id") else set()


def _snapshot(event: dict) -> dict:
    """One internally-consistent live state, built from a single response."""
    home = event.get("homeScore") or {}
    away = event.get("awayScore") or {}
    sets, tiebreak = _sets_and_tiebreak(home, away)
    return {
        "sets": sets,
        "point": [_norm_point(home.get("point"), tiebreak),
                  _norm_point(away.get("point"), tiebreak)],
        "tiebreak": tiebreak,
        "serving": _serving(event.get("firstToServe"), sets),
        "at": datetime.now(timezone.utc).isoformat(),
    }


async def _tracked(db) -> tuple[dict, dict]:
    """((unique_tournament_id, season_id) -> draw_id, sofa_player_id -> entry_id).

    The player map is scoped to draws we actually track, so an id that only
    exists in some other draw cannot resolve.
    """
    draw_rows = (await db.execute(
        select(Draw.id, Draw.sofa_tournament_id, Draw.sofa_season_id,
               Draw.tournament_id).where(
            Draw.sofa_tournament_id.isnot(None),
            Draw.sofa_season_id.isnot(None),
            Draw.status != "completed",
        ))).all()
    by_tournament = {(r[1], r[2]): r[0] for r in draw_rows}
    # The SSE broadcaster is keyed by TOURNAMENT, not draw — same as
    # espn_monitor — so keep the mapping needed to publish.
    _tournament_of.clear()
    _tournament_of.update({r[0]: r[3] for r in draw_rows})
    if not by_tournament:
        return {}, {}

    entry_rows = (await db.execute(
        select(DrawEntry.sofa_player_id, DrawEntry.id).where(
            DrawEntry.draw_id.in_(list(by_tournament.values())),
            DrawEntry.sofa_player_id.isnot(None),
        ))).all()
    return by_tournament, {r[0]: r[1] for r in entry_rows}


async def poll_once(db) -> dict:
    """One request, then write a snapshot for every tracked match that is live.

    Returns a small report rather than logging per match — at a 10s cadence,
    per-poll logging would bury everything else in the file.
    """
    by_tournament, by_player = await _tracked(db)
    if not by_tournament:
        return {"tracked_draws": 0, "live": 0, "written": 0, "skipped_other": 0}

    payload = await _get(_LIVE_PATH)
    state.last_poll_at = datetime.now(timezone.utc)
    events = payload.get("events") or []

    ours, skipped_other = [], 0
    for ev in events:
        ut = (ev.get("tournament") or {}).get("uniqueTournament") or {}
        key = (ut.get("id"), (ev.get("season") or {}).get("id"))
        if key in by_tournament:
            ours.append((ev, by_tournament[key]))
        elif _event_player_ids(ev.get("homeTeam") or {}) & set(by_player):
            # A player of ours, in someone else's event. Counted because it is
            # the exact case a player-id-only join would have got wrong, and a
            # count is how we would notice the filter regressing.
            skipped_other += 1

    written, seen_matches = 0, 0
    touched_draws: set = set()
    for ev, draw_id in ours:
        home_ids = _event_player_ids(ev.get("homeTeam") or {})
        away_ids = _event_player_ids(ev.get("awayTeam") or {})
        p1 = next((by_player[i] for i in home_ids if i in by_player), None)
        p2 = next((by_player[i] for i in away_ids if i in by_player), None)
        if not p1 or not p2:
            continue

        match = (await db.execute(
            select(Match).where(
                Match.draw_id == draw_id,
                Match.player1_id.in_([p1, p2]),
                Match.player2_id.in_([p1, p2]),
            ))).scalars().first()
        if match is None:
            continue
        seen_matches += 1

        snap = _snapshot(ev)
        # The bracket stores player1/player2 in its own order, which need not be
        # Sofascore's home/away. Flip the pairs rather than the ids so the
        # snapshot always reads in the match's own orientation.
        if match.player1_id == p2:
            snap["sets"] = [[b, a] for a, b in snap["sets"]]
            snap["point"] = [snap["point"][1], snap["point"][0]]
            if snap["serving"] in (1, 2):
                snap["serving"] = 3 - snap["serving"]

        # Compare without the timestamp: otherwise every poll is a write, and at
        # 10s that is 8,640 pointless UPDATEs and SSE broadcasts a day.
        before = dict(match.sofa_live_json or {})
        before.pop("at", None)
        after = dict(snap)
        after.pop("at", None)
        if before != after:
            match.sofa_live_json = snap
            written += 1
            touched_draws.add(draw_id)

    if seen_matches:
        state.last_match_seen_at = datetime.now(timezone.utc)

    # Clear anything we are still holding a snapshot for that is no longer live,
    # so a finished match does not keep showing 40-30 for ever.
    live_ids = set()
    for ev, draw_id in ours:
        home_ids = _event_player_ids(ev.get("homeTeam") or {})
        away_ids = _event_player_ids(ev.get("awayTeam") or {})
        p1 = next((by_player[i] for i in home_ids if i in by_player), None)
        p2 = next((by_player[i] for i in away_ids if i in by_player), None)
        if p1 and p2:
            live_ids |= {p1, p2}
    stale = (await db.execute(
        select(Match).where(
            Match.draw_id.in_(list(by_tournament.values())),
            Match.sofa_live_json.isnot(None),
        ))).scalars().all()
    for m in stale:
        if m.player1_id not in live_ids or m.player2_id not in live_ids:
            m.sofa_live_json = None
            written += 1
            touched_draws.add(m.draw_id)

    if written:
        await db.commit()
    return {
        "tracked_draws": len(by_tournament),
        "live": len(ours),
        "matches": seen_matches,
        "written": written,
        "skipped_other": skipped_other,
        # Tournament ids, because that is what the SSE broadcaster is keyed by.
        "tournament_ids": sorted({_tournament_of[d] for d in touched_draws
                                  if d in _tournament_of}),
    }


async def _anything_on_court(db) -> bool:
    """Does a tracked draw have a match ESPN currently calls live?

    This is the gate that decides whether to spend a request at all, and it is
    what keeps the daily volume honest. Polling a 10s loop around the clock is
    8,640 requests a day whether or not a ball is being hit; gating on ESPN —
    which is already running, already free, and never blocked — means zero
    requests overnight, zero between tournaments, and zero out of season.

    ESPN is the trigger rather than Sofascore itself because asking Sofascore
    "is anything live?" costs exactly the request we are trying to avoid.

    Deliberately also true while WE still hold a snapshot: the last poll of a
    match has to happen after ESPN has stopped calling it live, or the final
    point score would stay on screen for ever.
    """
    from sqlalchemy import or_

    row = (await db.execute(
        select(Match.id)
        .join(Draw, Draw.id == Match.draw_id)
        .where(
            Draw.sofa_tournament_id.isnot(None),
            Draw.status != "completed",
            or_(Match.live_scores_json.isnot(None),
                Match.sofa_live_json.isnot(None)),
        ).limit(1))).first()
    return row is not None


class SofascoreLiveMonitor:
    """Self-managed poll loop, in the shape espn_monitor already established.

    Off unless SOFASCORE_LIVE_ENABLED is set, so deploying this code changes
    nothing until an instance opts in — staging first, production only once it
    has been watched.
    """

    IDLE_INTERVAL = 60.0        # nothing on court: just re-check the cheap gate
    BLOCKED_BACKOFF = 1800.0    # matches the service's own circuit breaker

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        from app.database import AsyncSessionLocal

        logger.info("Sofascore live poller started (interval=%ss)", POLL_INTERVAL)
        while not self._stop.is_set():
            delay = POLL_INTERVAL
            try:
                async with AsyncSessionLocal() as db:
                    if not await _anything_on_court(db):
                        delay = self.IDLE_INTERVAL
                    else:
                        report = await poll_once(db)
                        state.consecutive_errors = 0
                        if report["written"]:
                            # Only publish when something actually changed —
                            # poll_once already suppresses no-op writes, so this
                            # is one SSE frame per real score change.
                            from app.services import broadcaster
                            for tid in report.get("tournament_ids") or []:
                                await broadcaster.publish(tid)
            except SofascoreBlocked as exc:
                delay = self.BLOCKED_BACKOFF
                await app_log(
                    "warning", "sofascore_live",
                    f"Live polling paused for {self.BLOCKED_BACKOFF / 60:.0f} "
                    f"minutes — Sofascore refused the request ({exc})",
                    dedup_key="sofa_live_blocked", dedup_hours=1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state.consecutive_errors += 1
                logger.warning("Sofascore live poll failed: %s", exc)
                # Only escalate once it is persistent — a single timeout in a
                # loop that runs six times a minute is noise.
                if state.consecutive_errors in (30, 300):
                    await app_log(
                        "error", "sofascore_live",
                        f"Sofascore live polling has failed "
                        f"{state.consecutive_errors} times in a row",
                        detail={"error": str(exc)[:300]},
                        dedup_key="sofa_live_errors", dedup_hours=6)
                delay = min(POLL_INTERVAL * state.consecutive_errors, 300.0)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass


monitor = SofascoreLiveMonitor()
