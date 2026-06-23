"""
Head-to-head scraper for Tennis Explorer's /mutual/{slug1}/{slug2}/ pages.
Results are cached in h2h_cache keyed by canonical (alphabetically sorted) slug pair.
Cache TTL: 24 hours.

URL format discovered from TE's JS: /mutual/{urlSlug1}/{urlSlug2}/
Ranking page slugs look like: "sinner-8b8e8", "alcaraz-5ab70"
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

def _week_start_utc() -> datetime:
    """Return Monday 00:00:00 UTC of the current week."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now - timedelta(days=now.weekday(), hours=now.hour, minutes=now.minute, seconds=now.second, microseconds=now.microsecond)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _canonical_pair(slug1: str, slug2: str) -> tuple[str, str]:
    return (slug1, slug2) if slug1 <= slug2 else (slug2, slug1)


# ---------------------------------------------------------------------------
# HTML parser
# ---------------------------------------------------------------------------

def _parse_score_cell(raw: str) -> str:
    """Convert HTML score cell content like '6<sup>5</sup>' → '6(5)'."""
    raw = raw.strip()
    if raw in ("&nbsp;", ""):
        return ""
    return re.sub(r"<sup>(\d+)</sup>", r"(\1)", raw)


def _parse_h2h_html(html: str, slug_a: str, slug_b: str) -> dict:
    """Parse TE mutual page HTML into structured H2H data.

    Returns wins from slug_a's perspective: winner="a" means slug_a won that match.
    """
    # Overall score
    gscore_m = re.search(r'<td class="gScore">(\d+) - (\d+)</td>', html)
    wins_a = int(gscore_m.group(1)) if gscore_m else 0
    wins_b = int(gscore_m.group(2)) if gscore_m else 0

    # Player names from header (first two plName th elements)
    plname_ms = re.findall(r'<th class="plName"[^>]*><a href="[^"]+">(.*?)</a></th>', html)
    name_a = plname_ms[0].strip() if len(plname_ms) > 0 else slug_a
    name_b = plname_ms[1].strip() if len(plname_ms) > 1 else slug_b

    # Surname prefix used for name matching (TE abbreviates: "Sinner J.")
    name_a_surname = name_a.split()[0].lower() if name_a else ""
    name_b_surname = name_b.split()[0].lower() if name_b else ""

    # Match result table tbody (the one with "Round" header)
    tbody_m = re.search(
        r'<th class="round">Round</th>.*?</thead>(.*?)</tbody>\s*</table>',
        html, re.DOTALL,
    )
    if not tbody_m:
        return _empty(slug_a, slug_b, name_a, name_b, wins_a, wins_b)

    tbody = tbody_m.group(1)

    # All <tr class="one|two"> rows
    tr_rows = re.findall(r'<tr class="(?:one|two)">(.*?)</tr>', tbody, re.DOTALL)

    matches_out = []
    i = 0
    while i < len(tr_rows) - 1:
        row1 = tr_rows[i]
        row2 = tr_rows[i + 1]

        # First row of a pair always has sColorLong (surface indicator)
        if "sColorLong" not in row1:
            i += 1
            continue

        # Year
        year_m = re.search(r'<td class="first"[^>]*>(\d{4})</td>', row1)
        year = int(year_m.group(1)) if year_m else None

        # Tournament name (td.t-name with rowspan="2")
        tourn_m = re.search(r'<td class="t-name" rowspan="2"><a[^>]*>([^<]+)</a></td>', row1)
        tournament = tourn_m.group(1).strip() if tourn_m else None

        # Surface (span title inside sColorLong)
        surf_m = re.search(r'class="sColorLong"[^>]*>.*?<span title="([^"]+)"', row1, re.DOTALL)
        surface = surf_m.group(1).strip() if surf_m else None

        # Round
        round_m = re.search(r'<td class="round"[^>]*>([^<]+)</td>', row1)
        round_str = round_m.group(1).strip() if round_m else None
        if not round_str or round_str in ("&nbsp;", "\xa0"):
            round_str = None

        # Player name from td.t-name without rowspan attribute
        def extract_player(row: str) -> tuple[str, bool]:
            """Return (name, is_winner). Winner has <strong> tag."""
            m = re.search(r'<td class="t-name">(<strong>)?([^<]+?)(</strong>)?</td>', row)
            if not m:
                return "", False
            return m.group(2).strip(), bool(m.group(1))

        p1_name, p1_won = extract_player(row1)
        p2_name, _ = extract_player(row2)

        # Score cells for each row
        def extract_scores(row: str) -> list[str]:
            cells = re.findall(r'<td class="score">(.*?)</td>', row, re.DOTALL)
            result = []
            for c in cells:
                s = _parse_score_cell(c)
                if not s:
                    break
                result.append(s)
            return result

        p1_scores = extract_scores(row1)
        p2_scores = extract_scores(row2)

        # Map p1/p2 to slug_a/slug_b via surname matching
        p1_lower = p1_name.lower()
        p2_lower = p2_name.lower()
        p1_is_a = bool(name_a_surname) and p1_lower.startswith(name_a_surname)
        p2_is_a = bool(name_a_surname) and p2_lower.startswith(name_a_surname)

        if p1_is_a:
            scores_a, scores_b = p1_scores, p2_scores
            winner = "a" if p1_won else "b"
        elif p2_is_a:
            scores_a, scores_b = p2_scores, p1_scores
            winner = "b" if p1_won else "a"
        else:
            i += 2
            continue

        # Build score string from slug_a's perspective
        score_parts = []
        for j in range(max(len(scores_a), len(scores_b))):
            sa = scores_a[j] if j < len(scores_a) else ""
            sb = scores_b[j] if j < len(scores_b) else ""
            if sa or sb:
                score_parts.append(f"{sa}-{sb}")
        score_str = ", ".join(score_parts)

        matches_out.append({
            "year": year,
            "tournament": tournament,
            "surface": surface,
            "round": round_str,
            "winner": winner,
            "score": score_str,
        })

        i += 2

    # Surface breakdown
    surface_wins: dict[str, list[int]] = {}
    for m in matches_out:
        surf = m.get("surface")
        if not surf:
            continue
        if surf not in surface_wins:
            surface_wins[surf] = [0, 0]
        if m["winner"] == "a":
            surface_wins[surf][0] += 1
        else:
            surface_wins[surf][1] += 1

    return {
        "slug_a": slug_a,
        "slug_b": slug_b,
        "name_a": name_a,
        "name_b": name_b,
        "wins_a": wins_a,
        "wins_b": wins_b,
        "surface_wins": surface_wins,
        "matches": matches_out,
    }


def _empty(slug_a, slug_b, name_a, name_b, wins_a=0, wins_b=0) -> dict:
    return {
        "slug_a": slug_a, "slug_b": slug_b,
        "name_a": name_a, "name_b": name_b,
        "wins_a": wins_a, "wins_b": wins_b,
        "surface_wins": {}, "matches": [],
    }


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

async def _scrape_h2h(slug_a: str, slug_b: str) -> dict:
    import httpx

    url = f"https://www.tennisexplorer.com/mutual/{slug_a}/{slug_b}/"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers=_HEADERS)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        logger.warning("H2H scrape failed for %s vs %s: %s", slug_a, slug_b, exc)
        from app.services.system_log import app_log
        await app_log("warning", "h2h", f"H2H scrape failed: {slug_a} vs {slug_b}",
                      {"slug_a": slug_a, "slug_b": slug_b, "error": str(exc)},
                      dedup_key=f"h2h_fail_{slug_a}_{slug_b}", dedup_hours=6)
        return {**_empty(slug_a, slug_b, slug_a, slug_b), "error": str(exc)}

    return _parse_h2h_html(html, slug_a, slug_b)


# ---------------------------------------------------------------------------
# Public entry point (with cache)
# ---------------------------------------------------------------------------

async def get_h2h(slug1: str, slug2: str, db: AsyncSession) -> dict:
    """Return H2H data, refreshing the cache if it was fetched before Monday of the current week."""
    from app.models.h2h import H2HCache

    slug_a, slug_b = _canonical_pair(slug1, slug2)

    cached = await db.get(H2HCache, (slug_a, slug_b))
    if cached and cached.fetched_at >= _week_start_utc():
        return cached.data_json

    data = await _scrape_h2h(slug_a, slug_b)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stmt = sqlite_insert(H2HCache).values(
        slug_a=slug_a, slug_b=slug_b, fetched_at=now, data_json=data
    ).on_conflict_do_update(
        index_elements=["slug_a", "slug_b"],
        set_={"fetched_at": now, "data_json": data},
    )
    await db.execute(stmt)
    await db.commit()
    return data


async def prefetch_h2h_for_draw(tournament_id: int) -> None:
    """
    After a draw is refreshed, fetch H2H for every matchup that hasn't been attempted yet.
    Creates its own DB session so it can run after the caller's session has committed.
    Silently skips pairs already in h2h_cache (success or prior failure).
    """
    from app.database import AsyncSessionLocal
    from app.models.h2h import H2HCache
    from app.models.rankings import TePlayer
    from app.models.tournament import DrawEntry, Match

    async with AsyncSessionLocal() as db:
        # Collect all non-bye matches with two known players
        matches_res = await db.execute(
            select(Match.player1_id, Match.player2_id)
            .where(
                Match.tournament_id == tournament_id,
                Match.is_bye == False,
                Match.player1_id.isnot(None),
                Match.player2_id.isnot(None),
            )
        )
        player_id_pairs = matches_res.all()
        if not player_id_pairs:
            return

        all_player_ids = {pid for row in player_id_pairs for pid in row}

        # te_player_id for each tournament player
        p_res = await db.execute(
            select(DrawEntry.id, DrawEntry.te_player_id)
            .where(DrawEntry.id.in_(all_player_ids), DrawEntry.te_player_id.isnot(None))
        )
        te_id_by_player: dict[int, int] = {r.id: r.te_player_id for r in p_res}

        # te_slug for each te_player
        te_ids = set(te_id_by_player.values())
        if not te_ids:
            return

        slug_res = await db.execute(
            select(TePlayer.id, TePlayer.te_slug)
            .where(TePlayer.id.in_(te_ids), TePlayer.te_slug.isnot(None))
        )
        slug_by_te_id: dict[int, str] = {r.id: r.te_slug for r in slug_res}

        # Build canonical slug pairs for all matchups
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for p1_id, p2_id in player_id_pairs:
            te1 = te_id_by_player.get(p1_id)
            te2 = te_id_by_player.get(p2_id)
            if not te1 or not te2:
                continue
            s1 = slug_by_te_id.get(te1)
            s2 = slug_by_te_id.get(te2)
            if not s1 or not s2:
                continue
            pair = _canonical_pair(s1, s2)
            if pair not in seen:
                seen.add(pair)
                pairs.append(pair)

        if not pairs:
            return

        # Check which pairs are already in cache (success or failure)
        cached_res = await db.execute(
            select(H2HCache.slug_a, H2HCache.slug_b).where(
                or_(*[
                    and_(H2HCache.slug_a == a, H2HCache.slug_b == b)
                    for a, b in pairs
                ])
            )
        )
        already_attempted = {(r.slug_a, r.slug_b) for r in cached_res}

        to_fetch = [p for p in pairs if p not in already_attempted]
        if not to_fetch:
            return

        logger.info("H2H prefetch: %d new pair(s) for tournament %d", len(to_fetch), tournament_id)

        for slug_a, slug_b in to_fetch:
            data = await _scrape_h2h(slug_a, slug_b)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            stmt = sqlite_insert(H2HCache).values(
                slug_a=slug_a, slug_b=slug_b, fetched_at=now, data_json=data
            ).on_conflict_do_update(
                index_elements=["slug_a", "slug_b"],
                set_={"fetched_at": now, "data_json": data},
            )
            await db.execute(stmt)
            await db.flush()
            await asyncio.sleep(0.4)  # be polite to TE

        await db.commit()
        logger.info("H2H prefetch complete for tournament %d", tournament_id)
