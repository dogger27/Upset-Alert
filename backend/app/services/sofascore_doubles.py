"""
Doubles scoring — for matches that have no draw and never will.

WHY THIS IS SEPARATE FROM EVERYTHING ELSE. Doubles is on the order of play but
not in the app's draws, because nobody picks it: there is no bracket, no
predictions, and nothing to score against. ESPN covers neither doubles nor
qualifying, so those rows sat at "scheduled" all day with no score — the one
part of the sheet the page could not bring to life.

Sofascore does cover them. So the result is stored on the SCHEDULE ROW itself,
which is the only record of a doubles match that exists here. Nothing about the
draws changes, and `schedule_entries.match_id` stays null for these rows exactly
as it always has.

WHY SURNAMES, WHEN EVERYTHING ELSE RESOLVES BY ID. Only 19 of 64 doubles player
slots on a real day carried a `sofa_player_id`, because most doubles specialists
are not in a singles draw and so were never stamped. Id-matching cannot carry
this. Surnames can, and decisively: the sheet prints them in CAPITALS
("Sadio DOUMBIA FRA") and Sofascore prints them first ("Doumbia S"), so the
surname is the one token both spell in full. Measured 16/16 on a real day, most
at 4 of 4 — the 3-of-4 cases are only hyphens and diacritics ("Roger-Vasselin",
"Heliövaara").

Matched ONCE and the event id written down, after which everything joins by id
like the rest of the app.
"""

import asyncio
import logging
import re
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.models.schedule import ScheduleEntry, ScheduleEntryPlayer
from app.models.tournament import Draw, Tournament
from app.services.sofascore import SofascoreBlocked, _get
from app.services.sofascore_live import _as_espn_shape, _norm_point, _sets_and_tiebreak
from app.services.sofascore_results import _final_scores
from app.services.system_log import app_log

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60.0

# Three of four surnames. Four is the norm; three is what a hyphen or a
# diacritic costs, and two would start matching a team against a different
# pairing that happens to share a player — which in doubles is common.
_MIN_SURNAMES = 3

# "[WC]", "[2]" and a trailing country code are the sheet's own annotations.
_SHEET_NOISE = re.compile(r"\[[^\]]*\]|\b[A-Z]{3}\b")


def _sheet_surnames(raw_names: list) -> set:
    """Surnames as the ORDER OF PLAY spells them.

    The sheet capitalises the surname and prints given names normally, so the
    all-caps token is the surname. Falls back to the last token for sheets that
    do not capitalise — some smaller events do not.
    """
    out = set()
    for raw in raw_names:
        for part in (raw or "").split("/"):
            part = _SHEET_NOISE.sub(" ", part)
            toks = [t for t in part.split() if len(t) > 2]
            caps = [t for t in toks if t.isupper()]
            out |= {t.lower() for t in (caps or toks[-1:])}
    return out


def _sofa_surnames(team_name: str) -> set:
    """Surnames as SOFASCORE spells them — "Doumbia S / Reboul F"."""
    out = set()
    for side in (team_name or "").split("/"):
        toks = [t for t in side.replace(".", " ").split() if len(t) > 2]
        if toks:
            out.add(toks[0].lower())
    return out


async def _doubles_ids(db, draw: Draw, tournament: Tournament) -> Optional[tuple]:
    """(unique_tournament_id, season_id) for this draw's DOUBLES event.

    Sofascore keeps doubles as its own uniqueTournament — Cincinnati is 2373 /
    2548 for singles and 2381 / 2553 for doubles — so it has to be found rather
    than derived. Searched by the tournament's own name and filtered on both
    "Doubles" in the name and the right tour, because a combined event returns
    an ATP and a WTA doubles entry that are otherwise identical.
    """
    if draw.sofa_doubles_tournament_id and draw.sofa_doubles_season_id:
        return draw.sofa_doubles_tournament_id, draw.sofa_doubles_season_id

    want_cat = {"M": "ATP", "F": "WTA"}.get(draw.gender)
    base = (tournament.name or "").split("(")[0].strip()
    from urllib.parse import quote
    payload = await _get(f"/search/unique-tournaments?q={quote(base)}")
    cand = None
    for row in payload.get("results", []):
        ent = row.get("entity", {})
        name = ent.get("name") or ""
        cat = (ent.get("category") or {}).get("name")
        if "doubles" in name.lower() and cat == want_cat:
            cand = ent.get("id")
            break
    if not cand:
        return None

    seasons = await _get(f"/unique-tournament/{cand}/seasons")
    # `year` is a STRING here, as it is on the singles seasons endpoint.
    season = next((s for s in seasons.get("seasons", [])
                   if str(s.get("year")) == str(draw.year)), None)
    if not season:
        return None

    draw.sofa_doubles_tournament_id = cand
    draw.sofa_doubles_season_id = season["id"]
    await db.commit()
    await app_log("info", "sofascore_doubles",
                  f"Resolved doubles event for {tournament.name} {draw.gender}: "
                  f"ut={cand} season={season['id']}",
                  detail={"draw_id": draw.id})
    return cand, season["id"]


def _snapshot(event: dict) -> dict:
    """The live point state, in the same shape the singles poller produces."""
    home, away = event.get("homeScore") or {}, event.get("awayScore") or {}
    sets, tiebreak = _sets_and_tiebreak(home, away)
    return {
        "sets": sets,
        "point": [_norm_point(home.get("point"), tiebreak),
                  _norm_point(away.get("point"), tiebreak)],
        "tiebreak": tiebreak,
        "serving": event.get("firstToServe") if event.get("firstToServe") in (1, 2) else None,
        "at": datetime.now(timezone.utc).isoformat(),
    }


async def sweep_once(db, day: Optional[date] = None) -> dict:
    """Resolve unmatched doubles rows, then score every one we can."""
    day = day or date.today()

    entries = (await db.execute(
        select(ScheduleEntry).where(
            ScheduleEntry.discipline != "singles",
            ScheduleEntry.play_date == day,
        ))).scalars().all()
    if not entries:
        return {"entries": 0, "resolved": 0, "scored": 0}

    # Draws carry the pointer to the doubles event; a tournament with no tracked
    # draw is not one we follow.
    draws = (await db.execute(
        select(Draw).where(Draw.tournament_id.in_({e.tournament_id for e in entries}),
                           Draw.sofa_tournament_id.isnot(None)))).scalars().all()
    if not draws:
        return {"entries": len(entries), "resolved": 0, "scored": 0}
    tourns = {t.id: t for t in (await db.execute(
        select(Tournament).where(
            Tournament.id.in_({d.tournament_id for d in draws})))).scalars().all()}

    # One events pull per doubles season, shared by every row that needs it.
    by_season, events = {}, []
    for d in draws:
        ids = await _doubles_ids(db, d, tourns.get(d.tournament_id))
        if ids:
            by_season[(d.tournament_id, d.gender)] = ids
    for ut, season in set(by_season.values()):
        for kind in ("last", "next"):
            try:
                payload = await _get(
                    f"/unique-tournament/{ut}/season/{season}/events/{kind}/0")
            except SofascoreBlocked:
                raise
            except Exception as exc:
                logger.warning("doubles %s page failed for ut %s: %s", kind, ut, exc)
                continue
            events += payload.get("events") or []

    players = {}
    for row in (await db.execute(
            select(ScheduleEntryPlayer).where(
                ScheduleEntryPlayer.schedule_entry_id.in_([e.id for e in entries])))).scalars().all():
        players.setdefault(row.schedule_entry_id, []).append(row)

    by_id = {ev["id"]: ev for ev in events}
    resolved = scored = 0

    for e in entries:
        ev = by_id.get(e.sofa_event_id) if e.sofa_event_id else None

        if ev is None:
            ours = _sheet_surnames([p.raw_name for p in players.get(e.id, [])])
            best, best_score = None, 0
            for cand in events:
                theirs = (_sofa_surnames(cand["homeTeam"]["name"])
                          | _sofa_surnames(cand["awayTeam"]["name"]))
                hit = len(ours & theirs)
                if hit > best_score:
                    best, best_score = cand, hit
            if best is None or best_score < _MIN_SURNAMES:
                continue
            e.sofa_event_id = best["id"]
            ev = best
            resolved += 1

        # Which side of OUR row is Sofascore's home team? The sheet's order and
        # theirs need not agree, and getting it backwards would credit the win
        # to the wrong pair.
        a_names = _sheet_surnames([p.raw_name for p in players.get(e.id, []) if p.side == "a"])
        home = _sofa_surnames(ev["homeTeam"]["name"])
        flip = len(a_names & home) < len(a_names & _sofa_surnames(ev["awayTeam"]["name"]))

        status = (ev.get("status") or {}).get("type")
        code = (ev.get("status") or {}).get("code", 100)
        wc = ev.get("winnerCode")

        if status == "inprogress":
            snap = _snapshot(ev)
            if flip:
                snap["sets"] = [[b, a] for a, b in snap["sets"]]
                snap["point"] = [snap["point"][1], snap["point"][0]]
                if snap["serving"] in (1, 2):
                    snap["serving"] = 3 - snap["serving"]
            live = _as_espn_shape(snap)
            if e.live_scores_json != live or e.live_point_json != snap:
                e.live_scores_json = live
                e.live_point_json = snap
                e.status = "live"
                scored += 1
        elif status == "finished" and wc in (1, 2):
            final = _final_scores(ev.get("homeScore") or {}, ev.get("awayScore") or {},
                                  code, wc)
            if final and flip:
                final = [final[1], final[0]]
            side = ("a" if wc == 1 else "b") if not flip else ("b" if wc == 1 else "a")
            if e.scores_json != final or e.winner_side != side:
                e.scores_json = final
                e.winner_side = side
                e.status = "completed"
                e.live_scores_json = None
                e.live_point_json = None
                scored += 1

    if resolved or scored:
        await db.commit()
    return {"entries": len(entries), "resolved": resolved, "scored": scored}


class SofascoreDoublesMonitor:
    """Self-managed loop, in the shape the other two pollers use."""

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

        logger.info("Sofascore doubles sweep started (interval=%ss)", POLL_INTERVAL)
        while not self._stop.is_set():
            delay = POLL_INTERVAL
            try:
                async with AsyncSessionLocal() as db:
                    report = await sweep_once(db)
                    if report.get("resolved") or report.get("scored"):
                        logger.info("Sofascore doubles: %s", report)
                        from app.services import broadcaster
                        for tid in {e for e in
                                    (await db.execute(select(ScheduleEntry.tournament_id)
                                                      .where(ScheduleEntry.play_date == date.today())
                                                      )).scalars().all()}:
                            await broadcaster.publish(tid)
            except SofascoreBlocked as exc:
                delay = self.BLOCKED_BACKOFF
                await app_log("warning", "sofascore_doubles",
                              f"Doubles sweep paused {self.BLOCKED_BACKOFF / 60:.0f}m ({exc})",
                              dedup_key="sofa_doubles_blocked", dedup_hours=1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Sofascore doubles sweep failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass


monitor = SofascoreDoublesMonitor()
