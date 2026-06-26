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
    r'<td class="rank first">(\d+)\.</td>.*?<td class="t-name"><a href="([^"]+)">(.*?)</a></td>.*?<td class="long-point">(\d+)</td>',
    re.DOTALL,
)
_TE_SLUG_RE = re.compile(r'^/player/([^/]+)/?$')

# Per-(gender, week_date): (te_index, rank_by_te_id)
# Avoids reloading thousands of rows from SQLite on every assign_rankings call.
_week_cache: dict[tuple, tuple[dict, dict, dict]] = {}

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
    # Rejection guard: if both wiki and TE have exclusive tokens that share no 3-char prefix,
    # the names are contradicting (different first names sharing a surname) — skip.
    # e.g. "Serena Williams" must not match Venus Williams via the shared "williams" token.
    for tok in wiki_ts:
        tok_hits = [id for te_ts, ids in te_index.items() if tok in te_ts for id in ids]
        if len(tok_hits) == 1:
            te_id = tok_hits[0]
            te_ts_match = next(te_ts for te_ts, ids in te_index.items() if te_id in ids)
            wiki_extra = wiki_ts - te_ts_match
            te_extra = te_ts_match - wiki_ts
            if wiki_extra and te_extra:
                # Both sides have tokens the other doesn't — check prefix similarity.
                # Spelling variants (Greet/Greetje, Darya/Daria) share a 3-char prefix;
                # completely different names (Serena/Venus) do not.
                if not any(
                    we[:3] == te[:3]
                    for we in wiki_extra for te in te_extra
                ):
                    continue
            return te_id

    # Rule 5: wiki token is a strict prefix of a unique TE token (min 4 chars).
    # Catches nicknames/abbreviations: "rafa" → "rafael", "stan" → "stanislas".
    for tok in wiki_ts:
        if len(tok) < 4:
            continue
        prefix_hits: list[int] = []
        for te_ts, ids in te_index.items():
            if any(te_tok.startswith(tok) and te_tok != tok for te_tok in te_ts):
                prefix_hits.extend(ids)
        if len(prefix_hits) == 1:
            te_id = prefix_hits[0]
            te_ts_match = next(te_ts for te_ts, ids in te_index.items() if te_id in ids)
            wiki_extra = wiki_ts - te_ts_match
            te_extra = te_ts_match - wiki_ts
            if wiki_extra and te_extra:
                if not any(we[:3] == te[:3] for we in wiki_extra for te in te_extra):
                    continue
            return te_id

    return None


def _build_te_index(
    te_players: list,
) -> tuple[dict[frozenset, list[int]], dict[int, str]]:
    """
    Build two complementary indices from a list of TePlayer ORM objects:
      - token-set index: frozenset → [player_id]  (for Rules 1–5)
      - norm index:      player_id → name_norm     (for fuzzy fallback)
    """
    index: dict[frozenset, list[int]] = {}
    id_to_norm: dict[int, str] = {}
    for tp in te_players:
        ts = frozenset(tp.name_norm.split())
        index.setdefault(ts, []).append(tp.id)
        id_to_norm[tp.id] = tp.name_norm
    return index, id_to_norm


def _fuzzy_match_te(wiki_name: str, id_to_norm: dict[int, str]) -> Optional[int]:
    """
    Last-resort fuzzy fallback using difflib SequenceMatcher.

    Compares the sorted-token normalized wiki name against every TE player's
    sorted-token name_norm (order-independent). Returns a player_id only when
    there is a unique best match ≥ 0.85 similarity that is at least 0.10 ahead
    of the second-best candidate — tight enough to avoid false positives.

    Catches genuine spelling variants (Tatjana/Tatiana, Jiri/Jiri) that Rules
    1–5 miss because the token strings differ by more than a prefix.
    """
    from difflib import SequenceMatcher

    wiki_sorted = " ".join(sorted(_norm(_clean_wiki_name(wiki_name)).split()))
    if not wiki_sorted:
        return None

    best_ratio = 0.0
    second_ratio = 0.0
    best_id: Optional[int] = None

    for te_id, te_norm in id_to_norm.items():
        te_sorted = " ".join(sorted(te_norm.split()))
        ratio = SequenceMatcher(None, wiki_sorted, te_sorted, autojunk=False).ratio()
        if ratio > best_ratio:
            second_ratio = best_ratio
            best_ratio = ratio
            best_id = te_id
        elif ratio > second_ratio:
            second_ratio = ratio

    if best_ratio >= 0.85 and (best_ratio - second_ratio) >= 0.10:
        return best_id
    return None


# ---------------------------------------------------------------------------
# Tennis Explorer scraper
# ---------------------------------------------------------------------------

async def _scrape_te(gender: str, week_date: Optional[date] = None, log_errors: bool = True) -> list[tuple[str, int, Optional[str], Optional[int]]]:
    """
    Scrape all pages of Tennis Explorer rankings for the given gender.
    Returns [(name_raw, rank, te_slug, points), ...] in TE's "Surname Firstname" format.
    te_slug is the URL slug from the player's TE profile, e.g. "sinner-jannik".
    Pass week_date to scrape historical rankings for a specific date.
    Pass log_errors=False to suppress app_log entries (e.g. best-effort weekly check).
    """
    import httpx

    url = _TE_URLS[gender]
    base_params: dict = {"date": week_date.isoformat()} if week_date else {}
    results: list[tuple[str, int, Optional[str], Optional[int]]] = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            page = 1
            while True:
                params = {**base_params, "page": page}
                resp = await client.get(url, params=params, headers=_TE_HEADERS)
                resp.raise_for_status()
                rows = _TE_ROW_RE.findall(resp.text)
                if not rows:
                    break
                for rank_str, href, raw_name, pts_str in rows:
                    slug_m = _TE_SLUG_RE.match(href)
                    slug = slug_m.group(1) if slug_m else None
                    points = int(pts_str) if pts_str else None
                    results.append((raw_name.strip(), int(rank_str), slug, points))
                page += 1
                await asyncio.sleep(0.1)
        logger.info("Tennis Explorer %s scrape: %d players across %d pages", gender, len(results), page - 1)
    except Exception as exc:
        logger.warning("Tennis Explorer %s scrape failed: %s", gender, exc)
        if log_errors:
            from app.services.system_log import app_log
            await app_log("error", "rankings", f"Tennis Explorer {gender} scrape failed: {exc}",
                          {"gender": gender, "error": str(exc)},
                          dedup_key=f"te_scrape_fail_{gender}", dedup_hours=2)

    return results


# ---------------------------------------------------------------------------
# DB-backed ranking management
# ---------------------------------------------------------------------------

async def ensure_te_week(gender: str, week_date: date, db: AsyncSession, log_errors: bool = True) -> bool:
    """
    Ensure te_rankings_snapshots has data for (gender, week_date).
    Scrapes Tennis Explorer and stores results if the week is absent.
    Returns True if a scrape was performed.
    Pass log_errors=False to suppress app_log entries (e.g. best-effort weekly check).
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
    raw_rows = await _scrape_te(gender, week_date=week_date, log_errors=log_errors)
    if len(raw_rows) < 50:
        logger.info("TE %s scrape returned only %d players — no rankings stored for week %s",
                    gender, len(raw_rows), week_date)
        if log_errors:
            from app.services.system_log import app_log
            await app_log("warning", "rankings", f"TE {gender} scrape returned only {len(raw_rows)} players — aborting",
                          {"gender": gender, "count": len(raw_rows)},
                          dedup_key=f"te_scrape_low_{gender}", dedup_hours=2)
        return False

    existing_players_res = await db.execute(
        select(TePlayer).where(TePlayer.gender == gender)
    )
    all_existing = list(existing_players_res.scalars())
    existing_by_raw: dict[str, TePlayer] = {p.name_raw: p for p in all_existing}
    # Frozenset index catches stubs created from draw players (Wikipedia "First Last" format)
    # that share the same token set as a newly scraped TE name ("Last First" format).
    existing_by_ts: dict[frozenset, TePlayer] = {
        frozenset(p.name_norm.split()): p for p in all_existing
    }

    for name_raw, rank, slug, points in raw_rows:
        tp = existing_by_raw.get(name_raw)
        if tp is None:
            # Check for a stub created from a draw player with the same token set.
            ts = frozenset(_norm(name_raw).split())
            tp = existing_by_ts.get(ts)
            if tp is not None:
                # Upgrade stub: update to TE canonical name and slug.
                tp.name_raw = name_raw
                tp.name_norm = _norm(name_raw)
                if slug and tp.te_slug is None:
                    tp.te_slug = slug
            else:
                tp = TePlayer(gender=gender, name_raw=name_raw, name_norm=_norm(name_raw), te_slug=slug)
                db.add(tp)
                await db.flush()
            existing_by_raw[name_raw] = tp
            existing_by_ts[frozenset(_norm(name_raw).split())] = tp
        elif slug and tp.te_slug is None:
            tp.te_slug = slug

        snap = await db.get(TeRankingsSnapshot, (tp.id, week_date))
        if snap is None:
            db.add(TeRankingsSnapshot(player_id=tp.id, week_date=week_date, rank=rank, points=points))
        else:
            snap.rank = rank
            snap.points = points

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
        te_index, id_to_norm = _build_te_index(tp_res.scalars().all())

        snap_res = await db.execute(
            select(TeRankingsSnapshot).where(TeRankingsSnapshot.week_date == week_date)
        )
        rank_by_te_id: dict[int, int] = {s.player_id: s.rank for s in snap_res.scalars()}
        _week_cache[cache_key] = (te_index, rank_by_te_id, id_to_norm)
        logger.info("Loaded TE index for %s week %s into memory (%d players)", gender, week_date, len(te_index))
    else:
        te_index, rank_by_te_id, id_to_norm = _week_cache[cache_key]

    from app.models.rankings import TePlayer
    from app.services.system_log import app_log
    for player in players:
        if player.te_player_id is None:
            te_id = _match_token_set(player.name, te_index)
            if te_id is not None:
                player.te_player_id = te_id
            elif player.name and player.entry_type not in ("Q", "LL"):
                # Fallback 1: fuzzy difflib match against all TE players in our DB.
                # Catches spelling variants (Tatjana/Tatiana) that token rules miss.
                te_id = _fuzzy_match_te(player.name, id_to_norm)
                if te_id is not None:
                    player.te_player_id = te_id
                    await app_log("info", "rankings",
                                  f"Fuzzy-matched {player.name!r} to TE player {te_id}",
                                  {"player_name": player.name, "te_id": te_id},
                                  dedup_key=f"fuzzy_match_{player.name.lower()}", dedup_hours=168)
                    player.ranking = rank_by_te_id.get(te_id)
                    continue

                # Fallback 2: TE list-players search then slug-guess for unranked players.
                slug, name_display, dob, first_name, last_name = await _find_te_player(player.name, gender)
                await app_log(
                    "warning" if not slug else "info",
                    "rankings",
                    f"Player not matched in TE rankings: {player.name!r}"
                    + (f" — found via TE profile (slug={slug!r})" if slug else " — no TE profile found"),
                    {"player_name": player.name, "gender": gender, "te_slug": slug},
                    dedup_key=f"match_fail_{player.name.lower()}", dedup_hours=24,
                )
                new_tp = TePlayer(
                    gender=gender,
                    name_raw=player.name,
                    name_norm=_norm(player.name),
                    te_slug=slug,
                    name_display=name_display or player.name,
                    first_name=first_name,
                    last_name=last_name,
                    date_of_birth=dob,
                )
                db.add(new_tp)
                await db.flush()
                player.te_player_id = new_tp.id
                # Update in-memory indices so the same player in this draw session matches.
                ts = frozenset(_norm(player.name).split())
                te_index.setdefault(ts, []).append(new_tp.id)
                id_to_norm[new_tp.id] = _norm(player.name)

        player.ranking = rank_by_te_id.get(player.te_player_id) if player.te_player_id else None


# ---------------------------------------------------------------------------
# Date-of-birth scraper
# ---------------------------------------------------------------------------

# TE page format: Age: 24 (16. 8. 2001)  →  day=16, month=8, year=2001
_DOB_RE = re.compile(r'Age:\s*\d+\s*\((\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\)')
# TE profile page title: "Felix Auger Aliassime - Tennis Explorer"
_TITLE_RE = re.compile(r'<title>([^<]+?)\s*-\s*Tennis Explorer\s*</title>', re.IGNORECASE)


async def _fetch_te_player_profile(te_slug: str) -> tuple[Optional[date], Optional[str]]:
    """
    Scrape DOB and display name from a TE player profile page.
    Returns (dob, name_display) — either may be None on parse failure.
    """
    import httpx

    url = f"https://www.tennisexplorer.com/player/{te_slug}/"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=_TE_HEADERS)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        logger.debug("Profile fetch failed for %s: %s", te_slug, exc)
        return None, None

    dob: Optional[date] = None
    dob_m = _DOB_RE.search(html)
    if dob_m:
        try:
            dob = date(int(dob_m.group(3)), int(dob_m.group(2)), int(dob_m.group(1)))
        except ValueError:
            pass

    name_display: Optional[str] = None
    title_m = _TITLE_RE.search(html)
    if title_m:
        name_display = title_m.group(1).strip() or None

    return dob, name_display


def _parse_profile_html(html: str) -> tuple[Optional[date], Optional[str]]:
    """Extract DOB and name_display from a pre-fetched TE profile page."""
    dob: Optional[date] = None
    dob_m = _DOB_RE.search(html)
    if dob_m:
        try:
            dob = date(int(dob_m.group(3)), int(dob_m.group(2)), int(dob_m.group(1)))
        except ValueError:
            pass
    name_display: Optional[str] = None
    title_m = _TITLE_RE.search(html)
    if title_m:
        name_display = title_m.group(1).strip() or None
    return dob, name_display


# TE alphabetical player list: <a href="/player/auger-aliassime/">Auger Aliassime Felix</a>
_TE_LIST_ENTRY_RE = re.compile(r'<a\s[^>]*href="(/player/[^"]+)"[^>]*>([^<]+)</a>')


async def _search_te_list(
    display_name: str, gender: str
) -> tuple[Optional[str], Optional[str]]:
    """
    Search TE's alphabetical /list-players/ pages for a player by display name.

    TE names on the list are in "Surname Firstname" order — the same format as
    our ranking pages — so token-set matching works directly.  This is far more
    reliable than slug guessing because it covers hash-disambiguated slugs like
    "ponchet-8cae2" that can never be derived from the name alone.

    Returns (te_slug, name_raw_te) with name_raw_te in TE "Surname First" format,
    or (None, None) if not found.
    """
    import httpx

    tokens_norm = _norm(display_name).split()
    if len(tokens_norm) < 2:
        return None, None

    target_ts = frozenset(tokens_norm)
    te_type = "atp" if gender == "M" else "wta"

    # Try the first letter of every token except the first (which is usually the
    # given name).  Deduplication avoids fetching the same letter page twice.
    letters_tried: set[str] = set()
    letters = []
    for tok in tokens_norm[1:]:
        letter = tok[0].upper()
        if letter not in letters_tried:
            letters_tried.add(letter)
            letters.append(letter)

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for letter in letters:
            try:
                resp = await client.get(
                    "https://www.tennisexplorer.com/list-players/",
                    params={"type": te_type, "abc": letter},
                    headers=_TE_HEADERS,
                )
                if resp.status_code != 200:
                    await asyncio.sleep(0.3)
                    continue
                html = resp.text
            except Exception as exc:
                logger.debug("TE list-players fetch failed for letter %s: %s", letter, exc)
                await asyncio.sleep(0.3)
                continue

            for href, link_name in _TE_LIST_ENTRY_RE.findall(html):
                slug_m = _TE_SLUG_RE.match(href)
                if not slug_m:
                    continue
                link_name = link_name.strip()
                if not link_name:
                    continue
                te_ts = frozenset(_norm(link_name).split())
                # Accept exact set match or proper subset in either direction (same
                # logic as Rules 1–3 in _apply_rules).
                if te_ts == target_ts or (target_ts < te_ts) or (len(te_ts) >= 2 and te_ts < target_ts):
                    return slug_m.group(1), link_name

            await asyncio.sleep(0.3)

    return None, None


async def _find_te_player(
    display_name: str,
    gender: str = "M",
) -> tuple[Optional[str], Optional[str], Optional[date], Optional[str], Optional[str]]:
    """
    Discover a TE player not yet in our rankings.  Three-stage fallback:

    1. TE alphabetical list-players pages — reliable, covers all TE players
       including those with hash-disambiguated slugs (e.g. "ponchet-8cae2").
       Returns the TE raw name ("Surname First"), so first/last split is exact.

    2. Slug guessing — derives candidates from the Wikipedia display name and
       validates each by fetching the profile and checking the title token set.
       Covers compound surnames ("auger-aliassime") and simple surnames ("sinner").

    3. If both fail: returns (None, None, None, None, None).  The caller creates
       a minimal record with name_display from the Wikipedia name.

    Returns (te_slug, name_display, dob, first_name, last_name).
    """
    import httpx

    tokens_norm = _norm(display_name).split()
    disp_tokens = display_name.split()
    if len(tokens_norm) < 2:
        return None, None, None, None, None

    target_ts = frozenset(tokens_norm)

    # ------------------------------------------------------------------
    # Stage 1: TE alphabetical list search (authoritative)
    # ------------------------------------------------------------------
    slug, name_raw_te = await _search_te_list(display_name, gender)
    if slug:
        dob, name_display = await _fetch_te_player_profile(slug)
        await asyncio.sleep(0.3)
        # name_raw_te is in TE "Surname First" format — use it to split.
        first_name, last_name = _split_display_name(name_raw_te, name_display or display_name)
        return slug, name_display or display_name, dob, first_name, last_name

    # ------------------------------------------------------------------
    # Stage 2: slug guessing (heuristic, no hash-disambiguated slugs)
    # ------------------------------------------------------------------
    candidates: list[tuple[str, str]] = []
    slug_a = "-".join(tokens_norm[1:])
    candidates.append((slug_a, "compound"))
    slug_b = tokens_norm[-1]
    if slug_b != slug_a:
        candidates.append((slug_b, "last"))

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for slug_cand, mode in candidates:
            try:
                resp = await client.get(
                    f"https://www.tennisexplorer.com/player/{slug_cand}/",
                    headers=_TE_HEADERS,
                )
                if resp.status_code != 200:
                    await asyncio.sleep(0.3)
                    continue
                html = resp.text
            except Exception as exc:
                logger.debug("TE slug probe failed for %r: %s", slug_cand, exc)
                await asyncio.sleep(0.3)
                continue

            title_m = _TITLE_RE.search(html)
            if not title_m:
                await asyncio.sleep(0.3)
                continue
            page_name = title_m.group(1).strip()
            if frozenset(_norm(page_name).split()) != target_ts:
                await asyncio.sleep(0.3)
                continue

            dob, name_display = _parse_profile_html(html)
            first_name: Optional[str] = None
            last_name: Optional[str] = None
            if mode == "compound":
                first_name = disp_tokens[0]
                last_name = " ".join(disp_tokens[1:])
            elif mode == "last" and len(disp_tokens) == 2:
                first_name = disp_tokens[0]
                last_name = disp_tokens[1]

            return slug_cand, name_display or display_name, dob, first_name, last_name

    return None, None, None, None, None


def _split_display_name(name_raw: str, name_display: str) -> tuple[Optional[str], Optional[str]]:
    """
    Given TE raw name ("Surname First") and display name ("First Surname"),
    determine the first/last split by finding the suffix of name_raw tokens
    that matches the prefix of name_display tokens.

    Returns (first_name, last_name) or (None, None) if the split is ambiguous.
    """
    raw_tokens = name_raw.split()
    disp_tokens = name_display.split()
    if len(raw_tokens) != len(disp_tokens) or len(raw_tokens) < 2:
        return None, None

    raw_lower = [t.lower() for t in raw_tokens]
    disp_lower = [t.lower() for t in disp_tokens]

    for fn_count in range(1, len(raw_tokens)):
        if raw_lower[-fn_count:] == disp_lower[:fn_count] and raw_lower[:-fn_count] == disp_lower[fn_count:]:
            return " ".join(disp_tokens[:fn_count]), " ".join(disp_tokens[fn_count:])

    return None, None


async def prefetch_dob_for_draw(tournament_id: int) -> None:
    """
    After a draw is refreshed, fetch DOB and display name from TE for any linked
    te_players in this draw that are still missing data. Creates its own DB session.

    Two phases:
      1. Players with a known te_slug: fetch profile directly.
      2. Players without a te_slug: probe TE to discover the slug + full profile.
    """
    from app.database import AsyncSessionLocal
    from app.models.rankings import TePlayer
    from app.models.tournament import DrawEntry
    from sqlalchemy import or_

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(TePlayer)
            .join(DrawEntry, DrawEntry.te_player_id == TePlayer.id)
            .where(
                DrawEntry.tournament_id == tournament_id,
                or_(
                    TePlayer.date_of_birth.is_(None),
                    TePlayer.name_display.is_(None),
                    TePlayer.first_name.is_(None),
                ),
            )
            .distinct()
        )
        missing = res.scalars().all()
        if not missing:
            return

        # Phase 1: players with a known slug — just fetch their profile.
        with_slug = [tp for tp in missing if tp.te_slug is not None]
        # Phase 2: players with no slug — probe TE to find them.
        without_slug = [tp for tp in missing if tp.te_slug is None]

        logger.info(
            "Profile prefetch: %d with slug, %d without slug (tournament %d)",
            len(with_slug), len(without_slug), tournament_id,
        )

        for tp in with_slug:
            if tp.name_display and tp.first_name is None:
                first_name, last_name = _split_display_name(tp.name_raw, tp.name_display)
                if first_name:
                    tp.first_name = first_name
                    tp.last_name = last_name
                    continue
            dob, name_display = await _fetch_te_player_profile(tp.te_slug)
            if dob and tp.date_of_birth is None:
                tp.date_of_birth = dob
            if name_display and tp.name_display is None:
                tp.name_display = name_display
                first_name, last_name = _split_display_name(tp.name_raw, name_display)
                if first_name:
                    tp.first_name = first_name
                    tp.last_name = last_name
            await asyncio.sleep(0.3)

        for tp in without_slug:
            search_name = tp.name_display or tp.name_raw
            slug, name_display, dob, first_name, last_name = await _find_te_player(search_name, tp.gender)
            if slug:
                tp.te_slug = slug
            if name_display:
                tp.name_display = name_display
            if dob and tp.date_of_birth is None:
                tp.date_of_birth = dob
            if first_name and tp.first_name is None:
                tp.first_name = first_name
                tp.last_name = last_name
            await asyncio.sleep(0.3)

        await db.commit()
        logger.info("Profile prefetch complete for tournament %d", tournament_id)


async def backfill_all_dob() -> dict:
    """
    Admin backfill: for every te_player with a slug that is missing DOB,
    name_display, or first_name, fetch the TE profile page and/or compute names.
    Creates its own DB session. Safe to call multiple times.
    """
    from app.database import AsyncSessionLocal
    from app.models.rankings import TePlayer
    from sqlalchemy import or_

    _BATCH = 50  # rows per commit — progress is visible and deploys don't erase work

    async with AsyncSessionLocal() as db:
        # Load IDs upfront so the batch loop is bounded regardless of HTTP failures.
        # On restart, already-committed players are excluded by the where clause.

        # Phase 1: players with a slug — fetch/compute missing fields.
        id_res = await db.execute(
            select(TePlayer.id).where(
                TePlayer.te_slug.isnot(None),
                or_(
                    TePlayer.date_of_birth.is_(None),
                    TePlayer.name_display.is_(None),
                    TePlayer.first_name.is_(None),
                ),
            )
        )
        p1_ids = id_res.scalars().all()
        logger.info("Profile backfill phase 1: %d players with slug to process", len(p1_ids))

        updated = 0
        for batch_start in range(0, len(p1_ids), _BATCH):
            batch_ids = p1_ids[batch_start: batch_start + _BATCH]
            res = await db.execute(select(TePlayer).where(TePlayer.id.in_(batch_ids)))
            batch = res.scalars().all()

            for tp in batch:
                changed = False
                if tp.name_display and tp.first_name is None:
                    first_name, last_name = _split_display_name(tp.name_raw, tp.name_display)
                    if first_name:
                        tp.first_name = first_name
                        tp.last_name = last_name
                        changed = True
                if tp.date_of_birth is None or tp.name_display is None:
                    dob, name_display = await _fetch_te_player_profile(tp.te_slug)
                    if dob and tp.date_of_birth is None:
                        tp.date_of_birth = dob
                        changed = True
                    if name_display and tp.name_display is None:
                        tp.name_display = name_display
                        first_name, last_name = _split_display_name(tp.name_raw, name_display)
                        if first_name:
                            tp.first_name = first_name
                            tp.last_name = last_name
                        changed = True
                    await asyncio.sleep(0.3)
                if changed:
                    updated += 1

            await db.commit()
            done = min(batch_start + _BATCH, len(p1_ids))
            logger.info("Profile backfill phase 1: %d/%d committed", done, len(p1_ids))

        # Phase 2: players with no slug — search TE to discover and fully populate.
        id_res2 = await db.execute(
            select(TePlayer.id).where(TePlayer.te_slug.is_(None))
        )
        p2_ids = id_res2.scalars().all()
        logger.info("Profile backfill phase 2: %d players without slug to process", len(p2_ids))

        slug_found = 0
        for batch_start in range(0, len(p2_ids), _BATCH):
            batch_ids = p2_ids[batch_start: batch_start + _BATCH]
            res = await db.execute(select(TePlayer).where(TePlayer.id.in_(batch_ids)))
            batch = res.scalars().all()

            for tp in batch:
                search_name = tp.name_display or tp.name_raw
                slug, name_display, dob, first_name, last_name = await _find_te_player(search_name, tp.gender)
                changed = False
                if slug:
                    tp.te_slug = slug
                    slug_found += 1
                    changed = True
                if name_display and tp.name_display is None:
                    tp.name_display = name_display
                    changed = True
                if dob and tp.date_of_birth is None:
                    tp.date_of_birth = dob
                    changed = True
                if first_name and tp.first_name is None:
                    tp.first_name = first_name
                    tp.last_name = last_name
                    changed = True
                if changed:
                    updated += 1
                await asyncio.sleep(0.3)

            await db.commit()
            done = min(batch_start + _BATCH, len(p2_ids))
            logger.info("Profile backfill phase 2: %d/%d committed", done, len(p2_ids))

        total = len(p1_ids) + len(p2_ids)
        logger.info(
            "Profile backfill complete: %d/%d updated, %d slugs discovered",
            updated, total, slug_found,
        )
        return {"total": total, "updated": updated, "failed": total - updated, "slugs_found": slug_found}

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
    """
    Fetch Elo from Tennis Abstract and store on te_rankings_snapshots for the
    most recent ranking week. Elo is weekly data and does not belong on te_players.
    """
    from app.database import AsyncSessionLocal
    from app.models.rankings import TePlayer, TeRankingsSnapshot

    for gender in ("M", "F"):
        try:
            elo_map = await _fetch_ta_elo_page(gender)
            logger.info("ELO page fetched for gender=%s: %d entries", gender, len(elo_map))
            async with AsyncSessionLocal() as db:
                # Find the most recent ranking week for this gender.
                week_res = await db.execute(
                    select(TeRankingsSnapshot.week_date)
                    .join(TePlayer, TeRankingsSnapshot.player_id == TePlayer.id)
                    .where(TePlayer.gender == gender)
                    .order_by(TeRankingsSnapshot.week_date.desc())
                    .limit(1)
                )
                week_date = week_res.scalar_one_or_none()
                if week_date is None:
                    logger.info("ELO refresh (%s): no ranking week found, skipping", gender)
                    continue

                # Load all snapshots for that week alongside player name_norm.
                snap_res = await db.execute(
                    select(TeRankingsSnapshot, TePlayer.name_norm)
                    .join(TePlayer, TeRankingsSnapshot.player_id == TePlayer.id)
                    .where(
                        TePlayer.gender == gender,
                        TeRankingsSnapshot.week_date == week_date,
                    )
                )
                rows = snap_res.all()

                # Assign elo to each snapshot row.
                for snap, name_norm in rows:
                    tokens = frozenset(name_norm.split())
                    snap.elo = elo_map.get(tokens) or None

                # Assign elo_rank: sort by elo desc; unmatched players get None.
                ranked = sorted(
                    [(snap, snap.elo) for snap, _ in rows if snap.elo is not None],
                    key=lambda t: t[1],
                    reverse=True,
                )
                ranked_ids = {snap.player_id for snap, _ in ranked}
                for pos, (snap, _) in enumerate(ranked, start=1):
                    snap.elo_rank = pos
                for snap, _ in rows:
                    if snap.player_id not in ranked_ids:
                        snap.elo_rank = None

                await db.commit()
                logger.info("ELO refresh (%s): %d/%d players ranked for week %s",
                            gender, len(ranked), len(rows), week_date)
        except Exception as exc:
            logger.warning("ELO refresh failed for gender=%s: %s", gender, exc)
            from app.services.system_log import app_log
            await app_log("error", "rankings", f"ELO refresh failed for {gender}: {exc}",
                          {"gender": gender, "error": str(exc)},
                          dedup_key=f"elo_fail_{gender}", dedup_hours=6)
