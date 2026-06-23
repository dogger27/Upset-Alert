"""
ATP/WTA ranking lookup.

Both genders use Tennis Explorer (~2270 ATP / ~1500 WTA players, updated daily).
Results are cached in te_players / te_rankings_snapshots — scraped at most once per week.

Name matching uses token-set algebra instead of ordered rotation heuristics:
  - Rule 1: exact token set match   {"felix","auger","aliassime"} == {"auger","aliassime","felix"}
  - Rule 2: wiki ⊂ TE (unique)     {"carlos","alcaraz"} ⊂ {"carlos","alcaraz","garfia"}
  - Rule 3: TE ⊂ wiki (unique)     {"albert","ramos"} ⊂ {"albert","ramos","vinolas"}
  + umlaut fallbacks: ö→oe/ue/ae on wiki side vs plain vowel on TE side
"""

import asyncio
import logging
import re
import unicodedata
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tennis Explorer URLs
# ---------------------------------------------------------------------------

_TE_URLS = {
    "M": "https://www.tennisexplorer.com/ranking/atp-men/",
    "F": "https://www.tennisexplorer.com/ranking/wta-women/",
}
_TE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}
_TE_ROW_RE = re.compile(
    r'<td class="rank first">(\d+)\.</td>.*?<td class="t-name"><a href="([^"]+)">(.*?)</a></td>',
    re.DOTALL,
)
_TE_SLUG_RE = re.compile(r'^/player/([^/]+)/?$')

# Per-(gender, week_date): (te_index, rank_by_te_id)
# Avoids reloading thousands of rows from SQLite on every assign_rankings call.
_week_cache: dict[tuple, tuple[dict, dict]] = {}

# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

# German umlauts must be expanded BEFORE NFD. NFD would decompose ö→o+combining,
# losing the 'e'. We expand on the wiki side; TE stores plain ASCII vowels.
# The umlaut fallback in _match_token_set handles the mismatch.
_PRE_NFD_TRANS = str.maketrans({
    "ä": "ae", "Ä": "ae",
    "ö": "oe", "Ö": "oe",
    "ü": "ue", "Ü": "ue",
})

# Characters that NFD does not decompose — must be transliterated explicitly.
_TRANSLITERATE = str.maketrans({
    "ø": "o",   # Møller → moller
    "æ": "ae",  # Kjær → kjaer
    "đ": "d",
    "ł": "l",
})


def _norm(name: str) -> str:
    """Normalize to lowercase ASCII: expand umlauts, strip accents, remove apostrophes, hyphen→space."""
    name = name.translate(_PRE_NFD_TRANS)
    nfd = unicodedata.normalize("NFD", name)
    stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower().strip()
    stripped = stripped.translate(_TRANSLITERATE)
    stripped = stripped.replace("'", "").replace("’", "")
    return stripped.replace("-", " ")


def _clean_wiki_name(name: str) -> str:
    """Strip Wikipedia disambiguation suffixes like '(tennis)'."""
    return re.sub(r"\s*\([^)]+\)\s*$", "", name).strip()


def _monday(d: date) -> date:
    """Return the Monday on or before d (ranking week anchor)."""
    return d - timedelta(days=d.weekday())


# ---------------------------------------------------------------------------
# Token-set matching
# ---------------------------------------------------------------------------

def _match_token_set(wiki_name: str, te_index: dict[frozenset, list[int]]) -> Optional[int]:
    """
    Match a Wikipedia player name to a te_players.id using token-set algebra.

    Rules (tried in order, return on first unique hit):
      1. Exact token set match
      2. Wiki tokens ⊂ TE tokens  (TE has extra name components)
      3. TE tokens ⊂ Wiki tokens, |TE| ≥ 2  (wiki has extra name components)
    Umlaut fallback: _PRE_NFD_TRANS expands ö→oe, ü→ue, ä→ae but TE stores
    plain ASCII vowels. Try collapsing each expansion before giving up.
    """
    wiki_ts = frozenset(_norm(_clean_wiki_name(wiki_name)).split())

    result = _apply_rules(wiki_ts, te_index)
    if result is not None:
        return result

    for src, dst in [("oe", "o"), ("ue", "u"), ("ae", "a")]:
        if any(src in tok for tok in wiki_ts):
            alt_ts = frozenset(tok.replace(src, dst) for tok in wiki_ts)
            if alt_ts != wiki_ts:
                result = _apply_rules(alt_ts, te_index)
                if result is not None:
                    return result

    return None


def _apply_rules(wiki_ts: frozenset, te_index: dict[frozenset, list[int]]) -> Optional[int]:
    # Rule 1: exact set match
    hits = te_index.get(wiki_ts, [])
    if len(hits) == 1:
        return hits[0]

    # Rule 2: wiki ⊂ TE (unique)
    rule2: list[int] = []
    for te_ts, ids in te_index.items():
        if wiki_ts < te_ts:
            rule2.extend(ids)
    if len(rule2) == 1:
        return rule2[0]

    # Rule 3: TE ⊂ wiki (unique, |TE| ≥ 2)
    rule3: list[int] = []
    for te_ts, ids in te_index.items():
        if len(te_ts) >= 2 and te_ts < wiki_ts:
            rule3.extend(ids)
    if len(rule3) == 1:
        return rule3[0]

    # Rule 4: unique identifying token — handles first-name spelling variants
    # (Kasatkina/Darya vs Daria, Minnen/Greetje vs Greet, Starodubtseva/Yulia vs Yuliia).
    # If exactly one TE player has a given wiki token, that token uniquely identifies them.
    for tok in wiki_ts:
        tok_hits = [id for te_ts, ids in te_index.items() if tok in te_ts for id in ids]
        if len(tok_hits) == 1:
            return tok_hits[0]

    return None


def _build_te_index(te_players: list) -> dict[frozenset, list[int]]:
    """Build token-set → [player_id] index from a list of TePlayer ORM objects."""
    index: dict[frozenset, list[int]] = {}
    for tp in te_players:
        ts = frozenset(tp.name_norm.split())
        index.setdefault(ts, []).append(tp.id)
    return index


# ---------------------------------------------------------------------------
# Tennis Explorer scraper
# ---------------------------------------------------------------------------

async def _scrape_te(gender: str) -> list[tuple[str, int, Optional[str]]]:
    """
    Scrape all pages of Tennis Explorer rankings for the given gender.
    Returns [(name_raw, rank, te_slug), ...] in TE's "Surname Firstname" format.
    te_slug is the URL slug from the player's TE profile, e.g. "sinner-jannik".
    """
    import httpx

    url = _TE_URLS[gender]
    results: list[tuple[str, int, Optional[str]]] = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            page = 1
            while True:
                resp = await client.get(url, params={"page": page}, headers=_TE_HEADERS)
                resp.raise_for_status()
                rows = _TE_ROW_RE.findall(resp.text)
                if not rows:
                    break
                for rank_str, href, raw_name in rows:
                    slug_m = _TE_SLUG_RE.match(href)
                    slug = slug_m.group(1) if slug_m else None
                    results.append((raw_name.strip(), int(rank_str), slug))
                page += 1
                await asyncio.sleep(0.1)
        logger.info("Tennis Explorer %s scrape: %d players across %d pages", gender, len(results), page - 1)
    except Exception as exc:
        logger.warning("Tennis Explorer %s scrape failed: %s", gender, exc)
        from app.services.system_log import app_log
        await app_log("error", "rankings", f"Tennis Explorer {gender} scrape failed: {exc}",
                      {"gender": gender, "error": str(exc)},
                      dedup_key=f"te_scrape_fail_{gender}", dedup_hours=2)

    return results


# ---------------------------------------------------------------------------
# DB-backed ranking management
# ---------------------------------------------------------------------------

async def ensure_te_week(gender: str, week_date: date, db: AsyncSession) -> bool:
    """
    Ensure te_rankings_snapshots has data for (gender, week_date).
    Scrapes Tennis Explorer and stores results if the week is absent.
    Returns True if a scrape was performed.
    """
    from app.models.rankings import TePlayer, TeRankingsSnapshot

    existing = await db.execute(
        select(func.count()).select_from(TeRankingsSnapshot)
        .join(TePlayer, TeRankingsSnapshot.player_id == TePlayer.id)
        .where(TePlayer.gender == gender, TeRankingsSnapshot.week_date == week_date)
    )
    if existing.scalar_one() >= 50:
        return False

    logger.info("Scraping Tennis Explorer for %s week %s...", gender, week_date)
    raw_rows = await _scrape_te(gender)
    if len(raw_rows) < 50:
        logger.warning("TE %s scrape returned only %d players — aborting", gender, len(raw_rows))
        from app.services.system_log import app_log
        await app_log("warning", "rankings", f"TE {gender} scrape returned only {len(raw_rows)} players — aborting",
                      {"gender": gender, "count": len(raw_rows)},
                      dedup_key=f"te_scrape_low_{gender}", dedup_hours=2)
        return False

    existing_players_res = await db.execute(
        select(TePlayer).where(TePlayer.gender == gender)
    )
    existing_by_raw: dict[str, TePlayer] = {
        p.name_raw: p for p in existing_players_res.scalars()
    }

    for name_raw, rank, slug in raw_rows:
        tp = existing_by_raw.get(name_raw)
        if tp is None:
            tp = TePlayer(gender=gender, name_raw=name_raw, name_norm=_norm(name_raw), te_slug=slug)
            db.add(tp)
            await db.flush()
            existing_by_raw[name_raw] = tp
        elif slug and tp.te_slug is None:
            tp.te_slug = slug

        snap = await db.get(TeRankingsSnapshot, (tp.id, week_date))
        if snap is None:
            db.add(TeRankingsSnapshot(player_id=tp.id, week_date=week_date, rank=rank))
        else:
            snap.rank = rank

    await db.flush()
    logger.info("Stored %d TE rankings for %s week %s", len(raw_rows), gender, week_date)
    return True


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

async def assign_rankings(
    players: list,
    gender: str,
    ref_date: date,
    db: AsyncSession,
) -> None:
    """
    Resolve te_player_id for each player (if not already set) and populate
    player.ranking from te_rankings_snapshots for the week of ref_date.
    Does not commit — caller owns the transaction.
    """
    from app.models.rankings import TePlayer, TeRankingsSnapshot

    # TE only exposes current rankings. Ensure this week exists, then use the
    # most recent available week on or before ref_date (covers past tournaments).
    today_week = _monday(date.today())
    await ensure_te_week(gender, today_week, db)

    target = _monday(ref_date)
    best_week_res = await db.execute(
        select(TeRankingsSnapshot.week_date)
        .join(TePlayer, TeRankingsSnapshot.player_id == TePlayer.id)
        .where(TePlayer.gender == gender, TeRankingsSnapshot.week_date <= target)
        .order_by(TeRankingsSnapshot.week_date.desc())
        .limit(1)
    )
    week_date = best_week_res.scalar_one_or_none() or today_week

    cache_key = (gender, week_date)
    if cache_key not in _week_cache:
        tp_res = await db.execute(select(TePlayer).where(TePlayer.gender == gender))
        te_index = _build_te_index(tp_res.scalars().all())

        snap_res = await db.execute(
            select(TeRankingsSnapshot).where(TeRankingsSnapshot.week_date == week_date)
        )
        rank_by_te_id: dict[int, int] = {s.player_id: s.rank for s in snap_res.scalars()}
        _week_cache[cache_key] = (te_index, rank_by_te_id)
        logger.info("Loaded TE index for %s week %s into memory (%d players)", gender, week_date, len(te_index))
    else:
        te_index, rank_by_te_id = _week_cache[cache_key]

    from app.services.system_log import app_log
    for player in players:
        if player.te_player_id is None:
            te_id = _match_token_set(player.name, te_index)
            if te_id is not None:
                player.te_player_id = te_id
            elif player.name and player.entry_type not in ("Q", "LL"):
                await app_log("warning", "rankings",
                              f"Player name not matched in TE: {player.name!r}",
                              {"player_name": player.name, "gender": gender},
                              dedup_key=f"match_fail_{player.name.lower()}", dedup_hours=24)

        player.ranking = rank_by_te_id.get(player.te_player_id) if player.te_player_id else None


# ---------------------------------------------------------------------------
# Date-of-birth scraper
# ---------------------------------------------------------------------------

# TE page format: Age: 24 (16. 8. 2001)  →  day=16, month=8, year=2001
_DOB_RE = re.compile(r'Age:\s*\d+\s*\((\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\)')


async def _fetch_te_player_dob(te_slug: str) -> Optional[date]:
    """Scrape DOB from a TE player profile page. Returns None on any failure."""
    import httpx

    url = f"https://www.tennisexplorer.com/player/{te_slug}/"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=_TE_HEADERS)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        logger.debug("DOB fetch failed for %s: %s", te_slug, exc)
        return None

    m = _DOB_RE.search(html)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    return None


async def prefetch_dob_for_draw(tournament_id: int) -> None:
    """
    After a draw is refreshed, fetch DOB from TE for any linked te_players
    in this draw that are still missing it. Creates its own DB session.
    """
    from app.database import AsyncSessionLocal
    from app.models.rankings import TePlayer
    from app.models.tournament import DrawEntry

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(TePlayer)
            .join(DrawEntry, DrawEntry.te_player_id == TePlayer.id)
            .where(
                DrawEntry.tournament_id == tournament_id,
                TePlayer.te_slug.isnot(None),
                TePlayer.date_of_birth.is_(None),
            )
            .distinct()
        )
        missing = res.scalars().all()
        if not missing:
            return

        logger.info("DOB prefetch: %d player(s) for tournament %d", len(missing), tournament_id)
        for tp in missing:
            dob = await _fetch_te_player_dob(tp.te_slug)
            if dob:
                tp.date_of_birth = dob
                logger.debug("DOB %s → %s", tp.te_slug, dob)
            await asyncio.sleep(0.3)

        await db.commit()
        logger.info("DOB prefetch complete for tournament %d", tournament_id)


async def backfill_all_dob() -> dict:
    """
    Admin backfill: fetch DOB for every te_player with a slug but no DOB yet.
    Creates its own DB session. Safe to call multiple times (skips already set).
    """
    from app.database import AsyncSessionLocal
    from app.models.rankings import TePlayer

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(TePlayer).where(
                TePlayer.te_slug.isnot(None),
                TePlayer.date_of_birth.is_(None),
            )
        )
        missing = res.scalars().all()
        total = len(missing)
        logger.info("DOB backfill: %d te_players to process", total)

        updated = 0
        for tp in missing:
            dob = await _fetch_te_player_dob(tp.te_slug)
            if dob:
                tp.date_of_birth = dob
                updated += 1
            await asyncio.sleep(0.3)

        await db.commit()
        logger.info("DOB backfill complete: %d/%d updated", updated, total)
        return {"total": total, "updated": updated, "failed": total - updated}


# ---------------------------------------------------------------------------
# Tennis Abstract Elo ratings
# ---------------------------------------------------------------------------

_TA_ELO_URLS = {
    "M": "https://tennisabstract.com/reports/atp_elo_ratings.html",
    "F": "https://tennisabstract.com/reports/wta_elo_ratings.html",
}

_TA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,*/*",
}


async def _fetch_ta_elo_page(gender: str) -> dict[frozenset, int]:
    """Scrape Tennis Abstract Elo page; return {frozenset(name_tokens) → elo}."""
    import html as html_lib
    import httpx

    url = _TA_ELO_URLS[gender]
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_TA_HEADERS) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    result: dict[frozenset, int] = {}
    for row_m in re.finditer(r'<tr[^>]*>(.*?)</tr>', resp.text, re.DOTALL):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row_m.group(1), re.DOTALL)
        if len(cells) < 4:
            continue
        name = html_lib.unescape(re.sub(r'<[^>]+>', '', cells[1])).strip()
        try:
            elo = round(float(cells[3].strip()))
        except (ValueError, IndexError):
            continue
        if name:
            result[frozenset(name.lower().split())] = elo
    return result


async def refresh_elo_ratings() -> None:
    """Fetch Elo from Tennis Abstract and update te_players.elo for both genders."""
    from app.database import AsyncSessionLocal
    from app.models.rankings import TePlayer

    for gender in ("M", "F"):
        try:
            elo_map = await _fetch_ta_elo_page(gender)
            logger.info("ELO page fetched for gender=%s: %d entries", gender, len(elo_map))
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(TePlayer).where(TePlayer.gender == gender))
                players = res.scalars().all()
                updated = 0
                for tp in players:
                    tokens = frozenset(tp.name_norm.split())
                    new_elo = elo_map.get(tokens)
                    if new_elo and tp.elo != new_elo:
                        tp.elo = new_elo
                        updated += 1
                await db.commit()
                logger.info("ELO refresh (%s): %d/%d players updated", gender, updated, len(players))
        except Exception as exc:
            logger.warning("ELO refresh failed for gender=%s: %s", gender, exc)
            from app.services.system_log import app_log
            await app_log("error", "rankings", f"ELO refresh failed for {gender}: {exc}",
                          {"gender": gender, "error": str(exc)},
                          dedup_key=f"elo_fail_{gender}", dedup_hours=6)
