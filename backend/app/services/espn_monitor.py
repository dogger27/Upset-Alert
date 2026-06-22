"""
ESPN Live Score Monitor.

Polls ESPN ATP/WTA scoreboards every 60 seconds while tournaments have their
draw released but picks not yet locked. The moment a main-draw match is
confirmed in-progress (ESPN STATUS_IN_PROGRESS + player found in our draw):
  1. Writes picks_locked_at = now        — idempotency guard, prevents re-fire
  2. Overwrites closing_time = now       — makes is_locked True immediately
  3. Emails every user who has picks     — via Resend
  4. SSE-broadcasts to open browsers    — via broadcaster pub/sub

Name matching reuses _norm() from rankings.py (battle-tested against thousands
of real player names from Tennis Explorer). Token-set algebra handles:
  - Accents / diacritics stripped on both sides
  - Name-order variants (Zheng Qinwen ↔ Qinwen Zheng)
  - Compound surnames (Auger-Aliassime, Davidovich Fokina)
  - Nickname variants (Caty ↔ Catherine McNally) via unique-token rule
  - German umlaut expansion mismatch (müller→mueller vs muller) via fallback
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.tournament import DrawEntry, Tournament
from app.services.rankings import _norm

logger = logging.getLogger(__name__)

_ESPN_ATP_URL = "http://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard"
_ESPN_WTA_URL = "http://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard"
_ESPN_URLS = {"M": _ESPN_ATP_URL, "F": _ESPN_WTA_URL}

# Words stripped from tournament names before overlap scoring.
_FILLER = {"open", "the", "powered", "by", "cup", "championships", "masters",
           "international", "tennis", "classic"}

# How close to start_date we begin watching (days before / after).
_WATCH_BEFORE_DAYS = 1
_WATCH_AFTER_DAYS = 3


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
    Returns:
        all_sets  — list of per-player token frozensets
        tok_index — single token → list of player frozensets containing it
                    (used for unique-token Rule 4)
    """
    all_sets: list = []
    tok_index: dict = {}
    for entry in entries:
        if not entry.name:
            continue
        ts = _tokenize(entry.name)
        all_sets.append(ts)
        for tok in ts:
            tok_index.setdefault(tok, []).append(ts)
    return all_sets, tok_index


def _player_in_draw(espn_name: str, all_sets: list, tok_index: dict) -> bool:
    espn_ts = _tokenize(espn_name)
    if not espn_ts:
        return False

    for espn_variant in _umlaut_variants(espn_ts):
        # Rule 1: exact token set (order-independent — handles Zheng Qinwen)
        # Rule 2: espn ⊂ our player (our name has extra components)
        # Rule 3: our player ⊂ espn (espn name has extra components, |ours| ≥ 2)
        for player_ts in all_sets:
            if espn_variant == player_ts:
                return True
            if espn_variant < player_ts:
                return True
            if len(player_ts) >= 2 and player_ts < espn_variant:
                return True

        # Rule 4: unique identifying token (handles Caty ↔ Catherine McNally)
        for tok in espn_variant:
            hits = tok_index.get(tok, [])
            if len(hits) == 1:
                return True

    return False


# ---------------------------------------------------------------------------
# Tournament name matching
# ---------------------------------------------------------------------------

def _names_match(our_name: str, espn_name: str) -> bool:
    """
    True if our tournament name's significant tokens are substantially contained
    in the ESPN event name. ESPN names often have extra sponsor prefixes/suffixes.
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
        logger.warning("ESPN %s fetch failed: %s", gender, exc)
        return []


def _live_players(event: dict, gender: str) -> list:
    """
    Return full names of players in STATUS_IN_PROGRESS singles competitions
    for the given gender grouping.
    """
    gender_label = "Men's" if gender == "M" else "Women's"
    players = []
    for group in event.get("groupings", []):
        gname = group.get("grouping", {}).get("displayName", "")
        if "Singles" not in gname or gender_label not in gname:
            continue
        for comp in group.get("competitions", []):
            state = comp.get("status", {}).get("type", {}).get("name", "")
            if state != "STATUS_IN_PROGRESS":
                continue
            for c in comp.get("competitors", []):
                name = c.get("athlete", {}).get("fullName", "")
                if name and name != "TBD":
                    players.append(name)
    return players


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

    async def _poll(self) -> None:
        today = date.today()
        window_start = today - timedelta(days=_WATCH_BEFORE_DAYS)
        window_end = today + timedelta(days=_WATCH_AFTER_DAYS)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Tournament).where(
                    Tournament.picks_locked_at.is_(None),
                    Tournament.draw_released_direct_at.isnot(None),
                    Tournament.status != "completed",
                    Tournament.start_date.isnot(None),
                    Tournament.start_date >= window_start,
                    Tournament.start_date <= window_end,
                )
            )
            watchlist = result.scalars().all()

        if not watchlist:
            return

        logger.debug("ESPN poll: watching %d tournament(s)", len(watchlist))

        # Fetch both scoreboards once per cycle regardless of how many tournaments
        atp_events = await _fetch_events("M")
        wta_events = await _fetch_events("F")
        espn_events = {"M": atp_events, "F": wta_events}

        for tournament in watchlist:
            await self._check_tournament(tournament, espn_events[tournament.gender])

    async def _check_tournament(self, tournament: Tournament, events: list) -> None:
        # Step 1: find the matching ESPN event by name
        espn_event = next(
            (e for e in events if _names_match(tournament.name, e.get("name", ""))),
            None,
        )
        if espn_event is None:
            logger.debug("ESPN: no event match for '%s' (%s)", tournament.name, tournament.gender)
            return

        # Step 2: get in-progress player names for our gender grouping
        live = _live_players(espn_event, tournament.gender)
        if not live:
            return

        # Step 3: load our draw and build the matching index
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DrawEntry).where(DrawEntry.tournament_id == tournament.id)
            )
            entries = result.scalars().all()

        if not entries:
            return

        all_sets, tok_index = _build_draw_index(entries)

        # Step 4: check each live player against our draw
        trigger_name = next(
            (n for n in live if _player_in_draw(n, all_sets, tok_index)),
            None,
        )
        if trigger_name is None:
            return

        logger.info(
            "ESPN LIVE MATCH DETECTED — %d %s (%s): '%s' is in progress",
            tournament.year, tournament.name, tournament.gender, trigger_name,
        )
        await self._on_match_start(tournament.id, trigger_name)

    async def _on_match_start(self, tournament_id: int, trigger_name: str) -> None:
        from app.models.prediction import UserPrediction
        from app.models.user import User
        from app.services import broadcaster
        from app.services.email import send_match_start_notification

        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as db:
            tournament = await db.get(Tournament, tournament_id)
            if tournament is None or tournament.picks_locked_at is not None:
                return  # already handled (race guard)

            tournament.picks_locked_at = now
            tournament.closing_time = now  # replace the hardcoded estimate

            result = await db.execute(
                select(User.email).join(
                    UserPrediction, UserPrediction.user_id == User.id
                ).where(
                    UserPrediction.tournament_id == tournament_id,
                    User.email_verified == True,
                ).distinct()
            )
            emails = [row[0] for row in result.all()]

            name = tournament.name
            year = tournament.year
            tid = tournament.id
            await db.commit()

        # SSE push first — browsers refresh immediately
        await broadcaster.publish(tournament_id)

        # Email
        if emails:
            await send_match_start_notification(emails, name, year, tid)
            logger.info(
                "Picks locked: %d %s — notified %d user(s), trigger player: %s",
                year, name, len(emails), trigger_name,
            )
        else:
            logger.info(
                "Picks locked: %d %s — no verified users with picks to notify",
                year, name,
            )
