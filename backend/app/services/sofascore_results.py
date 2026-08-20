"""
Sofascore match RESULTS — the half the live feed structurally cannot provide.

WHY A SECOND ENDPOINT AT ALL. `/sport/tennis/events/live` carries no
`winnerCode` and only in-progress statuses (codes 8/9/10 = 1st/2nd/3rd set), and
a match **disappears from it the instant it ends**. A poller watching only that
feed sees matches vanish and can never record who won. So results come from
`/unique-tournament/{ut}/season/{s}/events/last/{page}`, which returns finished
events with `winnerCode`, full per-set scores including tiebreaks, and a real
`startTimestamp`.

WHY THIS WRITES SHADOW COLUMNS AND NOTHING ELSE. `espn_monitor` is the only
writer of `winner_id` / `completed_at` / `scores_json` / `started_at`; eighteen
other modules read them — scoring, standings, pick locking, notifications, H2H,
upsets. That makes the eventual cutover a one-writer swap, but it also means a
wrong winner does not render badly: it scores the league wrong and emails
everyone about it, and the notification dedup tables mean a bad send cannot be
un-sent. So this writes `sofa_*` beside the real columns, changes nothing a user
can see, and earns its promotion by being diffed against ESPN over a full
tournament. `scripts/sofa_diff.py` is that report.

WHY THE CADENCE IS MINUTES, NOT SECONDS. A result is final — being 90 seconds
late to record it costs nothing, whereas a point score is worthless at 60s. One
request per tracked draw per cycle, against one shared request for every live
match, so the whole system stays around 6.4 req/min.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.models.tournament import Draw, DrawEntry, Match
from app.services.sofascore import SofascoreBlocked, _get
from app.services.sofascore_live import _event_player_ids, _tracked
from app.services.system_log import app_log

logger = logging.getLogger(__name__)

# How often to sweep for results. Minutes, not seconds — see the module note.
POLL_INTERVAL = 180.0

# Pages of finished events to walk per draw. 30 per page, and a 96-draw event
# has 95 matches, so 4 pages covers a completed Masters with room to spare.
# Walked newest-first and stopped early once a page yields nothing new.
MAX_PAGES = 4

_FINISHED = "finished"

# Sofascore's status codes for a match that ended without being played out.
# The feed carries these plainly; an earlier version of this file looked only at
# status.type == "finished" and discarded the code, which silently turned every
# retirement into a clean straight-sets win. Seven of them in one tournament.
_RETIRED = 92
_WALKOVER = 91
# type == "canceled", so it never reaches the finished branch — listed for the
# reader, because "no winnerCode" is a legitimate outcome rather than a gap.
_CANCELED = 70


def _aware(dt):
    """SQLite returns datetimes naive; treat them as the UTC they were stored as.

    Needed anywhere a stored timestamp is COMPARED with a computed one. The two
    are otherwise never equal for the same instant, which is silent: no error,
    just a write that repeats for ever.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _games(cell) -> Optional[int]:
    """Game count from a score cell, ignoring any tiebreak annotation."""
    if not cell:
        return None
    head = str(cell).split("(")[0].rstrip("r")
    return int(head) if head.isdigit() else None


def _final_scores(home: dict, away: dict, status_code: int = 100,
                  winner_code: Optional[int] = None) -> Optional[list]:
    """Per-set games as scores_json shape: [[p1 cells], [p2 cells]].

    BOTH sides carry their tiebreak count — "7(7)-6(3)", not "7-6(3)".

    That is what is already stored: diffing 174 matches against ESPN produced 63
    "differences" of which the overwhelming majority were only this, because the
    first version here annotated the loser alone. Nothing was wrong with either
    scoreline; they were two spellings of the same result. Matching the stored
    spelling is what makes a Sofascore result and a Wikipedia-scraped one
    indistinguishable downstream, which is the entire point of writing this
    shape rather than inventing one.
    """
    p1, p2 = [], []
    for n in range(1, 6):
        a, b = home.get(f"period{n}"), away.get(f"period{n}")
        if a is None and b is None:
            continue
        ta, tb = home.get(f"period{n}TieBreak"), away.get(f"period{n}TieBreak")
        ca, cb = str(a if a is not None else ""), str(b if b is not None else "")
        if ta is not None:
            ca = f"{ca}({ta})"
        if tb is not None:
            cb = f"{cb}({tb})"
        p1.append(ca)
        p2.append(cb)

    # A walkover was never played, so there are no games at all.
    # The WINNER's cell carries "w/o" — read off what is actually stored, not
    # off the comment in the frontend, which states the opposite. Match 4805:
    # O'Connell won by walkover and ESPN put "w/o" on HIS cell. It reads as "won
    # by walkover", which is also how the bracket's badge renders.
    if status_code == _WALKOVER:
        if winner_code == 1:
            return [["w/o"], [""]]
        if winner_code == 2:
            return [[""], ["w/o"]]
        return None

    if not p1:
        return None

    # A retirement marks the set the loser QUIT IN with a trailing "r", on that
    # player's own cell — "6-1 3-0r" means the second player retired at 0 games
    # in the second set. The bracket renders its "ret." badge off exactly this,
    # so dropping it turns a retirement into a straight-sets win.
    #
    # status_code alone is NOT enough. Sofascore flagged only 5 of the 7
    # retirements ESPN recorded here; Fucsovics-Atmane and O'Connell-Ruud both
    # came back code=100 "Ended" despite finishing 1-3 and 7-5 1-2. Nobody wins
    # a match by those scores, so an incomplete scoreline is itself the evidence
    # and is used as a second, independent signal.
    retired = status_code == _RETIRED
    if not retired and winner_code in (1, 2):
        # Sets the declared winner actually took. A completed best-of-3 needs
        # two; anything less means the match stopped early.
        won = sum(1 for a, b in zip(p1, p2)
                  if _games(a) is not None and _games(b) is not None
                  and ((_games(a) > _games(b)) == (winner_code == 1)))
        # Deliberately < 2 rather than a per-format threshold: a best-of-5 that
        # ended at two sets would be missed, which is a gap rather than a wrong
        # answer. Cincinnati and every non-Slam draw is best-of-3.
        retired = won < 2

    if retired and winner_code in (1, 2):
        loser = p2 if winner_code == 1 else p1
        if loser and loser[-1] != "":
            loser[-1] = f"{loser[-1]}r"

    return [p1, p2]


async def sweep_once(db) -> dict:
    """One pass over every tracked draw's finished events.

    Returns a report rather than logging per match; at this cadence a per-match
    line would still be thousands of lines a week for nothing.
    """
    by_tournament, by_player = await _tracked(db)
    if not by_tournament:
        return {"draws": 0, "seen": 0, "written": 0, "unmatched": 0}

    # Is there anything left to find? A draw whose every playable match already
    # carries a Sofascore verdict has nothing new until another match finishes,
    # and a COMPLETED tournament never will. Without this the sweep kept pulling
    # four pages per draw every three minutes forever — about 1.7 GB/month of
    # requests that could only return what we already had, which is more traffic
    # than the live poller uses.
    pending = (await db.execute(
        select(Match.id).where(
            Match.draw_id.in_(list(by_tournament.values())),
            Match.is_bye == False,                                  # noqa: E712
            Match.player1_id.isnot(None), Match.player2_id.isnot(None),
            Match.sofa_winner_id.is_(None),
        ).limit(1))).first()
    if pending is None:
        return {"draws": len(by_tournament), "seen": 0, "written": 0,
                "unmatched": 0, "skipped": "all tracked matches resolved"}

    seen = written = unmatched = 0
    touched_draws: set = set()
    now = datetime.now(timezone.utc)

    # Page 0 is the 30 most recently finished events, which is far more than a
    # tournament produces in three minutes. Deeper pages exist to backfill on
    # first run or after downtime, so they are walked only when page 0 turns up
    # something new — a page that adds nothing means we have caught up.
    for (ut_id, season_id), draw_id in by_tournament.items():
        for page in range(MAX_PAGES):
            try:
                payload = await _get(
                    f"/unique-tournament/{ut_id}/season/{season_id}/events/last/{page}")
            except SofascoreBlocked:
                raise
            except Exception as exc:
                logger.warning("results page %s for draw %s failed: %s",
                               page, draw_id, exc)
                break

            events = payload.get("events") or []
            if not events:
                break

            page_wrote = 0
            for ev in events:
                if (ev.get("status") or {}).get("type") != _FINISHED:
                    continue
                seen += 1

                home_ids = _event_player_ids(ev.get("homeTeam") or {})
                away_ids = _event_player_ids(ev.get("awayTeam") or {})
                p1 = next((by_player[i] for i in home_ids if i in by_player), None)
                p2 = next((by_player[i] for i in away_ids if i in by_player), None)
                if not p1 or not p2:
                    # A qualifying or doubles event inside the same season, or a
                    # player we never stamped. Counted, not guessed at.
                    unmatched += 1
                    continue

                match = (await db.execute(
                    select(Match).where(
                        Match.draw_id == draw_id,
                        Match.player1_id.in_([p1, p2]),
                        Match.player2_id.in_([p1, p2]),
                    ))).scalars().first()
                if match is None:
                    unmatched += 1
                    continue

                code = ev.get("winnerCode")
                if code not in (1, 2):
                    continue
                # winnerCode is home/away; the bracket has its own player order.
                # Resolve through the entry ids rather than positionally, or a
                # match stored the other way round records the wrong winner —
                # the single most damaging thing this file could get wrong.
                sofa_winner = p1 if code == 1 else p2

                status_code = (ev.get("status") or {}).get("code", 100)
                home_sc = ev.get("homeScore") or {}
                away_sc = ev.get("awayScore") or {}
                scores = _final_scores(home_sc, away_sc, status_code, code)
                if scores and match.player1_id == p2:
                    scores = [scores[1], scores[0]]

                start_ts = ev.get("startTimestamp")
                started = (datetime.fromtimestamp(start_ts, tz=timezone.utc)
                           if start_ts else None)

                changed = False
                if match.sofa_winner_id != sofa_winner:
                    match.sofa_winner_id = sofa_winner
                    changed = True
                if scores and match.sofa_scores_json != scores:
                    match.sofa_scores_json = scores
                    changed = True
                # Compared through _aware, because these two are never equal
                # otherwise: SQLite hands the stored value back NAIVE while the
                # freshly computed one carries UTC, so the same instant compares
                # unequal and every sweep rewrote all 175 rows and committed for
                # nothing. Same trap that killed the order-of-play ingest in
                # _absorb — see services/schedule.py.
                if started and _aware(match.sofa_started_at) != started:
                    match.sofa_started_at = started
                    changed = True
                # First observation only — this is "when we noticed", and
                # re-stamping it on every sweep would destroy the one thing it
                # is for: comparing how quickly each source reports a result.
                if match.sofa_completed_at is None:
                    match.sofa_completed_at = now
                    changed = True

                # PROMOTE into the real columns when Sofascore is the source of
                # record. This is the "one writer, not eighteen consumers"
                # cutover: scoring, standings, Hall of Fame, locking, H2H and
                # upsets all read winner_id / scores_json directly, and none of
                # them can be reached by a shim at the API layer.
                #
                # Only matches we actually HAVE a result for are touched, which
                # is what keeps byes correct: a bye has no Sofascore event and
                # never will, so its scraper-set winner is left exactly alone.
                # Blanking those was what put TBD through the whole bracket.
                if settings.sofascore_authoritative:
                    if match.winner_id != sofa_winner:
                        match.winner_id = sofa_winner
                        changed = True
                    if scores and match.scores_json != scores:
                        match.scores_json = scores
                        changed = True
                    if started and _aware(match.started_at) != started:
                        match.started_at = started
                        changed = True
                    if match.completed_at is None:
                        match.completed_at = now
                        changed = True
                    if match.status != "completed":
                        match.status = "completed"
                        changed = True

                if changed:
                    written += 1
                    page_wrote += 1
                    touched_draws.add(draw_id)

            if written:
                await db.commit()
            # Pages run newest-first, so page 0 holds the most recent results.
            # If it taught us nothing, no deeper page can either — new results
            # are by definition recent. Previously this only broke from page 1
            # onward, so a steady state still cost two pages per draw per sweep
            # to learn nothing twice.
            if page_wrote == 0:
                break

    # A recorded winner is the single most visible thing this service does, and
    # without a nudge the browser would not learn about it until its next poll —
    # two minutes on the draw page, and never on the schedule page, which has no
    # interval at all. Keyed by tournament, which is what the broadcaster uses.
    if touched_draws:
        from app.services import broadcaster
        from app.services.sofascore_live import _tournament_of
        for tid in {_tournament_of[d] for d in touched_draws if d in _tournament_of}:
            await broadcaster.publish(tid)

    return {"draws": len(by_tournament), "seen": seen,
            "written": written, "unmatched": unmatched}


class SofascoreResultsMonitor:
    """Self-managed sweep loop, in espn_monitor's shape."""

    BLOCKED_BACKOFF = 1800.0

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

        logger.info("Sofascore results sweep started (interval=%ss)", POLL_INTERVAL)
        while not self._stop.is_set():
            delay = POLL_INTERVAL
            try:
                async with AsyncSessionLocal() as db:
                    report = await sweep_once(db)
                    if report["written"]:
                        logger.info("Sofascore results: %s", report)
            except SofascoreBlocked as exc:
                delay = self.BLOCKED_BACKOFF
                await app_log(
                    "warning", "sofascore_results",
                    f"Results sweep paused {self.BLOCKED_BACKOFF / 60:.0f}m — "
                    f"Sofascore refused the request ({exc})",
                    dedup_key="sofa_results_blocked", dedup_hours=1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Sofascore results sweep failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass


monitor = SofascoreResultsMonitor()
