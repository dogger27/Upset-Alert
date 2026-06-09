"""
ATP/WTA ranking lookup using Jeff Sackmann's open datasets.
https://github.com/JeffSackmann/tennis_atp
https://github.com/JeffSackmann/tennis_wta
"""

import csv
import io
import re
import unicodedata
from datetime import date, timedelta
from typing import Optional

import httpx

_HEADERS = {"User-Agent": "TennisFantasyLeague/1.0 (https://github.com/local/tennis-fantasy)"}

_ATP_RANKINGS = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_rankings_current.csv"
_ATP_PLAYERS  = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_players.csv"
_WTA_RANKINGS = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/wta_rankings_current.csv"
_WTA_PLAYERS  = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/wta_players.csv"

# In-memory cache: (gender, date_str) -> {normalized_name: rank}
_cache: dict[tuple, dict[str, int]] = {}


def _norm(name: str) -> str:
    """Lowercase + strip accents for fuzzy name matching."""
    nfd = unicodedata.normalize("NFD", name)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower().strip()


def _clean_wiki_name(name: str) -> str:
    """Strip Wikipedia disambiguation suffixes like '(tennis)'."""
    return re.sub(r"\s*\([^)]+\)\s*$", "", name).strip()


async def fetch_rankings(gender: str, ref_date: date) -> dict[str, int]:
    """
    Return {normalized_full_name: ranking} for the ranking week on or
    immediately before ref_date.
    """
    cache_key = (gender, ref_date.strftime("%Y%m%d"))
    if cache_key in _cache:
        return _cache[cache_key]

    rankings_url = _ATP_RANKINGS if gender == "M" else _WTA_RANKINGS
    players_url  = _ATP_PLAYERS  if gender == "M" else _WTA_PLAYERS

    async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
        r_resp = await client.get(rankings_url)
        r_resp.raise_for_status()
        p_resp = await client.get(players_url)
        p_resp.raise_for_status()

    # --- Build player_id → full_name map ---
    player_names: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(p_resp.text)):
        pid = row.get("player_id", "")
        if pid:
            player_names[pid] = f"{row.get('name_first','')} {row.get('name_last','')}".strip()

    # --- Find closest date <= ref_date ---
    target_str = ref_date.strftime("%Y%m%d")
    rows = list(csv.reader(io.StringIO(r_resp.text)))
    # skip header
    data_rows = rows[1:]
    all_dates = sorted({r[0] for r in data_rows if r})
    valid = [d for d in all_dates if d <= target_str]
    if not valid:
        return {}
    best_date = valid[-1]

    # --- Extract rankings for that week ---
    result: dict[str, int] = {}
    for row in data_rows:
        if not row or row[0] != best_date:
            continue
        _, rank, player_id = row[0], int(row[1]), row[2]
        name = player_names.get(player_id)
        if name:
            result[_norm(name)] = rank

    _cache[cache_key] = result
    return result


def match_player_ranking(player_name: str, rankings: dict[str, int]) -> Optional[int]:
    """
    Look up a Wikipedia player name in the rankings dict.
    Tries exact normalized match first, then last-name-only fallback.
    """
    clean = _clean_wiki_name(player_name)
    key = _norm(clean)

    # 1. Exact normalized match
    if key in rankings:
        return rankings[key]

    # 2. Reversed two-word names — handles East Asian name order on Wikipedia
    #    e.g. "Zheng Qinwen" → try "Qinwen Zheng" to match Sackmann's given-name-first format
    parts = key.split()
    if len(parts) == 2:
        reversed_key = f"{parts[1]} {parts[0]}"
        if reversed_key in rankings:
            return rankings[reversed_key]

    # 3. Last name only (handles accent variants like "Menšík" vs "Mensik")
    last = parts[-1] if parts else key
    candidates = [(k, v) for k, v in rankings.items() if k.endswith(last)]
    if len(candidates) == 1:
        return candidates[0][1]

    return None
