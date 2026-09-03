"""
Sofascore live-score polling — the point score ESPN structurally cannot give us.

WHAT THIS ADDS AND WHAT IT DOES NOT TOUCH. ESPN remains the source of record for
who is playing, who won, and when a match started or finished. This service
writes exactly one column, `matches.sofa_live_json`, and nothing else. It never — plus, since the score-history
feature, one INSERT per score change into match_score_snapshots (see
services/score_history.py); that insert rides this poller's own commit
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
import time
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.models.tournament import Draw, DrawEntry, Match
from app.services.sofascore import SofascoreBlocked, _get
from app.services.system_log import app_log
from app.services.live_state import note_resumption
from app.services.settings import sofa_authoritative

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

# How long a match may be absent from the live list before we accept it is
# gone. Comfortably longer than a set break, which is what the absence usually
# is, and short enough that a match which vanished without a result does not sit
# there all evening.
GONE_AFTER = 180.0

# Readers treat a snapshot older than this as stale and fall back to ESPN.
# Comfortably more than POLL_INTERVAL so an ordinary late response does not
# flicker the UI, comfortably less than a game so nothing lingers when we stop.
FRESH_SECONDS = 45
# FRESHNESS IS A PROPERTY OF THE SOURCE, NOT OF TENNIS. 45s suits this poller,
# which refreshes every 10s and re-stamps at FRESH_SECONDS/2. Rows scored by
# the sofascore_doubles SWEEP — qualifying singles and every doubles — are
# refreshed once per sweep, nominally 60s and about 88s in practice, so a 45s
# window blacked out every one of them for half of each cycle, together: on a
# US Open qualifying morning all eleven live scores vanished and returned in
# lockstep, which reads as an outage rather than as a quiet moment. Two full
# sweeps of headroom keeps a genuinely dead feed from lingering while never
# punishing a row for its source's cadence.
ENTRY_FRESH_SECONDS = 180


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


# ── ONE SOURCE AT A TIME ──────────────────────────────────────────────────
# Sofascore is the primary scoring feed; espn_monitor is the standby. While
# this poller is healthy the standby writes nothing, so the two can never
# disagree in the database. "Healthy" is measured, not assumed: a cycle that
# reached the feed (or found nothing on court, which is not a failure) within
# FEED_STALE_AFTER seconds, and no circuit breaker open. A ban opens the breaker and
# hands over at once; the timer is for silent failures — a hung connection, a
# dead network. FIVE MINUTES, BY THE USER'S DECISION: ESPN carries game scores
# only, no points, so handing over on a brief stall trades the point-by-point
# feed for a coarser one. A stall that long is an outage; anything shorter is
# worth waiting out.
FEED_STALE_AFTER = 300.0
# Healthy from process start: the standby's first cycle runs before this
# poller's first cycle lands, and one cycle of ESPN writing at every boot is
# exactly the two-writer overlap this exists to end. The grace period is the
# same five minutes — the poller's first cycle lands within one or two.
_last_ok = time.monotonic()


def _mark_ok() -> None:
    global _last_ok
    _last_ok = time.monotonic()


def live_feed_healthy() -> bool:
    """Is the Sofascore live feed delivering right now? False hands scoring to
    the standby (see espn_monitor._poll), True takes it back."""
    from app.services.sofascore import blocked_for
    if blocked_for() > 0:
        return False
    return (time.monotonic() - _last_ok) <= FEED_STALE_AFTER


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


def _sets_and_tiebreak(home: dict, away: dict) -> tuple[list, bool, bool]:
    """Per-set games, whether the CURRENT set is a tiebreak, and whether that
    tiebreak is a MATCH tiebreak standing in for a whole set.

    Sofascore numbers sets period1..period5. The current set is the highest one
    present; a tiebreak in progress shows periodNTieBreak alongside it.

    A match tiebreak — the first-to-ten doubles play instead of a deciding set —
    arrives in the same shape as a set and is not one. There are no games in it,
    so the running POINT COUNT goes in the period itself: an 8-7 tiebreak
    reports as a period of 8-7. Rendered as a set that says a pair won eight
    games, which is not a score tennis can produce.
    A SET tiebreak is always played AT six games all, so its period reads 6-6
    and the count lives in periodNTieBreak. That is the entire difference
    between the two, and it is what the test below reads.
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
    match_tb = False
    if current_tb and sets:
        a, b = sets[-1]
        try:
            at_six_all = int(a) == 6 and int(b) == 6
        except (TypeError, ValueError):
            # Unreadable rather than not-6-6. Leaving the set in place is the
            # behaviour that predates this, and a wrong SET is a smaller error
            # than dropping a real one.
            at_six_all = True
        if not at_six_all:
            match_tb = True
            sets.pop()
    return sets, current_tb, match_tb


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
    sets, tiebreak, match_tb = _sets_and_tiebreak(home, away)
    return {
        "sets": sets,
        "point": [_norm_point(home.get("point"), tiebreak),
                  _norm_point(away.get("point"), tiebreak)],
        "tiebreak": tiebreak,
        "match_tiebreak": match_tb,
        "serving": _serving(event.get("firstToServe"), sets),
        "at": datetime.now(timezone.utc).isoformat(),
    }


def _older_than(stamp, seconds: float) -> bool:
    """Whether an ISO stamp is missing, unreadable, or older than `seconds`.

    Missing and unreadable both count as old: the caller is deciding whether to
    refresh something, and refreshing a value it cannot read is the safe answer.
    """
    if not stamp:
        return True
    try:
        at = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - at).total_seconds() > seconds


def renderable_history(snap: dict) -> Optional[dict]:
    """A stored history snapshot in the shape the schedule renderer reads.

    renderable_point with its freshness and finished guards removed — a history
    row is BY DEFINITION not fresh, that being the point — and the `at` stamp
    kept, because the popup labels each slider position with when the score
    stood that way. It delegates to the same body, so the judgement rules
    cannot drift into a second copy, which is that helper's whole doctrine.
    """
    if not snap or not snap.get("sets"):
        return None
    out = _render_snapshot(snap)
    out["at"] = snap.get("at")
    if snap.get("source") == "espn":
        # _render_snapshot fills a missing point with love-all, which is right
        # for Sofascore — a fresh snapshot with no point is a match between
        # games. ESPN publishes GAME COUNTS ONLY and never a point, so the same
        # blank means "unknown", and 0-0 would be a score it never reported.
        out["point"] = None
    return out


def renderable_point(snap: Optional[dict], finished: bool,
                     max_age: float = None) -> Optional[dict]:
    """The point score a reader should draw from this snapshot, or None.

    ONE copy of these rules, because they are judgement calls rather than
    formatting and every surface has to make the same ones — the schedule
    showing a different score from the draw for the same match is exactly the
    bug this prevents. It lived in two places until the doubles copy quietly
    missed a field the singles copy had gained, which is how that goes.

    Three reasons to return nothing:

    * No snapshot. The normal case: no poller, or nothing on court.
    * Stale. A point is the most perishable thing on the page — 40-30 becomes a
      new game in seconds, and one sitting beside a set score that has moved on
      reads as a bug in the bracket rather than as old data. Enforced here,
      server-side, rather than trusted to whatever the client last received.
    * The match is over. The poller clears its own snapshot when an event leaves
      the live list, but a result can be recorded first, and in that gap the
      honest answer is that the match has finished.

    `games` travels with `point` so callers can render one coherent state
    instead of splicing two feeds: taking games from ESPN and the point from
    here produces states that never existed, because ESPN lags up to 60s.
    """
    if not snap or finished:
        return None
    # Play stopped: the games and the point are BOTH the last true state —
    # the score the match will resume from. The row says "Suspended" beside
    # them, so nothing here implies the ball is in play.
    if snap.get("suspended"):
        out = _render_snapshot(snap)
        if out is not None:
            out["suspended"] = True
        return out
    try:
        at = datetime.fromisoformat(snap["at"])
    except (KeyError, TypeError, ValueError):
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - at).total_seconds() > (max_age or FRESH_SECONDS):
        return None

    # BETWEEN GAMES SOFASCORE SENDS NO POINT AT ALL, and this used to return
    # None on that alone — so the score blinked out for a few seconds after
    # every single game and came back for the next one. A gap that opens and
    # closes a dozen times a set reads as something broken, not as an absence.
    # The snapshot is fresh, which means the match is being played, and the
    # score between two games is love all — _render_snapshot says so.
    return _render_snapshot(snap)


def _render_snapshot(snap: dict) -> dict:
    """The formatting half, shared by renderable_point and renderable_history."""
    point = [p if p is not None else "0"
             for p in (snap.get("point") or [None, None])]

    sets = snap.get("sets") or []
    games = [[str(s[0]) if s and s[0] is not None else "" for s in sets],
             [str(s[1]) if s and s[1] is not None else "" for s in sets]]
    return {"point": point,
            "games": games if sets else None,
            "tiebreak": bool(snap.get("tiebreak")),
            # Every set in `games` is FINISHED when this is set — the one being
            # played is the tiebreak, and it is deliberately not in the list.
            # Without this a renderer leaves the last completed set unmarked,
            # because "last set present" is how it knows which one is live.
            "match_tiebreak": bool(snap.get("match_tiebreak")),
            "serving": snap.get("serving")}


def live_point_for(match) -> Optional[dict]:
    """The renderable point for a BRACKET match — singles, which has a draw row."""
    return renderable_point(getattr(match, "sofa_live_json", None),
                            getattr(match, "winner_id", None) is not None)


def _as_espn_shape(snap: dict) -> Optional[list]:
    """A Sofascore snapshot in live_scores_json's shape.

    [p1 games, p2 games, serving, set winners] — the format espn_monitor writes
    and every renderer already understands. Writing this rather than teaching
    the readers a second format is the whole point of promoting.
    """
    sets = (snap or {}).get("sets") or []
    p1 = [str(s[0]) if s and s[0] is not None else "" for s in sets]
    p2 = [str(s[1]) if s and s[1] is not None else "" for s in sets]
    if not p1:
        return None
    # Every set but the one in play is decided, and the higher count took it.
    # In a match tiebreak there is no set in play — the tiebreak is not in this
    # list — so every one of them is decided.
    live_idx = -1 if (snap or {}).get("match_tiebreak") else len(p1) - 1
    wins = [None if i == live_idx else (int(p1[i] or 0) > int(p2[i] or 0))
            for i in range(len(p1))]
    return [p1, p2, (snap or {}).get("serving"), wins]


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
    # WHICH MATCHES CHANGED, for anything that needs the edge rather than the
    # state. touched_draws is deliberately coarse — it feeds an SSE nudge that
    # tells a page to refetch — but a Live Activity pushes one match's score to
    # one Lock Screen and cannot refetch anything, so it needs to know exactly
    # which. Collected on the same branches, so it inherits the same "only when
    # something really changed" guarantee.
    changed_matches: set = set()
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

        # WHEN THE FIRST POINT WAS PLAYED — not when the match was scheduled.
        #
        # `startTimestamp` is the announced slot, not the start of play. It came
        # back as exactly 17:00:00.000 for a match the sheet listed as "not
        # before 1:00 PM", which is the same fact the row already showed. Putting
        # that behind the words "Started at" states something the feed does not
        # know: a match on a "not before" slot routinely begins much later.
        #
        # So the stamp is OUR first sighting of play, which at a 10-second poll
        # is within ten seconds of the first point. That is also what
        # espn_monitor records, so the two sources stay comparable.
        #
        # The exception is joining a match already in progress — after a deploy,
        # or on the first poll of the day. Games already on the board prove it
        # started before we looked, and "now" would be a worse answer than the
        # scheduled time, so the announced stamp is used there instead.
        played = sum((s[0] or 0) + (s[1] or 0) for s in (snap.get("sets") or []))
        if match.sofa_started_at is None or (
                sofa_authoritative() and match.started_at is None):
            ts = ev.get("startTimestamp")
            if played == 0:
                first_play = datetime.now(timezone.utc)
            elif ts:
                first_play = datetime.fromtimestamp(ts, tz=timezone.utc)
            else:
                first_play = None
            if first_play is not None:
                # Written once. A suspension and resumption must not restart the
                # clock — the elapsed time is what the expected-start chain
                # reads, and a match paused for rain has been on court since it
                # began.
                if match.sofa_started_at is None:
                    match.sofa_started_at = first_play
                    written += 1
                    touched_draws.add(draw_id)
                    changed_matches.add(match.id)
                if sofa_authoritative() and match.started_at is None:
                    match.started_at = first_play
                    written += 1
                    touched_draws.add(draw_id)

        # Compare without the timestamp: otherwise every poll is a write, and at
        # 10s that is 8,640 pointless UPDATEs and SSE broadcasts a day.
        #
        # BUT THE STAMP STILL HAS TO BE REFRESHED before it is read as stale,
        # and this is where that went wrong. Readers discard a snapshot older
        # than FRESH_SECONDS, and `at` only moved when the content did — so a
        # match where nothing changed simply aged out. Nothing changes for a
        # surprisingly long time: between games Sofascore sends no point at all,
        # and across a changeover that is ninety seconds in which the games, the
        # server and the point are all exactly what they were. The score
        # vanished off a match that was plainly still being played, and came
        # back when the next point landed.
        #
        # The two facts had been collapsed into one field. "When this state last
        # CHANGED" is what the comparison needs; "when we last CONFIRMED it" is
        # what freshness needs, and it is the second one that answers "is this
        # still true". Refreshing at half the freshness window keeps the stamp
        # honest at 2 writes a minute for a live match instead of 6 — the saving
        # the comparison was for, without the lie.
        before = dict(match.sofa_live_json or {})
        prev_at = before.pop("at", None)
        after = dict(snap)
        after.pop("at", None)
        if before != after or _older_than(prev_at, FRESH_SECONDS / 2):
            match.sofa_live_json = snap
            written += 1
            touched_draws.add(draw_id)
            changed_matches.add(match.id)
            # HISTORY, on the content-change half of this condition ONLY. The
            # stamp-refresh half fires every 22.5s per idle live match and would
            # bank thousands of identical rows a day; a change is one row per
            # point, which is the timeline the popup's slider scrubs. First
            # sighting lands here too — `before` is {} then. Wrapped so a
            # history failure can never cost the score write it rides beside.
            if before != after:
                try:
                    from app.services.score_history import record_snapshot
                    record_snapshot(db, match.id, snap)
                except Exception:
                    logger.exception("score history insert failed for match %s",
                                     match.id)

        # Same promotion as the results sweep: when Sofascore is the record,
        # espn_monitor stands by (it writes nothing while live_feed_healthy())
        # and live_scores_json would sit frozen at whatever it last said.
        # Everything that renders a live score reads that column, so it has to
        # be the one that moves.
        if sofa_authoritative():
            live = _as_espn_shape(snap)
            # A blank snapshot never replaces a real one — see _has_sets in
            # sofascore_doubles for why an in-progress match can report no
            # periods at all, and what writing that through looks like on the
            # page (the score vanishing, then returning a moment later).
            blank_now = not (snap or {}).get("sets")
            had_before = bool((match.live_scores_json or [[], []])[0])
            if (not blank_now or not had_before) and match.live_scores_json != live:
                # Before the assignment, while the old payload is still there
                # to compare against — see note_resumption.
                note_resumption(match, live)
                match.live_scores_json = live
                written += 1
                touched_draws.add(draw_id)
                changed_matches.add(match.id)

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
        if m.player1_id in live_ids and m.player2_id in live_ids:
            continue

        # MISSING FROM ONE POLL IS NOT THE SAME AS OVER, and treating it that
        # way is what put "Scheduled" on a match in its third set. Sofascore
        # drops an event out of the live list between sets and puts it back a
        # few seconds later; clearing on the first absence blanked the score,
        # and with an expected start still on the row the draw had nothing left
        # to call it but not-yet-started.
        #
        # Two things end a match, and neither of them is silence. A result is
        # the real one — the sweep records a winner and this clears on the next
        # poll. The other is an event that simply never comes back, and the
        # snapshot's own stamp already dates that: it is refreshed every time we
        # see the match, so a stamp three minutes old means three minutes of not
        # seeing it, which no set break lasts.
        #
        # Nothing is left showing a stale POINT in the meantime — that has its
        # own, much shorter freshness rule, and 45 seconds of silence retires it
        # while the set score stays up. Which is the right split: a set score
        # from a minute ago is still true, and a point from a minute ago is not.
        if m.winner_id is None and not _older_than(
                (m.sofa_live_json or {}).get("at"), GONE_AFTER):
            continue

        m.sofa_live_json = None
        written += 1
        touched_draws.add(m.draw_id)
        # THE END OF A MATCH IS A CHANGE TOO, and the only signal there is that
        # one is over — nothing anywhere emits "this match finished", the live
        # column is simply cleared. Without this an activity would sit on a
        # Lock Screen showing the last score for ever.
        changed_matches.add(m.id)
        # Clear the promoted copy too, or a finished match keeps showing a
        # live score for ever — exactly what staging did.
        if sofa_authoritative() and m.live_scores_json is not None:
            m.live_scores_json = None

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
        # BOTH ids, because subscribers are split across them — see
        # broadcaster.publish. The draw page keys on the draw id and would
        # otherwise never see a Sofascore nudge at all.
        "draw_ids": sorted(touched_draws),
        "changed_matches": sorted(changed_matches),
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

    from app.core.config import settings

    if settings.sofascore_live_force:
        # Staging, where espn_monitor is not running and the signal below is a
        # frozen copy. Still requires a draw worth polling for, so this does not
        # become an unconditional loop against an empty tour calendar.
        row = (await db.execute(
            select(Draw.id).where(
                Draw.sofa_tournament_id.isnot(None),
                Draw.status != "completed",
            ).limit(1))).first()
        return row is not None

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
        # Healthy from the first tick: the standby must not write in the seconds
        # before this loop's first cycle lands.
        _mark_ok()
        while not self._stop.is_set():
            delay = POLL_INTERVAL
            started = asyncio.get_running_loop().time()
            try:
                async with AsyncSessionLocal() as db:
                    if not await _anything_on_court(db):
                        delay = self.IDLE_INTERVAL
                        _mark_ok()          # nothing to fetch is not a failure
                    else:
                        report = await poll_once(db)
                        state.consecutive_errors = 0
                        _mark_ok()
                        if report["written"]:
                            # Only publish when something actually changed —
                            # poll_once already suppresses no-op writes, so this
                            # is one SSE frame per real score change.
                            from app.services import broadcaster
                            for tid in report.get("tournament_ids") or []:
                                await broadcaster.publish(tid)
                            for did in report.get("draw_ids") or []:
                                await broadcaster.publish(did)
                            # SYNCHRONOUS, AND IT MUST STAY THAT WAY. This adds
                            # match ids to an in-process set and returns; the
                            # dispatcher is a separate task. Awaiting a push
                            # here would put a round trip to Cupertino inside
                            # this loop and delay every score on the site.
                            from app.services import live_activity
                            live_activity.enqueue(report.get("changed_matches"))
            except SofascoreBlocked as exc:
                # The FLOOR, not the answer: the breaker escalates a repeat
                # block up to six hours, and waking every half hour into one
                # only refills the log. Sleep until it actually reopens.
                from app.services.sofascore import blocked_for
                delay = max(self.BLOCKED_BACKOFF, blocked_for() + 30)
                await app_log(
                    "warning", "sofascore_live",
                    # Stable sentence: the minutes and the reason vary every
                    # step of the backoff, and putting them in the text made
                    # one outage read as a dozen problems in triage.
                    "Live polling paused — Sofascore refused the request",
                    detail={"paused_minutes": round(delay / 60),
                            "reason": str(exc)},
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
                # THE INTERVAL IS THE CYCLE, NOT THE GAP. The fetch through the
                # residential proxy takes ~1.3 s and the writes a little more;
                # sleeping the full interval on top made the real cycle ~11.5 s,
                # and every one of those seconds was Lock Screen lag. Sleep the
                # remainder, so a 10 s interval polls every 10 s — the same
                # request rate the number always promised. Backoffs and the
                # idle gap are left exactly as they were.
                if delay == POLL_INTERVAL:
                    elapsed = asyncio.get_running_loop().time() - started
                    delay = max(1.0, POLL_INTERVAL - elapsed)
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass


monitor = SofascoreLiveMonitor()
