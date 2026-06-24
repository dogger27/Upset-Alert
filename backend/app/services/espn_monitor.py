"""
ESPN Live Score Monitor.

Polls ESPN ATP/WTA scoreboards every 60 seconds. Performs two jobs per cycle:

  JOB 1 — Picks locking (narrow window: start_date ± a few days)
    When a STATUS_IN_PROGRESS match features a player from our draw:
      • Sets picks_locked_at = now  (idempotency guard)
      • Overwrites closing_time = now  (is_locked becomes True immediately)
      • Emails every verified user with picks
      • SSE-broadcasts to connected browsers

  JOB 2 — Live scores (full tournament window)
    When a STATUS_IN_PROGRESS match features both players in our draw:
      • Locates the Match record and writes current set/game scores to live_scores_json
      • Completed tiebreak sets are annotated (e.g. "7(11)") using ESPN's tiebreak field
      • live_scores_json non-null ↔ match is in progress; cleared when match completes

  JOB 3 — Match results (full tournament window)
    When a STATUS_FINAL match features both players in our draw:
      • Locates the pending Match record by player pair lookup
      • Sets winner_id + scores_json (integer set scores only — no tiebreak annotation)
      • Clears live_scores_json
      • Wikipedia will later overwrite scores_json with tiebreak annotations
        when the EventStream or 30-min poll fires — no special handling needed

Name matching reuses _norm() from rankings.py (token-set algebra):
  - Accent / diacritic stripping on both sides
  - Order-independent frozensets (Zheng Qinwen ↔ Qinwen Zheng)
  - Compound surnames and extra name components (subset rules)
  - Nickname variants (Caty ↔ Catherine McNally) via unique-token rule
  - German umlaut expansion mismatch via collapsed-vowel fallback
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.tournament import DrawEntry, Match, Tournament
from app.services.rankings import _norm

logger = logging.getLogger(__name__)

_ESPN_ATP_URL = "http://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard"
_ESPN_WTA_URL = "http://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard"
_ESPN_URLS = {"M": _ESPN_ATP_URL, "F": _ESPN_WTA_URL}

_FILLER = {"open", "the", "powered", "by", "cup", "championships", "masters",
           "international", "tennis", "classic"}

_LOCK_BEFORE_DAYS = 1   # start watching for picks-lock N days before start_date
_LOCK_AFTER_DAYS  = 3   # stop watching N days after start_date
_RESULT_AFTER_DAYS = 16  # keep syncing results up to N days after start_date


# ---------------------------------------------------------------------------
# Name normalisation & token-set matching
# ---------------------------------------------------------------------------

def _tokenize(name: str) -> frozenset:
    return frozenset(_norm(name).split())


def _umlaut_variants(ts: frozenset) -> list:
    """Collapse umlaut expansions: mueller→muller, kjaer→kjar, etc."""
    variants = [ts]
    for src, dst in [("oe", "o"), ("ue", "u"), ("ae", "a")]:
        if any(src in tok for tok in ts):
            alt = frozenset(tok.replace(src, dst) for tok in ts)
            if alt != ts:
                variants.append(alt)
    return variants


def _build_draw_index(entries: list) -> tuple[list, dict]:
    """
    Build matching structures from a list of DrawEntry objects.

    Returns:
        pairs     — [(frozenset_of_tokens, DrawEntry), ...]
        tok_index — {single_token: [DrawEntry, ...]} for unique-token lookup
    """
    pairs: list = []
    tok_index: dict = {}
    for entry in entries:
        if not entry.name:
            continue
        ts = _tokenize(entry.name)
        pairs.append((ts, entry))
        for tok in ts:
            tok_index.setdefault(tok, []).append(entry)
    return pairs, tok_index


def _find_entry(espn_name: str, pairs: list, tok_index: dict) -> Optional[DrawEntry]:
    """
    Return the DrawEntry whose name best matches espn_name, or None.
    Applies Rules 1-4 from rankings.py token-set algebra plus umlaut fallback.
    """
    espn_ts = _tokenize(espn_name)
    if not espn_ts:
        return None

    for variant in _umlaut_variants(espn_ts):
        # Rules 1-3: set algebra (order-independent)
        for player_ts, entry in pairs:
            if variant == player_ts:
                return entry
            if variant < player_ts:          # ESPN name ⊂ our name
                return entry
            if len(player_ts) >= 2 and player_ts < variant:  # our name ⊂ ESPN
                return entry

        # Rule 4: unique identifying token (handles Caty ↔ Catherine McNally)
        for tok in variant:
            hits = tok_index.get(tok, [])
            if len(hits) == 1:
                return hits[0]

    return None


def _player_in_draw(espn_name: str, pairs: list, tok_index: dict) -> bool:
    return _find_entry(espn_name, pairs, tok_index) is not None


# ---------------------------------------------------------------------------
# Tournament name matching
# ---------------------------------------------------------------------------

def _names_match(our_name: str, espn_name: str) -> bool:
    """
    True if our tournament name's significant tokens substantially overlap
    with the ESPN event name. ESPN names often have sponsor prefixes/suffixes.
    """
    our_toks = set(_norm(our_name).split()) - _FILLER
    espn_toks = set(_norm(espn_name).split())
    if not our_toks:
        return False
    overlap = our_toks & espn_toks
    return len(overlap) >= max(1, round(len(our_toks) * 0.6))


# ---------------------------------------------------------------------------
# ESPN API helpers
# ---------------------------------------------------------------------------

async def _fetch_events(gender: str) -> list:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_ESPN_URLS[gender])
            resp.raise_for_status()
            return resp.json().get("events", [])
    except Exception as exc:
        err_msg = str(exc) or type(exc).__name__
        is_network_err = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
        if is_network_err:
            logger.debug("ESPN %s unreachable: %s", gender, exc)
        else:
            logger.warning("ESPN %s fetch failed: %s", gender, exc)
            from app.services.system_log import app_log
            await app_log("error", "espn", f"ESPN {gender} API failed: {err_msg}",
                          {"gender": gender, "error": err_msg, "exc_type": type(exc).__name__},
                          dedup_key=f"espn_api_fail_{gender}", dedup_hours=2)
        return []


def _gender_label(gender: str) -> str:
    return "Men's" if gender == "M" else "Women's"


def _singles_comps(event: dict, gender: str, status: str) -> list:
    """Return competitions with the given status from the correct gender grouping."""
    label = _gender_label(gender)
    comps = []
    for group in event.get("groupings", []):
        gname = group.get("grouping", {}).get("displayName", "")
        if "Singles" not in gname or label not in gname:
            continue
        for comp in group.get("competitions", []):
            if comp.get("status", {}).get("type", {}).get("name", "") == status:
                comps.append(comp)
    return comps


def _comp_live_players(comp: dict) -> list:
    """Full names of all players in a competition."""
    return [
        c.get("athlete", {}).get("fullName", "")
        for c in comp.get("competitors", [])
        if c.get("athlete", {}).get("fullName", "") not in ("", "TBD")
    ]


def _comp_live_scores(comp: dict) -> Optional[tuple]:
    """
    Parse a STATUS_IN_PROGRESS competition.
    Returns (name_a, name_b, scores_a, scores_b) where scores are current
    set/game counts as strings. Completed tiebreak sets are annotated with
    the loser's tiebreak points, e.g. "7(11)", matching the Wikipedia format.
    Returns None if either player is unknown.
    """
    competitors = comp.get("competitors", [])
    if len(competitors) != 2:
        return None
    a, b = competitors[0], competitors[1]
    name_a = a.get("athlete", {}).get("fullName", "")
    name_b = b.get("athlete", {}).get("fullName", "")
    if not name_a or not name_b or "TBD" in (name_a, name_b):
        return None

    sc_a, sc_b = [], []
    for la, lb in zip(a.get("linescores", []), b.get("linescores", [])):
        va = la.get("value")
        vb = lb.get("value")
        if va is None or vb is None:
            continue
        ta = la.get("tiebreak")  # this player's tiebreak points (if set ended in TB)
        tb_v = lb.get("tiebreak")
        if ta is not None and tb_v is not None:
            # Winner shows set score with loser's tiebreak points in parens
            if la.get("winner"):
                sc_a.append(f"{int(va)}({int(tb_v)})")
                sc_b.append(str(int(vb)))
            else:
                sc_a.append(str(int(va)))
                sc_b.append(f"{int(vb)}({int(ta)})")
        else:
            sc_a.append(str(int(va)))
            sc_b.append(str(int(vb)))

    return name_a, name_b, sc_a, sc_b


def _comp_result(comp: dict) -> Optional[tuple]:
    """
    Parse a STATUS_FINAL competition.
    Returns (winner_name, loser_name, winner_set_scores, loser_set_scores)
    where set scores are lists of integer strings e.g. ["6", "4", "7"].
    Returns None if result cannot be reliably determined.
    """
    competitors = comp.get("competitors", [])
    if len(competitors) != 2:
        return None

    winner = next((c for c in competitors if c.get("winner")), None)
    loser  = next((c for c in competitors if not c.get("winner")), None)
    if not winner or not loser:
        return None

    w_name = winner.get("athlete", {}).get("fullName", "")
    l_name = loser.get("athlete", {}).get("fullName", "")
    if not w_name or not l_name or "TBD" in (w_name, l_name):
        return None

    def scores(competitor: dict) -> list:
        return [
            str(int(ls["value"]))
            for ls in competitor.get("linescores", [])
            if ls.get("value") is not None
        ]

    return w_name, l_name, scores(winner), scores(loser)


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class ESPNMonitor:
    def __init__(self):
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("ESPN live monitor started (60s poll interval)")
        while self._running:
            try:
                await self._poll()
            except Exception as exc:
                logger.warning("ESPN monitor poll error: %s", exc)
            await asyncio.sleep(60)

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Poll cycle
    # ------------------------------------------------------------------

    async def _poll(self) -> None:
        today = date.today()

        # Job 1 watchlist: narrow window around start_date for picks locking
        lock_start  = today - timedelta(days=_LOCK_BEFORE_DAYS)
        lock_end    = today + timedelta(days=_LOCK_AFTER_DAYS)

        # Job 2 watchlist: full tournament window for match results
        result_cutoff = today - timedelta(days=_RESULT_AFTER_DAYS)

        async with AsyncSessionLocal() as db:
            lock_res = await db.execute(
                select(Tournament).where(
                    Tournament.picks_locked_at.is_(None),
                    Tournament.draw_released_direct_at.isnot(None),
                    Tournament.status != "completed",
                    Tournament.start_date.isnot(None),
                    Tournament.start_date >= lock_start,
                    Tournament.start_date <= lock_end,
                )
            )
            lock_list = lock_res.scalars().all()

            result_res = await db.execute(
                select(Tournament).where(
                    Tournament.draw_released_direct_at.isnot(None),
                    Tournament.status != "completed",
                    Tournament.start_date.isnot(None),
                    Tournament.start_date >= result_cutoff,
                )
            )
            result_list = result_res.scalars().all()

        # Unique set of tournaments needing attention
        all_ids   = {t.id for t in lock_list} | {t.id for t in result_list}
        by_id     = {t.id: t for t in lock_list + result_list}
        lock_ids  = {t.id for t in lock_list}
        result_ids = {t.id for t in result_list}

        if not all_ids:
            return

        logger.debug(
            "ESPN poll: %d lock-watch, %d result-watch",
            len(lock_ids), len(result_ids),
        )

        atp_events = await _fetch_events("M")
        wta_events = await _fetch_events("F")
        espn_events = {"M": atp_events, "F": wta_events}

        for tid in all_ids:
            tournament = by_id[tid]
            events = espn_events[tournament.gender]

            espn_event = next(
                (e for e in events if _names_match(tournament.name, e.get("name", ""))),
                None,
            )
            if espn_event is None:
                logger.debug(
                    "ESPN: no event match for '%s' (%s)",
                    tournament.name, tournament.gender,
                )
                if tid in lock_ids:
                    from app.services.system_log import app_log
                    await app_log("warning", "espn",
                                  f"No ESPN event found for '{tournament.name}' — picks may not auto-lock",
                                  {"tournament_id": tournament.id, "tournament_name": tournament.name,
                                   "gender": tournament.gender},
                                  dedup_key=f"espn_no_match_{tournament.id}")
                continue

            # Load draw entries once — used by both jobs
            async with AsyncSessionLocal() as db:
                de_res = await db.execute(
                    select(DrawEntry).where(DrawEntry.tournament_id == tid)
                )
                entries = de_res.scalars().all()

            if not entries:
                continue

            pairs, tok_index = _build_draw_index(entries)

            # Job 1: picks locking
            if tid in lock_ids:
                await self._check_lock(tournament, espn_event, pairs, tok_index)

            # Job 2: live scores
            if tid in result_ids:
                await self._sync_live(tournament, espn_event, pairs, tok_index)

            # Job 3: match results
            if tid in result_ids:
                n = await self._sync_results(tournament, espn_event, pairs, tok_index)
                if n:
                    logger.info(
                        "ESPN: updated %d match result(s) for %d %s",
                        n, tournament.year, tournament.name,
                    )

    # ------------------------------------------------------------------
    # Job 1: picks locking
    # ------------------------------------------------------------------

    async def _check_lock(
        self,
        tournament: Tournament,
        espn_event: dict,
        pairs: list,
        tok_index: dict,
    ) -> None:
        live_comps = _singles_comps(espn_event, tournament.gender, "STATUS_IN_PROGRESS")
        trigger_name = None
        for comp in live_comps:
            for name in _comp_live_players(comp):
                if _player_in_draw(name, pairs, tok_index):
                    trigger_name = name
                    break
            if trigger_name:
                break

        if trigger_name:
            logger.info(
                "ESPN LIVE MATCH DETECTED — %d %s (%s): '%s' is in progress",
                tournament.year, tournament.name, tournament.gender, trigger_name,
            )
            await self._on_match_start(tournament.id, trigger_name)

    async def _on_match_start(self, tournament_id: int, trigger_name: str) -> None:
        from app.services import broadcaster
        from app.services.notifications import notify_match_start

        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as db:
            tournament = await db.get(Tournament, tournament_id)
            if tournament is None or tournament.picks_locked_at is not None:
                return  # already handled (race guard)

            tournament.picks_locked_at = now
            tournament.closing_time = now
            name, year, tid = tournament.name, tournament.year, tournament.id
            await db.commit()

        await broadcaster.publish(tournament_id)

        asyncio.create_task(notify_match_start(tid, name, year))
        logger.info(
            "Picks locked: %d %s — trigger: %s",
            year, name, trigger_name,
        )

    # ------------------------------------------------------------------
    # Job 2: live scores
    # ------------------------------------------------------------------

    async def _sync_live(
        self,
        tournament: Tournament,
        espn_event: dict,
        pairs: list,
        tok_index: dict,
    ) -> None:
        """
        For every STATUS_IN_PROGRESS match where both players are in our draw,
        write current set/game counts to live_scores_json.
        Also clears live_scores_json for any draw match that is no longer in progress
        (e.g. it just finished and _sync_results hasn't fired yet, or it was abandoned).
        Broadcasts if anything changed.
        """
        live_comps = _singles_comps(espn_event, tournament.gender, "STATUS_IN_PROGRESS")

        # Map (entry_id_a, entry_id_b) → (scores_a, scores_b) for in-progress matches
        in_progress: dict[tuple, tuple] = {}
        for comp in live_comps:
            result = _comp_live_scores(comp)
            if not result:
                continue
            name_a, name_b, sc_a, sc_b = result
            entry_a = _find_entry(name_a, pairs, tok_index)
            entry_b = _find_entry(name_b, pairs, tok_index)
            if not entry_a or not entry_b or entry_a.id == entry_b.id:
                continue
            in_progress[(entry_a.id, entry_b.id)] = (sc_a, sc_b)
            in_progress[(entry_b.id, entry_a.id)] = (sc_b, sc_a)

        async with AsyncSessionLocal() as db:
            m_res = await db.execute(
                select(Match).where(
                    Match.tournament_id == tournament.id,
                    Match.winner_id.is_(None),
                    Match.player1_id.isnot(None),
                    Match.player2_id.isnot(None),
                    Match.is_bye == False,
                )
            )
            pending = m_res.scalars().all()
            changed = 0

            for m in pending:
                key = (m.player1_id, m.player2_id)
                live = in_progress.get(key)
                if live:
                    new_val = [live[0], live[1]]
                    if m.live_scores_json != new_val:
                        m.live_scores_json = new_val
                        changed += 1
                elif m.live_scores_json is not None:
                    # Match was live but no longer in ESPN's in-progress list
                    m.live_scores_json = None
                    changed += 1

            if changed:
                await db.commit()
                from app.services import broadcaster
                await broadcaster.publish(tournament.id)

    # ------------------------------------------------------------------
    # Job 3: match results
    # ------------------------------------------------------------------

    async def _sync_results(
        self,
        tournament: Tournament,
        espn_event: dict,
        pairs: list,
        tok_index: dict,
    ) -> int:
        """
        For every STATUS_FINAL singles competition whose players are in our draw,
        update the corresponding pending Match record with winner + set scores.
        Returns the number of matches updated.

        Score format stored: [["6","4","7"], ["3","6","6"]]
        Wikipedia will later refine to: [["6","4","7(5)"], ["3","6","6(7)"]]
        when it rewrites scores_json on its next scrape. No special handling needed —
        the Wikipedia scraper always overwrites scores_json unconditionally.
        """
        final_comps = _singles_comps(espn_event, tournament.gender, "STATUS_FINAL")
        if not final_comps:
            return 0

        updated = 0
        rounds_updated: set[int] = set()
        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as db:
            # Load pending matches (both players known, no winner yet, not a bye)
            m_res = await db.execute(
                select(Match).where(
                    Match.tournament_id == tournament.id,
                    Match.winner_id.is_(None),
                    Match.player1_id.isnot(None),
                    Match.player2_id.isnot(None),
                    Match.is_bye == False,
                )
            )
            pending = m_res.scalars().all()
            if not pending:
                return 0

            # Index by both player-ID orderings for O(1) lookup
            by_players: dict[tuple, Match] = {}
            for m in pending:
                by_players[(m.player1_id, m.player2_id)] = m
                by_players[(m.player2_id, m.player1_id)] = m

            for comp in final_comps:
                result = _comp_result(comp)
                if not result:
                    continue

                w_name, l_name, w_scores, l_scores = result

                w_entry = _find_entry(w_name, pairs, tok_index)
                l_entry = _find_entry(l_name, pairs, tok_index)
                if not w_entry or not l_entry:
                    continue  # players not in our draw (qualifiers, etc.)
                if w_entry.id == l_entry.id:
                    continue  # name collision — skip rather than corrupt

                match = by_players.get((w_entry.id, l_entry.id))
                if not match:
                    continue  # match not found (wrong round / players not set yet)

                # Align scores to player1/player2 bracket order
                if match.player1_id == w_entry.id:
                    match.scores_json = [w_scores, l_scores]
                else:
                    match.scores_json = [l_scores, w_scores]

                match.winner_id = w_entry.id
                match.status = "completed"
                match.completed_at = now
                match.live_scores_json = None  # clear live indicator
                updated += 1
                rounds_updated.add(match.round_number)

            if updated:
                await db.commit()
                from app.services import broadcaster
                await broadcaster.publish(tournament.id)

                # Check whether any of the rounds we just wrote results into
                # are now fully complete; if so, fire round-standings emails.
                for rn in rounds_updated:
                    incomplete = await db.execute(
                        select(func.count()).where(
                            Match.tournament_id == tournament.id,
                            Match.round_number == rn,
                            Match.is_bye == False,
                            Match.winner_id.is_(None),
                        )
                    )
                    if incomplete.scalar_one() == 0:
                        from app.services.notifications import notify_round_complete
                        asyncio.create_task(notify_round_complete(tournament.id, rn))
                        logger.info("Round %d complete for tournament %d — notification queued", rn, tournament.id)

                # Check whether the whole tournament is now complete
                total_incomplete = await db.execute(
                    select(func.count()).where(
                        Match.tournament_id == tournament.id,
                        Match.is_bye == False,
                        Match.winner_id.is_(None),
                    )
                )
                if total_incomplete.scalar_one() == 0:
                    from app.services.notifications import notify_tournament_complete
                    asyncio.create_task(notify_tournament_complete(tournament.id))
                    logger.info("Tournament %d fully complete — completion notification queued", tournament.id)

        return updated
