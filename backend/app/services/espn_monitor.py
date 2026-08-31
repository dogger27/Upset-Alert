"""
ESPN Live Score Monitor.

Polls ESPN ATP/WTA scoreboards every 60 seconds. Performs two jobs per cycle:

  JOB 1 — Picks locking (narrow window: start_date ± a few days)
    When a STATUS_IN_PROGRESS match features a player from our draw:
      • Sets picks_locked_at = now  — this is what actually closes picks and
        flips the draw Open -> Active (Draw.is_locked / computed_status)
      • Overwrites closing_time = now, so the displayed lock time matches the
        moment play really started rather than the schedule table's estimate
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
from app.models.tournament import DrawEntry, Match, Draw, LOCK_LEAD_DAYS
from app.services.rankings import _norm
from app.services.live_state import note_resumption

logger = logging.getLogger(__name__)

_ESPN_ATP_URL = "http://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard"
_ESPN_WTA_URL = "http://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard"
_ESPN_URLS = {"M": _ESPN_ATP_URL, "F": _ESPN_WTA_URL}

_FILLER = {"open", "the", "powered", "by", "cup", "championships", "masters",
           "international", "tennis", "classic"}

# Picks-lock watch window, relative to start_date. The LEAD bound is the one
# that matters: a main-draw match cannot be under way days before the draw
# starts, so ESPN claiming otherwise means we have the wrong event, not an
# early start. It was 3 days, and that is exactly how 2026 Canadian Open
# (start Aug 3) locked on Jul 31 off a Washington match. Keep it equal to the
# allowance in Draw.computed_status, which accepts a pre-start lock only within
# 1 day — one venue far enough east can genuinely begin the UTC evening before.
_LOCK_LEAD_DAYS  = LOCK_LEAD_DAYS  # accept a lock at most N days BEFORE start_date
_LOCK_TRAIL_DAYS = 1    # keep watching N days AFTER start_date
_RESULT_AFTER_DAYS = 16  # keep syncing results up to N days after start_date
# How far ahead to start reading the published order of play. The deadline only
# matters until the first ball, and ESPN publishes day 1's times the evening
# before, so three days is comfortably early without widening the picks-lock
# window (_LOCK_LEAD_DAYS), which is deliberately tight for a different reason.
_SCHEDULE_LEAD_DAYS = 3

# Minimum player-set Jaccard for a name/city-independent event match. Our field
# and the ESPN event's singles field must be largely the SAME set of players.
# Observed: the real event scores ~0.6; a concurrent Grand Slam that merely
# contains most of a small draw's players scores <0.1 (huge non-overlap), so a
# 0.25 floor separates them with a wide margin.
_PLAYER_MATCH_MIN_JACCARD = 0.25


# ---------------------------------------------------------------------------
# Name normalisation & token-set matching
# ---------------------------------------------------------------------------

def _espn_snapshot(live_val):
    """An ESPN live row in the snapshot shape the history endpoint reads.

    live_scores_json is [p1_games, p2_games, serving, p1_set_wins, "suspended"?]
    with games as strings; a snapshot wants sets as [[p1, p2], ...] pairs.

    `point` is None and honestly so: ESPN publishes GAME counts only, never the
    point within the game. The renderer already treats a missing point as
    nothing to draw, so an ESPN-sourced timeline scrubs game by game where a
    Sofascore one scrubs point by point — coarser, and the whole difference
    between a slider and no slider for these matches.
    """
    a, b = live_val[0] or [], live_val[1] or []
    sets = []
    for i in range(max(len(a), len(b))):
        pa = a[i] if i < len(a) else None
        pb = b[i] if i < len(b) else None
        sets.append([int(pa) if str(pa).isdigit() else pa,
                     int(pb) if str(pb).isdigit() else pb])
    return {
        "sets": sets,
        "point": None,
        "tiebreak": False,
        "match_tiebreak": False,
        "serving": live_val[2] if len(live_val) > 2 else None,
        "at": datetime.now(timezone.utc).isoformat(),
        # Read by renderable_history to suppress the point cell entirely. A
        # Sofascore snapshot with no point means "between games, love all";
        # this one means the feed has no points to give, and rendering 0-0
        # would put a score on screen ESPN never reported.
        "source": "espn",
    }


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

def _player_names_equal(a: str, b: str) -> bool:
    """Same player, allowing for spelling. ESPN writes 'Dino Prizmic' where
    Wikipedia writes 'Dino Prizmic\u0107'; _norm already strips accents and
    punctuation, so surname plus first initial is enough to identify one player
    inside a single 128-slot draw, and is far safer than exact equality."""
    ta, tb = _norm(a).split(), _norm(b).split()
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    return ta[-1] == tb[-1] and ta[0][:1] == tb[0][:1]


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


def _venue_city(event: dict) -> str:
    """City portion of an ESPN event's venue, e.g. 'Båstad' from 'Båstad, Sweden'."""
    disp = event.get("venue", {}).get("displayName", "")
    return disp.split(",")[0].strip()


def _build_name_index(names: list) -> tuple[list, dict]:
    """Like _build_draw_index but over plain name strings (for the ESPN side)."""
    pairs: list = []
    tok_index: dict = {}
    for nm in names:
        if not nm:
            continue
        ts = _tokenize(nm)
        pairs.append((ts, nm))
        for tok in ts:
            tok_index.setdefault(tok, []).append(nm)
    return pairs, tok_index


def _event_singles_players(event: dict, gender: str) -> list:
    """Unique full names of every singles player in the event for this gender."""
    label = _gender_label(gender)
    names: list = []
    seen: set = set()
    for group in event.get("groupings", []):
        gname = group.get("grouping", {}).get("displayName", "")
        if "Singles" not in gname or label not in gname:
            continue
        for comp in group.get("competitions", []):
            for c in comp.get("competitors", []):
                nm = c.get("athlete", {}).get("fullName", "")
                if nm and nm != "TBD" and nm not in seen:
                    seen.add(nm)
                    names.append(nm)
    return names


def _player_jaccard(entries: list, event: dict, gender: str) -> float:
    """
    Symmetric player-set overlap between our draw and the ESPN event's singles
    field: |A ∩ B| / |A ∪ B|. Name- and city-independent. A concurrent Grand
    Slam scores near-zero (our small draw is a tiny slice of its huge field),
    while the real event scores high because the two rosters are the same set.
    """
    our_named = [e for e in entries if e.name]
    espn_names = _event_singles_players(event, gender)
    if not our_named or not espn_names:
        return 0.0
    pairs, tok_index = _build_name_index(espn_names)
    inter = sum(1 for e in our_named if _find_entry(e.name, pairs, tok_index))
    union = len(our_named) + len(espn_names) - inter
    return inter / union if union else 0.0


# Confidence assigned to a non-Jaccard match, so competing claims on the same
# ESPN event can be compared on one scale. A name match is definitive; a bare
# city match is the weakest signal we act on and must lose to any real overlap.
_NAME_MATCH_CONFIDENCE = 1.0
_CITY_MATCH_CONFIDENCE = 0.2


def _match_event(tournament, events: list, entries: list) -> tuple[Optional[dict], float]:
    """
    Find the ESPN event for this tournament, most-specific signal first:
      1. Name-token overlap  — cheap; handles the common case.
      2. Player-set Jaccard  — robust to sponsor renames & bad/missing metadata
                               (e.g. ESPN's 'Nordea Open' == our 'Swedish Open');
                               matches on who's actually in the draw.
      3. Venue city          — final cheap tiebreak against the event venue.
    Returns (event, confidence) — (None, 0.0) if nothing matched. The confidence
    is what _poll uses to settle two draws claiming the same event; it is not a
    probability, only an ordering.
    """
    # 1. Name
    for e in events:
        if _names_match(tournament.name, e.get("name", "")):
            return e, _NAME_MATCH_CONFIDENCE

    # 2. Player-set Jaccard (only worth computing if we have a draw to compare)
    if entries:
        best, best_score = None, 0.0
        for e in events:
            score = _player_jaccard(entries, e, tournament.gender)
            if score > best_score:
                best, best_score = e, score
        if best is not None and best_score >= _PLAYER_MATCH_MIN_JACCARD:
            logger.info(
                "ESPN: matched '%s' → '%s' by player overlap (Jaccard=%.2f)",
                tournament.name, best.get("name"), best_score,
            )
            return best, best_score

    # 3. Venue city
    city = getattr(tournament, "city", None)
    if city:
        for e in events:
            vcity = _venue_city(e)
            if vcity and _norm(city) == _norm(vcity):
                return e, _CITY_MATCH_CONFIDENCE

    return None, 0.0


# ---------------------------------------------------------------------------
# ESPN API helpers
# ---------------------------------------------------------------------------

# Consecutive transient failures per gender, and the streak length that turns
# "ESPN is being slow" into "ESPN has been unreachable for a third of an hour".
# In-memory is sound here specifically because the poll is 60s: a restart clears
# the streak, but a real outage rebuilds it in 20 minutes. The same approach
# would be useless for a weekly job, which is why rankings/ELO staleness is
# checked against the data instead (see _check_rankings_health).
_ESPN_FAIL_STREAK: dict[str, int] = {}
ESPN_FAIL_STREAK_ALERT = 20
# Once alerted, stay quiet for this many further failed polls (~6h at 60s)
# before saying it again. Without this the alert fires on EVERY poll past the
# threshold — a minute apart, forever. app_log's dedup would absorb the
# duplicates, but that cache is in-process and resets on every deploy, so an
# outage spanning a restart would emit again immediately. Rate-limit at the
# source instead of trusting a cache that is designed to be lost.
ESPN_OUTAGE_REALERT_POLLS = 360


async def _fetch_events(gender: str) -> list:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_ESPN_URLS[gender])
            resp.raise_for_status()
            events = resp.json().get("events", [])
        _ESPN_FAIL_STREAK[gender] = 0
        return events
    except Exception as exc:
        from app.services.http_errors import describe_exception, is_transient_http_error
        err_msg = describe_exception(exc)
        # The old test here listed only ConnectError/ConnectTimeout, so ESPN
        # answering slowly (ReadTimeout) was logged as an application error —
        # on a 60s poll loop, for a service that times out routinely. One slow
        # response is not worth waking anyone; a sustained outage stops live
        # scores, so the streak is what earns the log.
        if is_transient_http_error(exc):
            streak = _ESPN_FAIL_STREAK.get(gender, 0) + 1
            _ESPN_FAIL_STREAK[gender] = streak
            logger.debug("ESPN %s unreachable (%d in a row): %s", gender, streak, err_msg)
            over = streak - ESPN_FAIL_STREAK_ALERT
            if over >= 0 and over % ESPN_OUTAGE_REALERT_POLLS == 0:
                from app.services.system_log import app_log
                await app_log("error", "espn",
                              f"ESPN {gender} unreachable for {streak} consecutive polls "
                              f"(~{streak} min) — live scores are not updating: {err_msg}",
                              {"gender": gender, "error": err_msg,
                               "exc_type": type(exc).__name__, "consecutive_failures": streak},
                              dedup_key=f"espn_outage_{gender}", dedup_hours=6)
        else:
            logger.warning("ESPN %s fetch failed: %s", gender, err_msg)
            from app.services.system_log import app_log
            await app_log("error", "espn", f"ESPN {gender} API failed: {err_msg}",
                          {"gender": gender, "error": err_msg, "exc_type": type(exc).__name__},
                          dedup_key=f"espn_api_fail_{gender}", dedup_hours=2)
        return []


def _gender_label(gender: str) -> str:
    return "Men's" if gender == "M" else "Women's"


def _is_qualifying(comp: dict) -> bool:
    """True if this competition is a qualifying-draw match (not the main draw).
    ESPN files qualifying under the same 'Singles' grouping, tagged only by the
    round name, e.g. round.displayName='Qualifying 1st Round'."""
    rname = comp.get("round", {}).get("displayName", "") or ""
    return "qualif" in rname.lower()


# Statuses that mean "match is over with a winner". ESPN uses STATUS_RETIRED
# for mid-match retirements (winner flag still set on the standing player) and
# STATUS_WALKOVER for walkovers — a plain STATUS_FINAL filter silently drops
# those results (seen live: Carballés Baena retirement at 2026 Båstad).
_FINAL_STATUSES = ("STATUS_FINAL", "STATUS_RETIRED", "STATUS_WALKOVER")


def _singles_comps(event: dict, gender: str, status) -> list:
    """Return MAIN-DRAW singles competitions with the given status (a string or
    a tuple of strings) for this gender. Qualifying matches are excluded — they
    share the 'Singles' grouping but must never trigger a picks-lock or be
    recorded as a main-draw result."""
    statuses = (status,) if isinstance(status, str) else tuple(status)
    label = _gender_label(gender)
    comps = []
    for group in event.get("groupings", []):
        gname = group.get("grouping", {}).get("displayName", "")
        if "Singles" not in gname or label not in gname:
            continue
        for comp in group.get("competitions", []):
            if _is_qualifying(comp):
                continue
            if comp.get("status", {}).get("type", {}).get("name", "") in statuses:
                comps.append(comp)
    return comps


def _comp_has_linescores(comp: dict) -> bool:
    """True if any competitor carries linescore values — on a STATUS_SCHEDULED
    competition this is ESPN's representation of a SUSPENDED match (the match
    reverts to 'scheduled' for resumption but keeps its partial scores)."""
    return any(
        ls.get("value") is not None
        for c in comp.get("competitors", [])
        for ls in c.get("linescores", [])
    )


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
    Returns (name_a, name_b, scores_a, scores_b, serving, set_wins_a) where:
    - scores include own tiebreak points in parens, e.g. "7(13)" / "6(11)"
    - serving: 1 if A is serving (possession=True), 2 if B, None if unknown
    - set_wins_a: list of True (A won), False (B won), or None (in progress)
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

    sc_a, sc_b, set_wins_a = [], [], []
    for la, lb in zip(a.get("linescores", []), b.get("linescores", [])):
        va = la.get("value")
        vb = lb.get("value")
        if va is None or vb is None:
            continue
        ta = la.get("tiebreak")  # this player's tiebreak points (if set ended in TB)
        tb_v = lb.get("tiebreak")
        if ta is not None and tb_v is not None:
            sc_a.append(f"{int(va)}({int(ta)})")
            sc_b.append(f"{int(vb)}({int(tb_v)})")
        else:
            sc_a.append(str(int(va)))
            sc_b.append(str(int(vb)))
        # winner field present on completed sets only; absent means in progress
        w = la.get("winner")
        set_wins_a.append(True if w is True else (False if w is False else None))

    if a.get("possession"):
        serving = 1
    elif b.get("possession"):
        serving = 2
    else:
        serving = None

    return name_a, name_b, sc_a, sc_b, serving, set_wins_a


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
        lock_start  = today - timedelta(days=_LOCK_TRAIL_DAYS)
        lock_end    = today + timedelta(days=_LOCK_LEAD_DAYS)

        # Job 2 watchlist: full tournament window for match results
        result_cutoff = today - timedelta(days=_RESULT_AFTER_DAYS)

        async with AsyncSessionLocal() as db:
            lock_res = await db.execute(
                select(Draw).where(
                    Draw.picks_locked_at.is_(None),
                    Draw.draw_released_direct_at.isnot(None),
                    Draw.status != "completed",
                    Draw.start_date.isnot(None),
                    Draw.start_date >= lock_start,
                    Draw.start_date <= lock_end,
                )
            )
            lock_list = lock_res.scalars().all()

            result_res = await db.execute(
                select(Draw).where(
                    Draw.draw_released_direct_at.isnot(None),
                    Draw.status != "completed",
                    Draw.start_date.isnot(None),
                    Draw.start_date >= result_cutoff,
                )
            )
            result_list = result_res.scalars().all()

            # Job 4 watchlist: draws about to start, whose pick deadline is still
            # only an assumption from the schedule lookup table.
            sched_res = await db.execute(
                select(Draw).where(
                    Draw.picks_locked_at.is_(None),
                    Draw.draw_released_direct_at.isnot(None),
                    Draw.status != "completed",
                    Draw.start_date.isnot(None),
                    Draw.start_date >= today,
                    Draw.start_date <= today + timedelta(days=_SCHEDULE_LEAD_DAYS),
                )
            )
            sched_list = sched_res.scalars().all()

        # Unique set of tournaments needing attention
        all_ids   = {t.id for t in lock_list} | {t.id for t in result_list} | {t.id for t in sched_list}
        by_id     = {t.id: t for t in lock_list + result_list + sched_list}
        lock_ids  = {t.id for t in lock_list}
        result_ids = {t.id for t in result_list}
        sched_ids = {t.id for t in sched_list}

        if not all_ids:
            return

        logger.debug(
            "ESPN poll: %d lock-watch, %d result-watch",
            len(lock_ids), len(result_ids),
        )

        atp_events = await _fetch_events("M")
        wta_events = await _fetch_events("F")
        espn_events = {"M": atp_events, "F": wta_events}

        # Load draw entries once — needed for player-overlap matching AND both jobs
        entries_by_id: dict[int, list] = {}
        for tid in all_ids:
            async with AsyncSessionLocal() as db:
                de_res = await db.execute(
                    select(DrawEntry).where(DrawEntry.draw_id == tid)
                )
                entries_by_id[tid] = de_res.scalars().all()

        # An ESPN event is one tournament, so two draws of the same gender can
        # never both own it — but nothing used to stop them. 2026 Canadian Open
        # matched 'Mubadala DC Open' at Jaccard 0.32 (a Masters 1000 shares much
        # of its field with the ATP 500 the week before, and its own event was
        # not on the scoreboard yet) while Washington matched that same event at
        # 0.70. Canadian Open then locked its picks off a Washington match three
        # days before its own first ball. Strongest claim takes the event; the
        # loser is left unmatched rather than pointed at someone else's draw.
        claims: dict[int, tuple] = {}
        for tid in all_ids:
            tournament = by_id[tid]
            event, confidence = _match_event(
                tournament, espn_events[tournament.gender], entries_by_id[tid]
            )
            if event is not None:
                claims[tid] = (event, confidence)

        holder: dict[tuple, int] = {}
        for tid, (event, confidence) in claims.items():
            key = (by_id[tid].gender, str(event.get("id") or event.get("name")))
            if key not in holder or confidence > claims[holder[key]][1]:
                holder[key] = tid
        matched = {tid: claims[tid][0] for tid in holder.values()}

        for tid, (event, confidence) in claims.items():
            if tid in matched:
                continue
            key = (by_id[tid].gender, str(event.get("id") or event.get("name")))
            winner = by_id[holder[key]]
            logger.debug(
                "ESPN: '%s' (%s) dropped its claim on '%s' (%.2f) — '%s' matched it better (%.2f)",
                by_id[tid].name, by_id[tid].gender, event.get("name"), confidence,
                winner.name, claims[holder[key]][1],
            )
            # Losing a claim BEFORE your own first ball is the ordinary state,
            # not a fault. ESPN publishes an event around the time play begins,
            # so in the days before that a draw has nothing of its own to match
            # and falls through to player overlap — where it scores against
            # whatever is running this week, because next week's field is
            # largely this week's early losers. Winston-Salem hit Cincinnati at
            # 0.33 every poll for the two days before it started. The guard
            # correctly refused it; alerting on the guard working is an email a
            # day for every event in the week before it opens.
            #
            # Recorded either way, so the Admin panel still shows the reasoning
            # — only the LEVEL moves, and only "warning" reaches the alert
            # digest. Once play has begun and we still cannot see the
            # tournament, that is worth waking someone for: the live scores and
            # the sharpened pick lock both depend on this match.
            started = (by_id[tid].start_date is not None
                       and today >= by_id[tid].start_date)
            from app.services.system_log import app_log
            await app_log(
                "warning" if started else "info", "espn",
                f"'{by_id[tid].name}' ({by_id[tid].gender}) matched ESPN event "
                f"'{event.get('name')}' at {confidence:.2f}, but '{winner.name}' matched it "
                f"at {claims[holder[key]][1]:.2f} — left unmatched rather than tracking the wrong event"
                + ("" if started else " (not started yet — its own event is not published)"),
                {"tournament_id": tid, "tournament_name": by_id[tid].name,
                 "gender": by_id[tid].gender, "espn_event": event.get("name"),
                 "confidence": round(confidence, 3),
                 "start_date": str(by_id[tid].start_date),
                 "started": started,
                 "winner_tournament_id": winner.id, "winner_name": winner.name,
                 "winner_confidence": round(claims[holder[key]][1], 3)},
                dedup_key=f"espn_claim_lost_{tid}", dedup_hours=6,
            )

        for tid in all_ids:
            tournament = by_id[tid]
            entries = entries_by_id[tid]

            espn_event = matched.get(tid)
            if espn_event is None:
                logger.debug(
                    "ESPN: no event match for '%s' (%s)",
                    tournament.name, tournament.gender,
                )
                # Only a system-log warning once play SHOULD be underway. Before
                # the start date, ESPN routinely hasn't published the event yet
                # (it appears around first play) — that's normal, not a failure,
                # and picks lock at closing_time regardless. Warning earlier just
                # spams the log every poll for every upcoming tournament.
                started = (
                    tournament.start_date is not None
                    and tournament.start_date <= date.today()
                )
                if tid in lock_ids and started:
                    from app.services.system_log import app_log
                    await app_log("warning", "espn",
                                  f"No ESPN event matched for '{tournament.name}' after start — "
                                  f"auto-lock precision unavailable (picks still lock at scheduled closing_time)",
                                  {"tournament_id": tournament.id, "tournament_name": tournament.name,
                                   "gender": tournament.gender},
                                  dedup_key=f"espn_no_match_{tournament.id}", dedup_hours=6)
                continue

            # Job 4 runs before the entry check: reading the order of play needs
            # only the event, not a matched roster.
            if tid in sched_ids:
                await self._refine_closing_time(tournament, espn_event)

            if not entries:
                continue

            pairs, tok_index = _build_draw_index(entries)

            # Job 1: picks locking
            if tid in lock_ids:
                await self._check_lock(tournament, espn_event, pairs, tok_index)

            # Job 5: name the blank qualifier slots BEFORE results are synced,
            # so the matches they belong to can be matched this same pass rather
            # than waiting another minute.
            if tid in result_ids and any(not (e.name or "").strip() for e in entries):
                await self._fill_unnamed_slots(tournament, espn_event, pairs, tok_index)

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
    # Job 5: name the qualifier slots Wikipedia has left blank
    # ------------------------------------------------------------------

    async def _fill_unnamed_slots(
        self,
        tournament: Draw,
        espn_event: dict,
        pairs: list,
        tok_index: dict,
    ) -> int:
        """
        Give a name to a bracket slot that is still an empty qualifier.

        Wikipedia publishes the main draw with "Q/LL" placeholders and fills in
        who actually qualified as a separate editing pass, which can lag the
        first ball by a day. 2026 Cincinnati started with all 13 qualifier slots
        blank in both draws.

        The cost is not only cosmetic. An unnamed slot cannot be matched to an
        ESPN competitor, so those 13 matches get no live score, no result and no
        winner — a quarter of the first round simply stops working.

        ESPN has the pairings from the moment the order of play exists, so the
        gap is filled by ANCHORING on the opponent: our own bracket already says
        this blank slot plays a known player, so the ESPN Round-1 competition
        containing that known player names the other side. No fuzzy matching of
        the missing player is needed — the player we already know does the work.

        Deliberately narrow:
          * round 1 only, and only a match with exactly one blank side;
          * the anchor must appear in exactly ONE main-draw Round-1 competition,
            so an ambiguous name fills nothing;
          * the incoming name must not already sit in this draw, which would
            mean the pairing disagrees with ours and one of us is wrong;
          * never overwrites a name — only blanks are eligible.

        Wikipedia overwrites these later with its own spelling, which
        classify_change reads as the same person (a restored diacritic), so the
        correction lands without tripping the in-play roster guard.
        """
        from sqlalchemy import select as _select

        r1_comps = [
            c for c in _singles_comps(
                espn_event, tournament.gender,
                ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS", "STATUS_SUSPENDED") + _FINAL_STATUSES,
            )
            if (c.get("round", {}).get("displayName", "") or "").strip().lower() == "round 1"
        ]
        if not r1_comps:
            return 0

        from app.models.notification import DrawChangeEvent
        # Same gate the scraper uses: nothing is announced for a draw whose own
        # release has not been.
        draw_announced = tournament.draw_release_notified_at is not None

        async with AsyncSessionLocal() as db:
            matches = (await db.execute(
                _select(Match).where(Match.draw_id == tournament.id,
                                     Match.round_number == 1,
                                     Match.is_bye == False)  # noqa: E712
            )).scalars().all()
            entries = (await db.execute(
                _select(DrawEntry).where(DrawEntry.draw_id == tournament.id)
            )).scalars().all()
            by_id = {e.id: e for e in entries}
            taken = {_norm(e.name) for e in entries if (e.name or "").strip()}

            filled = 0
            for m in matches:
                sides = [by_id.get(m.player1_id), by_id.get(m.player2_id)]
                if any(x is None for x in sides):
                    continue
                blanks = [e for e in sides if not (e.name or "").strip()]
                known = [e for e in sides if (e.name or "").strip()]
                if len(blanks) != 1 or len(known) != 1:
                    continue

                anchor_name = known[0].name
                hits = []
                for comp in r1_comps:
                    names = _comp_live_players(comp)
                    if len(names) != 2:
                        continue
                    if any(_player_names_equal(anchor_name, n) for n in names):
                        hits.append(names)
                if len(hits) != 1:
                    continue

                names = hits[0]
                opponent = next(
                    (n for n in names if not _player_names_equal(anchor_name, n)), None
                )
                if not opponent or _norm(opponent) in taken:
                    continue

                blanks[0].name = opponent
                taken.add(_norm(opponent))
                filled += 1
                # Recorded like a scraper fill would be, or this path names the
                # slot and nobody is told. It is now the path that usually gets
                # there first — ESPN publishes a pairing hours before Wikipedia
                # transcribes it — so leaving it silent meant the qualifier
                # notification simply never fired for a draw already under way.
                if draw_announced:
                    db.add(DrawChangeEvent(
                        draw_id=tournament.id,
                        entry_id=blanks[0].id,
                        bracket_position=blanks[0].bracket_position,
                        kind="filled",
                        old_name=None,
                        new_name=opponent,
                        old_entry_type=blanks[0].entry_type,
                        new_entry_type=blanks[0].entry_type,
                    ))
                logger.info("ESPN: named %s slot %d in %s %s as %r (opponent of %s)",
                            blanks[0].entry_type or "empty", blanks[0].bracket_position,
                            tournament.year, tournament.name, opponent, anchor_name)

            if filled:
                await db.commit()

        if filled:
            from app.services.system_log import app_log
            await app_log(
                "info", "espn",
                f"Filled {filled} unnamed slot(s) in {tournament.year} {tournament.name} "
                f"({'ATP' if tournament.gender == 'M' else 'WTA'}) from ESPN's Round-1 "
                f"pairings — Wikipedia still shows them as Q/LL placeholders",
                {"draw_id": tournament.id, "filled": filled},
                dedup_key=f"espn_fill_slots_{tournament.id}", dedup_hours=6,
            )
        return filled

    # ------------------------------------------------------------------
    # Job 4: pick deadline from the published order of play
    # ------------------------------------------------------------------

    async def _refine_closing_time(self, tournament: Draw, espn_event: dict) -> None:
        """
        Replace the assumed pick deadline with the real first ball of day 1.

        closing_time is otherwise derived from tournament_schedule's lookup
        table, which stores one nominal start hour per venue — an assumption,
        and every tournament schedules differently. 2026 Cincinnati starts its
        main draw at 10:00 local where the table assumes 11:00, so picks would
        have stayed open an hour into play.

        The order of play is the authority, and ESPN publishes it the evening
        before. Until then it reports every day-1 match at MIDNIGHT venue-local,
        which is a placeholder and not a schedule — taking it at face value
        would close picks ten hours early, a far worse failure than the hour
        this exists to fix. Verified against live data: unscheduled Cincinnati
        showed all 32 day-1 matches at exactly 00:00 local, while the Canadian
        Open's published day read 22:00 and 23:30. So midnight local is the
        signal for "not published yet", and a real session never starts there.

        Qualifying is excluded by _singles_comps, which matters more here than
        anywhere: qualifying starts days earlier, and its first match would drag
        the deadline back before the draw was even released.
        """
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo

        if tournament.picks_locked_at is not None or tournament.status in ("active", "completed"):
            return
        # Without the venue zone there is no way to tell a midnight placeholder
        # from a real time, and a wrong deadline is worse than a rough one.
        if not tournament.venue_timezone or not tournament.start_date:
            return
        try:
            venue_tz = ZoneInfo(tournament.venue_timezone)
        except Exception:
            return

        starts = []
        for comp in _singles_comps(espn_event, tournament.gender, "STATUS_SCHEDULED"):
            raw = comp.get("date")
            if not raw:
                continue
            try:
                starts.append(
                    _dt.strptime(raw, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
                )
            except ValueError:
                continue
        if not starts:
            return

        # Day 1 is the earliest LOCAL date on the board — a UTC date would split
        # an evening session across two days for any venue west of Greenwich.
        local = sorted((u, u.astimezone(venue_tz)) for u in starts)
        day1 = local[0][1].date()
        day1_starts = [(u, l) for u, l in local if l.date() == day1]

        first_utc, first_local = day1_starts[0]
        if first_local.hour == 0 and first_local.minute == 0:
            logger.debug("ESPN: order of play not published yet for %s %s (all day-1 "
                         "matches at midnight local)", tournament.year, tournament.name)
            return

        # A schedule that lands days from the draw's own start date belongs to
        # something else — a stale event, or a match that survived the exclusivity
        # check. Never move a deadline on that evidence.
        if abs((day1 - tournament.start_date).days) > 1:
            logger.debug("ESPN: ignoring day-1 %s for %s (start_date %s)",
                         day1, tournament.name, tournament.start_date)
            return

        new_close = first_utc.replace(tzinfo=None)
        old_close = tournament.closing_time
        # Recorded BEFORE the "deadline already agrees" exit. A published
        # schedule that merely confirms the assumption is still the observation
        # this column exists for — and it is the common case, so skipping it
        # would leave the estimator learning only from the times we got wrong.
        observation_new = tournament.first_match_at is None

        async with AsyncSessionLocal() as db:
            fresh = await db.get(Draw, tournament.id)
            if fresh is None or fresh.picks_locked_at is not None \
                    or fresh.status in ("active", "completed"):
                return
            fresh.first_match_at = new_close
            fresh.first_match_local_hour = first_local.hour
            fresh.first_match_local_minute = first_local.minute
            moved = old_close is None or abs((new_close - old_close).total_seconds()) >= 300
            if moved:
                fresh.closing_time = new_close
            await db.commit()

        tournament.first_match_at = new_close
        tournament.first_match_local_hour = first_local.hour
        tournament.first_match_local_minute = first_local.minute
        if not moved:
            if observation_new:
                logger.info("ESPN: %s %s first ball confirmed at %s local — deadline already correct",
                            tournament.year, tournament.name, first_local.strftime("%H:%M"))
            return
        tournament.closing_time = new_close

        from app.services.system_log import app_log
        await app_log(
            "info", "espn",
            f"Pick deadline for {tournament.year} {tournament.name} "
            f"({'ATP' if tournament.gender == 'M' else 'WTA'}) set from the published "
            f"order of play: {first_local:%a %d %b %H:%M} local "
            f"(was {old_close} UTC, now {new_close} UTC)",
            {"draw_id": tournament.id, "old_closing_time": str(old_close),
             "new_closing_time": str(new_close),
             "first_match_local": first_local.isoformat(),
             "day1_matches": len(day1_starts)},
            dedup_key=f"espn_schedule_close_{tournament.id}", dedup_hours=6,
        )
        logger.info("ESPN: pick deadline for %s %s -> %s UTC (first ball %s local)",
                    tournament.year, tournament.name, new_close, first_local)

    # ------------------------------------------------------------------
    # Job 1: picks locking
    # ------------------------------------------------------------------

    async def _check_lock(
        self,
        tournament: Draw,
        espn_event: dict,
        pairs: list,
        tok_index: dict,
    ) -> None:
        # A match that is under way OR already played is equally good evidence
        # that the draw has begun. Watching only STATUS_IN_PROGRESS meant a
        # first match that finished (or was suspended by rain) between two
        # 60-second polls left the draw Open with results already on the board.
        # Suspended/played comps must carry linescores, so a merely scheduled
        # match can never lock anything.
        started_comps = _singles_comps(espn_event, tournament.gender, "STATUS_IN_PROGRESS")
        started_comps += [
            c for c in _singles_comps(
                espn_event, tournament.gender,
                ("STATUS_SUSPENDED", "STATUS_SCHEDULED") + _FINAL_STATUSES,
            )
            if _comp_has_linescores(c)
        ]

        trigger_name = None
        for comp in started_comps:
            for name in _comp_live_players(comp):
                if _player_in_draw(name, pairs, tok_index):
                    trigger_name = name
                    break
            if trigger_name:
                break

        if trigger_name:
            logger.info(
                "ESPN MAIN-DRAW PLAY DETECTED — %d %s (%s): '%s' is under way or played",
                tournament.year, tournament.name, tournament.gender, trigger_name,
            )
            await self._on_match_start(tournament.id, trigger_name)

    async def _on_match_start(self, tournament_id: int, trigger_name: str) -> None:
        from app.services import broadcaster
        from app.services.system_log import app_log

        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as db:
            tournament = await db.get(Draw, tournament_id)
            if tournament is None or tournament.picks_locked_at is not None:
                return  # already handled (race guard)

            # A main-draw match cannot be under way days before the draw starts.
            # If we got here anyway, the evidence is about some other event and
            # locking on it would shut users out of a draw that hasn't begun —
            # refuse at the write site, not just at the watchlist that led here.
            days_early = (tournament.start_date - date.today()).days if tournament.start_date else 0
            if days_early > _LOCK_LEAD_DAYS:
                logger.warning(
                    "Refusing to lock %d %s (%s) — starts in %d days, "
                    "so '%s' being live is not this draw",
                    tournament.year, tournament.name, tournament.gender,
                    days_early, trigger_name,
                )
                await app_log(
                    "warning", "espn",
                    f"Refused an early picks-lock for '{tournament.name}' ({tournament.gender}): "
                    f"starts in {days_early} days but ESPN reported '{trigger_name}' live — wrong event",
                    {"tournament_id": tournament.id, "tournament_name": tournament.name,
                     "gender": tournament.gender, "trigger_player": trigger_name,
                     "start_date": str(tournament.start_date), "days_early": days_early},
                    dedup_key=f"espn_early_lock_refused_{tournament.id}", dedup_hours=6,
                )
                return

            # NOT UNDER MATCH-BY-MATCH LOCKING. picks_locked_at means "the
            # bracket is closed", and closing it at the first ball is the
            # draw_start rule. A progressive draw stays open until every
            # first-round match is complete — matches freeze individually as
            # they go on court, which draw_lock_state handles, and that is the
            # whole point of the mode. Stamping here closed Winston-Salem with
            # none of its sixteen first-round matches played.
            #
            # draw_lock_state stamps it when the round is genuinely done, so the
            # column keeps its meaning under both rules and everything reading
            # is_locked keeps getting a straight answer.
            from app.services.settings import LOCK_PROGRESSIVE_R1, resolve_draw_lock_mode
            if await resolve_draw_lock_mode(db, tournament) == LOCK_PROGRESSIVE_R1:
                return

            # Capture predicted closing_time before overwriting it
            original_ct = tournament.closing_time

            tournament.picks_locked_at = now
            tournament.closing_time = now
            name, year, tid = tournament.name, tournament.year, tournament.id
            category, gender = tournament.category or "", tournament.gender or "M"
            await db.commit()

        # Build timing comparison
        actual_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")
        if original_ct is not None:
            ct_aware = original_ct.replace(tzinfo=timezone.utc) if original_ct.tzinfo is None else original_ct
            diff_seconds = (now - ct_aware).total_seconds()
            abs_min = int(abs(diff_seconds) // 60)
            abs_sec = int(abs(diff_seconds) % 60)
            direction = "late" if diff_seconds >= 0 else "early"
            sign = "+" if diff_seconds >= 0 else "-"
            predicted_str = ct_aware.strftime("%Y-%m-%d %H:%M:%S UTC")
            diff_str = f"{sign}{abs_min}m {abs_sec}s ({direction})"
        else:
            predicted_str = "not set"
            diff_str = "N/A"
            diff_seconds = None

        await broadcaster.publish(tournament_id)

        logger.info(
            "Picks locked: %d %s — trigger: %s | predicted=%s actual=%s diff=%s",
            year, name, trigger_name, predicted_str, actual_str, diff_str,
        )
        await app_log(
            "info", "espn",
            f"{year} {name}: first match live — predicted {predicted_str}, actual {actual_str}, diff {diff_str}",
            {
                "tournament_id": tid,
                "trigger_player": trigger_name,
                "predicted_closing_time": predicted_str,
                "actual_detection_time": actual_str,
                "diff_seconds": round(diff_seconds) if diff_seconds is not None else None,
                "diff_str": diff_str,
            },
        )

    # ------------------------------------------------------------------
    # Job 2: live scores
    # ------------------------------------------------------------------

    async def _sync_live(
        self,
        tournament: Draw,
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

        # Suspended matches keep their partial linescores; track them alongside
        # live matches so the draw shows "7-6, 4-6 (Suspended)" instead of
        # silently dropping the score. ESPN reports them two different ways: an
        # explicit STATUS_SUSPENDED, or a revert to STATUS_SCHEDULED (for the
        # resumption) with the linescores left in place. Only the second was
        # handled, so rain at 2026 Canadian Open R1 left three matches with no
        # live state at all — the draw looked like play had never begun.
        suspended_comps = [
            c for c in _singles_comps(
                espn_event, tournament.gender, ("STATUS_SUSPENDED", "STATUS_SCHEDULED")
            )
            if _comp_has_linescores(c)
        ]

        # Map (entry_id_a, entry_id_b) → (scores_a, scores_b, serving, set_wins, suspended)
        in_progress: dict[tuple, tuple] = {}
        for comp, is_suspended in (
            [(c, False) for c in live_comps] + [(c, True) for c in suspended_comps]
        ):
            result = _comp_live_scores(comp)
            if not result:
                continue
            name_a, name_b, sc_a, sc_b, serving, set_wins_a = result
            entry_a = _find_entry(name_a, pairs, tok_index)
            entry_b = _find_entry(name_b, pairs, tok_index)
            if not entry_a or not entry_b or entry_a.id == entry_b.id:
                continue
            if is_suspended:
                serving = None  # nobody is serving a suspended match
            serving_b = (3 - serving) if serving else None
            set_wins_b = [(not w if w is not None else None) for w in set_wins_a]
            in_progress[(entry_a.id, entry_b.id)] = (sc_a, sc_b, serving, set_wins_a, is_suspended)
            in_progress[(entry_b.id, entry_a.id)] = (sc_b, sc_a, serving_b, set_wins_b, is_suspended)

        async with AsyncSessionLocal() as db:
            m_res = await db.execute(
                select(Match).where(
                    Match.draw_id == tournament.id,
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
                    suspended = live[4]
                    raw_serving = live[2]  # from ESPN possession; may be None

                    # Total completed games determines serve parity from match start.
                    # Scores are strings like "6", "7(13)" — strip tiebreak annotation.
                    def _gc(s: str) -> int:
                        return int(s.split("(")[0])
                    total_games = sum(_gc(s) for s in live[0] + live[1])

                    if suspended:
                        serving = None  # never infer a server for a suspended match
                    elif raw_serving is not None:
                        # ESPN tells us who is serving; back-calculate who served first.
                        if m.served_first is None:
                            m.served_first = raw_serving if total_games % 2 == 0 else (3 - raw_serving)
                        serving = raw_serving
                    elif m.served_first is not None:
                        # No ESPN possession signal — infer from first-server + game parity.
                        serving = m.served_first if total_games % 2 == 0 else (3 - m.served_first)
                    else:
                        serving = None  # not enough data yet

                    # [p1_scores, p2_scores, serving, set_wins_p1, ("suspended"|None)]
                    new_val = [live[0], live[1], serving, live[3]]
                    if suspended:
                        new_val.append("suspended")
                    if m.live_scores_json != new_val:
                        # Before the assignment — see note_resumption.
                        note_resumption(m, new_val)
                        m.live_scores_json = new_val
                        changed += 1
                        # SCORE HISTORY, WHERE SOFASCORE CANNOT PROVIDE IT.
                        #
                        # The scrubber's snapshots normally come from the
                        # Sofascore poller, which carries the point score. But
                        # Sofascore does not list every match — qualifying and
                        # some outside courts are ESPN-only — and those matches
                        # had no history at all, so their popup opened without
                        # a slider while the match beside them had one.
                        #
                        # ONLY when Sofascore is absent for this match. The two
                        # feeds must never be spliced into one timeline: ESPN
                        # lags up to 60s and has no point score, so interleaving
                        # them would produce states that never existed — the
                        # same trap renderable_point documents. One match, one
                        # source; whichever is actually watching it.
                        if m.sofa_live_json is None:
                            try:
                                from app.services.score_history import record_snapshot
                                record_snapshot(db, m.id, _espn_snapshot(new_val))
                            except Exception:
                                logger.exception(
                                    "ESPN score history insert failed for match %s", m.id)
                    # First sighting on court. Only ever written once, so a
                    # suspension and resumption does not restart the clock —
                    # the elapsed time is what the schedule needs, not time
                    # actually in play.
                    if m.started_at is None:
                        m.started_at = datetime.now(timezone.utc)
                        changed += 1
                elif m.live_scores_json is not None:
                    # Match was live but no longer in ESPN's in-progress/suspended list
                    m.live_scores_json = None
                    changed += 1

            # Defensive sweep: a winner written by the Wikipedia scrape path can
            # race ahead of ESPN's completion event, leaving live_scores_json
            # orphaned on a completed match (renders a stale "In Progress" badge).
            stale_res = await db.execute(
                select(Match).where(
                    Match.draw_id == tournament.id,
                    Match.winner_id.isnot(None),
                    Match.live_scores_json.isnot(None),
                )
            )
            for m in stale_res.scalars().all():
                # JSON columns store cleared values as JSON null (not SQL NULL),
                # which still matches isnot(None) — skip the already-cleared ones.
                if m.live_scores_json is not None:
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
        tournament: Draw,
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
        final_comps = _singles_comps(espn_event, tournament.gender, _FINAL_STATUSES)
        if not final_comps:
            return 0

        updated = 0
        rounds_updated: set[int] = set()
        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as db:
            # Load pending matches (both players known, no winner yet, not a bye)
            m_res = await db.execute(
                select(Match).where(
                    Match.draw_id == tournament.id,
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
                match.completed_at = datetime.now(timezone.utc)
                # Measured length, for main-draw singles — the only matches
                # ESPN reports, so the only ones we can time. Recorded only when
                # we saw the start: a match already under way when the monitor
                # first polled would otherwise report an implausibly short one.
                if match.started_at is not None:
                    started = match.started_at
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    mins = int((match.completed_at - started).total_seconds() // 60)
                    if 10 <= mins <= 420:      # sanity: a real match, not a clock error
                        match.duration_min = mins
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
                            Match.draw_id == tournament.id,
                            Match.round_number == rn,
                            Match.is_bye == False,
                            Match.winner_id.is_(None),
                        )
                    )
                    if incomplete.scalar_one() == 0:
                        # Records the round; the email is a weekly digest sent by
                        # scheduler._notify_pending_round_digests once the week's
                        # other draws have reached the same round.
                        from app.services.notifications import record_round_complete
                        asyncio.create_task(record_round_complete(tournament.id, rn))
                        logger.info("Round %d complete for tournament %d — queued for digest", rn, tournament.id)

                # Check whether the whole tournament is now complete
                total_incomplete = await db.execute(
                    select(func.count()).where(
                        Match.draw_id == tournament.id,
                        Match.is_bye == False,
                        Match.winner_id.is_(None),
                    )
                )
                if total_incomplete.scalar_one() == 0:
                    from app.services.notifications import notify_tournament_complete
                    asyncio.create_task(notify_tournament_complete(tournament.id))
                    logger.info("Tournament %d fully complete — completion notification queued", tournament.id)

                # INSTANT, not next-revision: a winner this cycle just wrote
                # may be the decider of a schedule slot still offering
                # "A or B" — fold it away in the same breath. `tournament`
                # here is a DRAW row; the schedule keys on its tournament_id.
                if updated and tournament.tournament_id:
                    try:
                        from app.services import schedule as _sched
                        await _sched.resolve_settled_alternatives(
                            db, tournament.tournament_id)
                    except Exception:
                        logger.exception("alt-collapse after ESPN results failed")

        return updated
