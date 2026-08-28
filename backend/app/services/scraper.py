"""
Wikipedia bracket scraper for tennis tournament draws.

Supports 16TeamBracket-Compact-Tennis5/3 sections (R1→R4) and the
8TeamBracket-Tennis5/3 finals section (QF→F), covering 32/64/128-player draws.
"""

import html
import asyncio
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import httpx

WIKI_API = "https://en.wikipedia.org/w/api.php"

# Entry designations that appear in a draw's seed column. SE (special exempt),
# Alt (alternate) and NG were missing here, so every player carrying one was
# parsed to entry_type=None and lost their badge — the frontend had shipped a
# .pos-badge.entry-se style for a value the scraper could never produce.
# Matched case-insensitively via _ENTRY_TYPE_CANON so wikitext casing ("alt",
# "ALT") still lands on one stored spelling.
#
# NG is a Next Gen wild card, and is real despite being rare and unexplained by
# any legend on the draw pages themselves — do not mistake it for scrape noise.
# Delray Beach 2026 is the proof: the draw stores 2 WC + 1 NG while the page's
# infobox declares "28 (4 Qualifiers / 3 Wild Cards)", so NG counts toward the
# wildcard total while being labelled separately in the bracket. All three
# holders so far were teenagers ranked outside the top 140.
ENTRY_TYPES = {"Q", "WC", "LL", "PR", "SE", "Alt", "NG"}
_ENTRY_TYPE_CANON = {t.upper(): t for t in ENTRY_TYPES}


def _canon_entry_type(value: str) -> Optional[str]:
    """Canonical entry type for a raw token, or None if it isn't one."""
    return _ENTRY_TYPE_CANON.get(value.strip().upper())


class WikiPageNotFound(ValueError):
    """
    The requested Wikipedia page does not exist.

    Distinct from every other scrape failure because for an upcoming draw it is
    usually not a failure at all: editors create the singles draw page around
    the time the draw is published, so every draw spends its whole pre-release
    polling window returning this. Callers use the type to decide whether that
    is expected (page never resolved yet — the routine case) or genuinely
    broken (a page_id that used to resolve and now 404s).

    Subclasses ValueError so pre-existing `except ValueError` handlers — notably
    scrape_tournament's title-variant fallback — keep working unchanged.
    """

# Points (per round_number 1-7) for ATP/WTA mirror mode — keyed by draw_size
# Grand Slam values; scaled proportionally for smaller draws
ATP_WTA_POINTS: dict[int, dict[int, int]] = {
    128: {1: 10, 2: 45, 3: 90, 4: 180, 5: 360, 6: 720, 7: 2000},
    64:  {1: 10, 2: 45, 3: 90, 4: 180, 5: 360, 6: 720},
    32:  {1: 10, 2: 45, 3: 90, 4: 180, 5: 360},
}


@dataclass
class PlayerEntry:
    bracket_position: int   # 1-indexed in the full draw
    name: str
    nationality: Optional[str]
    seed: Optional[int]
    entry_type: Optional[str]   # WC / Q / LL / PR / None


@dataclass
class MatchResult:
    round_number: int        # 1 = first round of the main draw
    match_number: int        # 1-indexed within the round
    player1_position: int    # bracket_position of player1
    player2_position: Optional[int]  # None = bye
    winner_position: Optional[int]   # None = not yet played
    is_bye: bool = False
    # [[p1_s1, p1_s2, ...], [p2_s1, p2_s2, ...]] e.g. [["6","4","7(4)"],["3","6","6(7)"]]
    scores: Optional[list] = None


@dataclass
class ParsedDraw:
    draw_size: int
    num_rounds: int
    players: list[PlayerEntry] = field(default_factory=list)
    matches: list[MatchResult] = field(default_factory=list)
    ranking_ref_date: Optional[date] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    has_final_winner: bool = False
    has_direct_draw: bool = False
    has_qualifiers: bool = False
    city: Optional[str] = None
    country: Optional[str] = None
    wiki_page_id: Optional[int] = None
    resolved_title: Optional[str] = None  # set when title fallback succeeded


# ---------------------------------------------------------------------------
# Wikipedia API
# ---------------------------------------------------------------------------

_MONTHS = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}

_INFOBOX_LOCATION_RE = re.compile(r"\|\s*location\s*=\s*([^\n|}{]+)", re.IGNORECASE)
_WIKI_LINK_TEXT_RE = re.compile(r"\[\[(?:[^\]|]+\|)?([^\]|]+)\]\]")


def _parse_infobox_location(wikitext: str) -> tuple[Optional[str], Optional[str]]:
    """Extract (city, country) from a tournament page's infobox location field."""
    m = _INFOBOX_LOCATION_RE.search(wikitext)
    if not m:
        return None, None
    raw = m.group(1).strip()
    # Extract all display texts from wiki links, also plain text parts
    parts = []
    last = 0
    for lm in _WIKI_LINK_TEXT_RE.finditer(raw):
        plain = raw[last:lm.start()].strip(" ,[]")
        if plain:
            parts.append(plain)
        parts.append(lm.group(1).strip())
        last = lm.end()
    plain = raw[last:].strip(" ,[]")
    if plain:
        parts.append(plain)
    if not parts:
        return None, None
    # Last part = country, second-to-last (skipping state-like parts) = city
    # Filter out empty and very short parts
    parts = [p for p in parts if len(p) > 1]
    if len(parts) == 1:
        return parts[0], None
    country = parts[-1]
    # If second-to-last looks like a state/province (contains comma or abbreviation), use third-to-last
    city = parts[-2] if len(parts) >= 2 else None
    # If the city still contains a comma (e.g. "Miami Gardens, Florida"), take just the part before comma
    if city and ',' in city:
        city = city.split(',')[0].strip()
    return city, country


from datetime import timedelta as _timedelta


def snap_to_monday(d: date) -> date:
    """Round d to the nearest Monday (tennis tournaments always start on Monday)."""
    offset = d.isoweekday() - 1  # Mon=0 … Sun=6
    if offset <= 3:
        return d - _timedelta(days=offset)   # round back
    return d + _timedelta(days=7 - offset)   # round forward


# Captures all content of the date field until the next infobox field or closing }}
_INFOBOX_DATE_RE = re.compile(
    r"\|\s*date\s*=\s*(.*?)(?=\n\s*\|[a-z _]|\n\s*\}\}|\Z)",
    re.IGNORECASE | re.DOTALL,
)
# "29 December 2026 – 11 January 2027" (both dates have explicit years)
_DATE_BOTH_YEARS_RE = re.compile(
    r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)
# "24 May – 7 June 2026" or "24 May – 7 June" (year at end or absent)
_DATE_DIFF_MONTH_RE = re.compile(
    r"(\d{1,2})\s+([A-Za-z]+)\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?",
    re.IGNORECASE,
)
# "5–11 January 2026" or "5–11 January"
_DATE_SAME_MONTH_RE = re.compile(
    r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?",
    re.IGNORECASE,
)
# Month-FIRST, the US convention, which every pattern above misses because they
# all lead with the day. North American events are written this way, so the
# whole date-correction path silently returned nothing for them: 2026 Canadian
# Open reads "August 2–13, 2026" and kept a stale end date of 10 August while
# its men's final was still to be played on the 13th.
# "August 2–13, 2026" / "August 2–13"
_DATE_US_SAME_MONTH_RE = re.compile(
    r"([A-Za-z]+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})(?:,?\s*(\d{4}))?",
    re.IGNORECASE,
)
# "August 24 – September 7, 2026"
_DATE_US_DIFF_MONTH_RE = re.compile(
    r"([A-Za-z]+)\s+(\d{1,2})\s*[-–]\s*([A-Za-z]+)\s+(\d{1,2})(?:,?\s*(\d{4}))?",
    re.IGNORECASE,
)


def _try_parse_date_range(raw: str, year: int) -> tuple[Optional[date], Optional[date]]:
    """Try all three date-range formats on a cleaned string."""
    m0 = _DATE_BOTH_YEARS_RE.match(raw)
    if m0:
        d1, mon1_s, yr1, d2, mon2_s, yr2 = m0.groups()
        mon1, mon2 = _MONTHS.get(mon1_s.lower()), _MONTHS.get(mon2_s.lower())
        if mon1 and mon2:
            try:
                return date(int(yr1), mon1, int(d1)), date(int(yr2), mon2, int(d2))
            except ValueError:
                pass

    m2 = _DATE_DIFF_MONTH_RE.match(raw)
    if m2:
        d1, mon1_s, d2, mon2_s, yr_s = m2.groups()
        yr = int(yr_s) if yr_s else year
        mon1, mon2 = _MONTHS.get(mon1_s.lower()), _MONTHS.get(mon2_s.lower())
        if mon1 and mon2:
            try:
                # yr is treated as the end-date year (Wikipedia places the explicit year
                # after the last date, e.g. "29 December – 5 January 2026" → end=Jan 2026).
                # When months cross a year boundary (Dec→Jan), start is in yr-1.
                cross_year = mon2 < mon1
                start = date(yr - 1 if cross_year else yr, mon1, int(d1))
                return start, date(yr, mon2, int(d2))
            except ValueError:
                pass

    # Month-first is tried BEFORE the day-first same-month pattern: "August
    # 2–13, 2026" would otherwise fall through to it and match nothing, which is
    # how this format went unnoticed.
    m4 = _DATE_US_DIFF_MONTH_RE.match(raw)
    if m4:
        mon1_s, d1, mon2_s, d2, yr_s = m4.groups()
        mon1, mon2 = _MONTHS.get(mon1_s.lower()), _MONTHS.get(mon2_s.lower())
        if mon1 and mon2:
            yr = int(yr_s) if yr_s else year
            try:
                cross_year = mon2 < mon1
                return date(yr - 1 if cross_year else yr, mon1, int(d1)), date(yr, mon2, int(d2))
            except ValueError:
                pass

    m5 = _DATE_US_SAME_MONTH_RE.match(raw)
    if m5:
        mon_s, d1, d2, yr_s = m5.groups()
        mon = _MONTHS.get(mon_s.lower())
        if mon:
            yr = int(yr_s) if yr_s else year
            try:
                return date(yr, mon, int(d1)), date(yr, mon, int(d2))
            except ValueError:
                pass

    m3 = _DATE_SAME_MONTH_RE.match(raw)
    if m3:
        d1, d2, mon_s, yr_s = m3.groups()
        yr = int(yr_s) if yr_s else year
        mon = _MONTHS.get(mon_s.lower())
        if mon:
            try:
                return date(yr, mon, int(d1)), date(yr, mon, int(d2))
            except ValueError:
                pass

    return None, None


def _parse_infobox_date(wikitext: str, year: int, gender: str = "") -> tuple[Optional[date], Optional[date]]:
    """
    Parse start/end dates from the infobox | date = field.

    When the field contains gender-qualified lines (e.g. '17–23 May (men)' /
    '20–26 July (women)'), the matching gender line is preferred.
    Falls back to the first parseable line when no gender match is found.
    """
    m = _INFOBOX_DATE_RE.search(wikitext)
    if not m:
        return None, None
    raw_block = m.group(1)

    # Strip template wrappers and wiki links
    raw_block = re.sub(r"\{\{(?:nowrap|plainlist|ubl)\s*\|", "", raw_block, flags=re.IGNORECASE)
    raw_block = re.sub(r"\{\{[^}]+\}\}", "", raw_block)
    raw_block = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]|\[\[([^\]]+)\]\]",
                       lambda x: x.group(1) or x.group(2), raw_block)
    raw_block = re.sub(r"\*\s*", "", raw_block)  # list bullet markers

    # Split into segments (by <br>, newline)
    segments = [s.strip() for s in re.split(r"<br\s*/?>|\n", raw_block) if s.strip()]

    gender_tag = "(men)" if gender == "M" else "(women)" if gender == "F" else ""

    def clean(seg: str) -> str:
        return re.sub(r"\s*\([^)]+\).*$", "", seg).strip()

    # 1. Try gender-matched segment
    if gender_tag:
        for seg in segments:
            if gender_tag.lower() in seg.lower():
                result = _try_parse_date_range(clean(seg), year)
                if result[0]:
                    return result

    # 2. Fall back to first parseable segment
    for seg in segments:
        result = _try_parse_date_range(clean(seg), year)
        if result[0]:
            return result

    return None, None


_RANKING_DATE_RE = re.compile(
    r"(?:seedings?|rankings?)\s+(?:are\s+)?based\s+on\s+\w+\s+rankings?\s+as\s+of\s+"
    r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)


def extract_ranking_ref_date(wikitext: str) -> Optional[date]:
    """Extract the ranking reference date from the seeds section prose."""
    m = _RANKING_DATE_RE.search(wikitext)
    if not m:
        return None
    try:
        day, month_str, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = _MONTHS.get(month_str)
        if month:
            return date(year, month, day)
    except (ValueError, KeyError):
        pass
    return None


_WIKI_CACHE_DIR = "/tmp/wiki_cache"
_WIKI_CACHE_TTL = 25 * 60  # 25 min — expires before the 30-min scheduler job refires


def _cache_path(page_id: Optional[int], page_title: str) -> str:
    if page_id is not None:
        return f"{_WIKI_CACHE_DIR}/{page_id}.txt"
    import hashlib
    key = hashlib.md5(page_title.encode()).hexdigest()
    return f"{_WIKI_CACHE_DIR}/{key}.txt"


async def fetch_wikitext(
    page_title: str,
    page_id: Optional[int] = None,
    force_refresh: bool = False,
) -> tuple[str, int]:
    """Fetch wikitext for a Wikipedia page. Returns (wikitext, pageid).

    Uses pageids= when page_id is known (immune to title renames), falls back
    to titles= on first fetch and stores the resolved pageid in the cache filename.
    """
    import os, time
    os.makedirs(_WIKI_CACHE_DIR, exist_ok=True)
    path = _cache_path(page_id, page_title)

    if not force_refresh and os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < _WIKI_CACHE_TTL:
            with open(path, "r", encoding="utf-8") as f:
                # page_id is known (encoded in the filename) when we have one
                resolved_id = page_id if page_id is not None else 0
                return f.read(), resolved_id

    params: dict = {
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "format": "json",
        "formatversion": "2",
    }
    if page_id is not None:
        params["action"] = "query"
        params["pageids"] = page_id
    else:
        params["action"] = "query"
        params["titles"] = page_title
        params["redirects"] = 1  # follow redirects so "– Men's singles" → "– Singles" works

    import asyncio as _asyncio
    headers = {"User-Agent": "TennisFantasyLeague/1.0 (https://upsetalert.ca; pdwiens@gmail.com)"}
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        resp = await client.get(WIKI_API, params=params)
        if resp.status_code == 429:
            import logging as _logging
            _log = _logging.getLogger(__name__)
            # Honour Retry-After header if present, otherwise wait 10s then retry once
            retry_after = int(resp.headers.get("Retry-After", 10))
            retry_after = min(retry_after, 60)  # cap at 60s
            _log.warning(
                "Wikipedia 429 for page %s/%s — waiting %ds then retrying",
                page_title, page_id, retry_after,
            )
            await _asyncio.sleep(retry_after)
            resp = await client.get(WIKI_API, params=params)
            if resp.status_code == 429:
                # Still rate-limited after retry — serve stale cache or fail
                if os.path.exists(path):
                    _log.warning(
                        "Wikipedia still 429 after retry for %s/%s — using stale cache",
                        page_title, page_id,
                    )
                    with open(path, "r", encoding="utf-8") as f:
                        resolved_id = page_id if page_id is not None else 0
                        return f.read(), resolved_id
                resp.raise_for_status()  # no cache to fall back to — propagate
        resp.raise_for_status()
    data = resp.json()
    pages = data["query"]["pages"]
    if not pages or "revisions" not in pages[0]:
        raise WikiPageNotFound(f"Page not found: {page_title!r} (id={page_id})")
    page_data = pages[0]
    resolved_id: int = page_data["pageid"]
    content = page_data["revisions"][0]["slots"]["main"]["content"]

    # Write to the stable pageid-keyed cache file
    stable_path = f"{_WIKI_CACHE_DIR}/{resolved_id}.txt"
    with open(stable_path, "w", encoding="utf-8") as f:
        f.write(content)

    return content, resolved_id


# ---------------------------------------------------------------------------
# Wikitext template extraction
# ---------------------------------------------------------------------------

def _extract_templates(wikitext: str, name_prefix: str) -> list[tuple[str, str]]:
    """
    Return (template_name, template_body) for every template whose name
    starts with name_prefix (case-insensitive).
    """
    results: list[tuple[str, str]] = []
    pattern = re.compile(r'\{\{(' + re.escape(name_prefix) + r'[^|}\n]*)', re.IGNORECASE)

    for m in pattern.finditer(wikitext):
        tpl_name = m.group(1).strip()
        start = m.start()
        depth = 0
        i = start
        while i < len(wikitext) - 1:
            if wikitext[i:i+2] == "{{":
                depth += 1
                i += 2
            elif wikitext[i:i+2] == "}}":
                depth -= 1
                i += 2
                if depth == 0:
                    break
            else:
                i += 1
        results.append((tpl_name, wikitext[start:i]))
    return results


def _parse_params(template_body: str) -> dict[str, str]:
    """Parse key=value pairs from a template body, one per line."""
    params: dict[str, str] = {}
    for line in template_body.split("\n"):
        line = line.strip().lstrip("|").strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        # Only keep RD-prefixed params and the round label params
        if key.startswith("RD"):
            params[key] = value.strip()
    return params


# ---------------------------------------------------------------------------
# Player name / seed parsing
# ---------------------------------------------------------------------------

_FLAG_RE = re.compile(r'\{\{flagicon[^}]*\}\}', re.IGNORECASE)
_TB_RE = re.compile(r'(\d+)<sup>(\d+)</sup>', re.IGNORECASE)
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_WIKI_LINK_RE = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')
_BOLD_RE = re.compile(r"'''(.*?)'''", re.DOTALL)
_NATIONALITY_RE = re.compile(r'\{\{flagicon\|([A-Z]{2,3})\}\}', re.IGNORECASE)


def _parse_team(raw: str) -> tuple[str, Optional[str], bool]:
    """
    Returns (player_name, nationality_code, is_winner).
    player_name is the full Wikipedia article name when available.
    """
    is_winner = "'''" in raw

    nat_match = _NATIONALITY_RE.search(raw)
    nationality = nat_match.group(1).upper() if nat_match else None

    link_match = _WIKI_LINK_RE.search(raw)
    if link_match:
        name = link_match.group(1).strip()
    else:
        # Fallback: strip templates and markup
        name = _FLAG_RE.sub("", raw)
        name = _BOLD_RE.sub(r"\1", name)
        name = re.sub(r"\[|\]", "", name)
        name = name.strip(" |'\n")

    # Strip Wikipedia disambiguation suffixes: "(tennis)", "(Canadian tennis player)", etc.
    name = re.sub(r"\s*\([^)]+\)\s*$", "", name).strip()

    return name, nationality, is_winner


def _parse_score_value(raw: str) -> Optional[str]:
    """Clean a score string: strip bold, convert tiebreak to (n) notation."""
    v = raw.strip().replace("'''", "").replace("''", "")
    v = _TB_RE.sub(lambda m: f"{m.group(1)}({m.group(2)})", v)
    v = _HTML_TAG_RE.sub("", v).strip()
    return v if v else None


def _extract_scores(params: dict, rd: int, slot_a: int, slot_b: int) -> Optional[list]:
    """Return [[p1_scores...], [p2_scores...]] or None if no scores present."""
    scores_a, scores_b = [], []
    for set_num in range(1, 6):
        # Try zero-padded keys first (16TeamBracket), then unpadded (8TeamBracket)
        raw_a = (params.get(f"RD{rd}-score{slot_a:02d}-{set_num}")
                 or params.get(f"RD{rd}-score{slot_a}-{set_num}", ""))
        raw_b = (params.get(f"RD{rd}-score{slot_b:02d}-{set_num}")
                 or params.get(f"RD{rd}-score{slot_b}-{set_num}", ""))
        sa = _parse_score_value(raw_a)
        sb = _parse_score_value(raw_b)
        if sa is None and sb is None:
            break
        scores_a.append(sa or "")
        scores_b.append(sb or "")
    return [scores_a, scores_b] if (scores_a or scores_b) else None


_INNER_TEMPLATE_RE = re.compile(r'\{\{[^{}]*\}\}')
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_WRAPPER_TEMPLATE_NAMES = frozenset({
    'nowrap', 'small', 'plaintext', 'nobr', 'bigger', 'smaller', 'nowrap2',
})


def _strip_seed_templates(v: str) -> str:
    """
    Reduce a seed cell to its bare value: {{nowrap|X}} → X, {{small|X}} → X,
    <small>X</small> → X, and HTML entities to their characters.

    Wikitext expresses the same emphasis two ways, and only the template form
    was handled — so "<small>1/WC</small>" survived intact and then failed every
    downstream test, losing BOTH the seed and the wildcard for players like
    Auger-Aliassime (seed 1 + WC at the Open Occitanie). Entities matter for the
    same reason: a cell holding only "&nbsp;" is an empty cell, and must reduce
    to "" rather than to a non-empty string that parses as nothing.
    """
    prev = None
    while prev != v:
        prev = v
        m = _INNER_TEMPLATE_RE.search(v)
        if not m:
            break
        inner = m.group(0)[2:-2]
        if '|' in inner:
            name, content = inner.split('|', 1)
            if name.strip().lower() in _WRAPPER_TEMPLATE_NAMES:
                v = v[:m.start()] + content + v[m.end():]
                continue
        v = v[:m.start()] + v[m.end():]
    v = _HTML_TAG_RE.sub('', v)
    # &nbsp; unescapes to U+00A0, which str.strip() does not remove on its own.
    return html.unescape(v).replace('\xa0', ' ').strip()


def _parse_seed(raw: str) -> tuple[Optional[int], Optional[str]]:
    """Returns (seed_int, entry_type). Handles compound values like '20/WC'
    (a seeded wildcard) and reserve-slot compounds like 'Q/LL' (last spot
    unresolved between a qualifier and a lucky loser — no seed number at
    all). 'Q' wins when present since that's the placeholder label the
    frontend renders ("Qualifier N"); other combinations fall back to
    whichever part is a known entry type.
    """
    v = _strip_seed_templates(raw.strip())
    if not v:
        return None, None
    if '/' in v:
        parts = [p.strip() for p in v.split('/')]
        try:
            seed = int(parts[0])
            return seed, _canon_entry_type(parts[1]) if len(parts) > 1 else None
        except ValueError:
            # Compound of non-numeric entry types (e.g. "Q/LL") — no seed.
            if 'Q' in parts:
                return None, 'Q'
            return None, next(
                (c for c in (_canon_entry_type(p) for p in parts) if c), None
            )
    canon = _canon_entry_type(v)
    if canon:
        return None, canon
    try:
        return int(v), None
    except ValueError:
        return None, None


# ---------------------------------------------------------------------------
# Section parsing helpers
# ---------------------------------------------------------------------------

def _parse_16team_section(
    params: dict[str, str],
    section_index: int,   # 0-based, determines global bracket positions
    global_round_offset: int,  # round number of this section's RD1 in the full draw
    players_out: list[PlayerEntry],
    matches_out: list[MatchResult],
    draw_size: int,
    include_section_final: bool = True,
    byes_allowed: bool = True,
) -> Optional[list[Optional[int]]]:
    """
    Parse one {{16TeamBracket-Compact-Tennis5/3}} (or ...-Byes) section.

    bracket positions for this section: section_index*16 + 1 .. section_index*16 + 16

    include_section_final controls whether this section's own local "RD4" is
    treated as a real match. Some Wikipedia draws (e.g. the "-Byes" template
    variant used for 56/64-draw Masters events) pair each 16-team section's
    own RD4 with an *external*, separate {{8TeamBracket}} "Finals" section that
    already contains the authoritative Quarterfinal/Semifinal/Final results —
    the section's own RD4 field there is just an editorial re-display of the
    same real-world QF match, not a second one. Parsing it as a real match
    creates a duplicate (round_number, match_number) key that collides with
    the one the external finals bracket produces for the same round, and one
    silently clobbers the other on upsert.
    When include_section_final is False, RD4 is skipped entirely (no match
    emitted) and this section's two Round-3 survivors are returned instead,
    so the caller can feed them into the external finals bracket's own QF
    pairing (which expects genuine pairs of Round-3 survivors, not a single
    already-reduced section champion).
    """
    base_pos = section_index * 16  # 0-based offset

    # --- Extract RD1 players (16 slots) ---
    player_by_local: dict[int, PlayerEntry] = {}
    for local in range(1, 17):
        key_seed = f"RD1-seed{local:02d}"
        key_team = f"RD1-team{local:02d}"
        raw_team = params.get(key_team, "").strip()
        if not raw_team:
            continue
        name, nat, _ = _parse_team(raw_team)
        seed, entry_type = _parse_seed(params.get(key_seed, ""))
        bracket_pos = base_pos + local
        entry = PlayerEntry(
            bracket_position=bracket_pos,
            name=name,
            nationality=nat,
            seed=seed,
            entry_type=entry_type,
        )
        players_out.append(entry)
        player_by_local[local] = entry

    # --- Detect bye players: Wikipedia places them directly in RD2 when both ---
    # their RD1 slots are empty (seed skips round 1). Assign them the first     ---
    # (odd) bracket position of the pair so they appear in R1 with a bye.       ---
    bye_positions: dict[int, int] = {}  # rd1_slot_a (1-indexed) -> bracket_pos
    for rd2_slot in range(1, 9):
        rd1_a = (rd2_slot - 1) * 2 + 1
        rd1_b = rd1_a + 1
        if (params.get(f"RD1-team{rd1_a:02d}", "").strip()
                or params.get(f"RD1-team{rd1_b:02d}", "").strip()):
            continue  # Normal R1 match, not a bye
        raw_rd2 = params.get(f"RD2-team{rd2_slot:02d}", "").strip()
        if not raw_rd2:
            continue  # Draw not yet released for this slot
        name, nat, _ = _parse_team(raw_rd2)
        seed, entry_type = _parse_seed(params.get(f"RD2-seed{rd2_slot:02d}", ""))
        bracket_pos = base_pos + rd1_a
        entry = PlayerEntry(
            bracket_position=bracket_pos,
            name=name,
            nationality=nat,
            seed=seed,
            entry_type=entry_type,
        )
        players_out.append(entry)
        player_by_local[rd1_a] = entry
        bye_positions[rd1_a] = bracket_pos

    # --- Build winner map: local_pos -> bracket_pos for each round ---
    # We track which bracket_position occupies each RD slot by following bold markup.
    # rd_occupant[round][local_slot] = bracket_position
    rd_occupant: dict[int, dict[int, Optional[int]]] = {1: {}, 2: {}, 3: {}, 4: {}, 5: {}}

    for local in range(1, 17):
        pos = base_pos + local
        rd_occupant[1][local] = pos

    # CAN THIS DRAW PRODUCE A BYE AT ALL? Only a field smaller than its
    # bracket needs padding, so 32/64/128 have none. Computed once: it gates
    # both halves of the same inference — the bye flag AND the advancement,
    # which is the half missed on the first pass and put nine men and
    # fourteen women into round two of the 2026 US Open without playing.
    # The page's own template decides; bye_positions is the same fact seen
    # from inside a section (a seed sitting in RD2 with both RD1 slots empty).
    byes_possible = byes_allowed and bool(bye_positions)

    # Process RD1..RD4 (or RD1..RD3 when the section's own final round is
    # actually handled by an external finals bracket — see docstring).
    max_local_round = 4 if include_section_final else 3
    for rd in range(1, max_local_round + 1):
        slots_this_rd = 16 // (2 ** (rd - 1))   # 16, 8, 4
        slots_next_rd = slots_this_rd // 2
        for match_idx in range(slots_next_rd):
            slot_a = match_idx * 2 + 1
            slot_b = match_idx * 2 + 2
            key_a = f"RD{rd}-team{slot_a:02d}"
            key_b = f"RD{rd}-team{slot_b:02d}"
            raw_a = params.get(key_a, "")
            raw_b = params.get(key_b, "")
            _, _, a_wins = _parse_team(raw_a)
            _, _, b_wins = _parse_team(raw_b)

            pos_a = rd_occupant[rd].get(slot_a)
            pos_b = rd_occupant[rd].get(slot_b)

            # Determine winner
            winner_pos: Optional[int] = None
            if a_wins and not b_wins:
                winner_pos = pos_a
            elif b_wins and not a_wins:
                winner_pos = pos_b
            elif raw_a and not raw_b and byes_possible:
                # Only one player present → bye or walkover. In a full draw
                # this is an unfilled slot instead, and nobody advances.
                winner_pos = pos_a
            elif raw_b and not raw_a and byes_possible:
                winner_pos = pos_b
            elif rd == 1 and not raw_a and not raw_b and slot_a in bye_positions:
                # Seed placed directly in RD2 — first-round bye
                winner_pos = bye_positions[slot_a]

            rd_occupant[rd + 1][match_idx + 1] = winner_pos

            # Determine bye.
            #
            # AN EMPTY SLOT IS NOT A BYE IN A DRAW THAT HAS NO BYES. Byes exist
            # only when the field is smaller than the bracket — 2**rounds minus
            # draw_size of them — so a 128 draw (2**7) has exactly zero, and a
            # blank RD1-team there means "not filled in yet": a qualifier the
            # tournament has not produced, or an editor mid-edit. The US Open
            # 2026 draws published with 24 blank slots while qualifying was
            # still being played, and reading those as byes invented 27 free
            # walkovers across the two draws, advanced players who had not
            # played, and — because the pick filler deliberately skips byes —
            # left every one of those slots without a default pick.
            is_bye = byes_possible and (
                (bool(raw_a) != bool(raw_b) and not (a_wins or b_wins))
                or (rd == 1 and not raw_a and not raw_b and slot_a in bye_positions)
            )

            # Match number in the full draw for this round
            matches_in_section_per_round = [8, 4, 2, 1]
            global_match_base = section_index * matches_in_section_per_round[rd - 1]
            global_match_number = global_match_base + match_idx + 1
            global_round = global_round_offset + rd - 1

            scores = _extract_scores(params, rd, slot_a, slot_b)
            matches_out.append(MatchResult(
                round_number=global_round,
                match_number=global_match_number,
                player1_position=pos_a if pos_a is not None else 0,
                player2_position=pos_b,
                winner_position=winner_pos,
                is_bye=is_bye,
                scores=scores,
            ))

    # The section's RD4 winner feeds the finals bracket (handled by parse_8team_section).
    if not include_section_final:
        # Round-3 survivors, in bracket-position order — the two players who
        # would have met in this section's own (skipped) RD4.
        return [rd_occupant[4].get(1), rd_occupant[4].get(2)]
    return None


def _parse_8team_finals(
    params: dict[str, str],
    section_winners: list[Optional[int]],  # 8 bracket positions from the section winners
    qf_round: int,                          # global round number for QF
    matches_out: list[MatchResult],
) -> None:
    """
    Parse the {{8TeamBracket-Tennis5/3}} finals template.
    RD1 = QF (4 matches), RD2 = SF (2 matches), RD3 = F (1 match).
    """
    # Map RD1 slots (1-8) to section-winner bracket positions
    # The 8 QF participants come from the 8 section winners in order
    rd_occupant: dict[int, dict[int, Optional[int]]] = {1: {}, 2: {}, 3: {}}
    for i, pos in enumerate(section_winners, start=1):
        rd_occupant[1][i] = pos

    round_slots = {1: 8, 2: 4, 3: 2}
    for rd in range(1, 3):
        num_matches = round_slots[rd] // 2
        for match_idx in range(num_matches):
            slot_a = match_idx * 2 + 1
            slot_b = match_idx * 2 + 2

            # Try both zero-padded and non-padded key formats
            raw_a = params.get(f"RD{rd}-team{slot_a:02d}") or params.get(f"RD{rd}-team{slot_a}", "")
            raw_b = params.get(f"RD{rd}-team{slot_b:02d}") or params.get(f"RD{rd}-team{slot_b}", "")
            _, _, a_wins = _parse_team(raw_a)
            _, _, b_wins = _parse_team(raw_b)

            pos_a = rd_occupant[rd].get(slot_a)
            pos_b = rd_occupant[rd].get(slot_b)

            winner_pos: Optional[int] = None
            if a_wins and not b_wins:
                winner_pos = pos_a
            elif b_wins and not a_wins:
                winner_pos = pos_b

            rd_occupant[rd + 1][match_idx + 1] = winner_pos

            global_round = qf_round + rd - 1
            global_match = match_idx + 1
            scores = _extract_scores(params, rd, slot_a, slot_b)
            matches_out.append(MatchResult(
                round_number=global_round,
                match_number=global_match,
                player1_position=pos_a if pos_a is not None else 0,
                player2_position=pos_b,
                winner_position=winner_pos,
                scores=scores,
            ))

    # Final (RD3)
    raw_a = params.get("RD3-team01") or params.get("RD3-team1", "")
    raw_b = params.get("RD3-team02") or params.get("RD3-team2", "")
    _, _, a_wins = _parse_team(raw_a)
    _, _, b_wins = _parse_team(raw_b)
    pos_a = rd_occupant[3].get(1)
    pos_b = rd_occupant[3].get(2)
    winner_pos = None
    if a_wins and not b_wins:
        winner_pos = pos_a
    elif b_wins and not a_wins:
        winner_pos = pos_b
    scores = _extract_scores(params, 3, 1, 2)
    matches_out.append(MatchResult(
        round_number=qf_round + 2,
        match_number=1,
        player1_position=pos_a if pos_a is not None else 0,
        player2_position=pos_b,
        winner_position=winner_pos,
        scores=scores,
    ))


def _parse_4team_final_only(
    params: dict[str, str],
    sf_winners: list[Optional[int]],  # 2 bracket positions: [top-half SF winner, bottom-half SF winner]
    final_round: int,
    matches_out: list[MatchResult],
) -> None:
    """
    Extract only the Final match from a {{4TeamBracket-Tennis*}} template.

    Wikipedia uses this template for 32-draw Finals sections (SF + Final).
    The SF matches are already produced by the two 16TeamBracket sections, so
    we only need the Final here to avoid duplicating round 4 matches.
    """
    raw_a = params.get("RD2-team01") or params.get("RD2-team1", "")
    raw_b = params.get("RD2-team02") or params.get("RD2-team2", "")
    _, _, a_wins = _parse_team(raw_a)
    _, _, b_wins = _parse_team(raw_b)

    pos_a = sf_winners[0] if len(sf_winners) > 0 else None
    pos_b = sf_winners[1] if len(sf_winners) > 1 else None

    winner_pos: Optional[int] = None
    if a_wins and not b_wins:
        winner_pos = pos_a
    elif b_wins and not a_wins:
        winner_pos = pos_b

    scores = _extract_scores(params, 2, 1, 2)
    matches_out.append(MatchResult(
        round_number=final_round,
        match_number=1,
        player1_position=pos_a if pos_a is not None else 0,
        player2_position=pos_b,
        winner_position=winner_pos,
        scores=scores,
    ))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_draw(wikitext: str) -> ParsedDraw:
    """
    Parse a Wikipedia tennis draw page into a structured ParsedDraw.
    Handles 128, 64, and 32-player main draws.
    """
    players: list[PlayerEntry] = []
    matches: list[MatchResult] = []

    # Find all 16TeamBracket sections
    sections_16 = _extract_templates(wikitext, "16TeamBracket-Compact-Tennis")
    # THE PAGE SAYS WHETHER THIS DRAW HAS BYES. Wikipedia renders a field
    # smaller than its bracket with the "-Byes" template variant, seeds placed
    # directly in RD2 — Winston-Salem is 48 players in a 64 bracket and uses
    # it; the US Open, 128 in 128, does not. Reading that instead of guessing
    # from the bracket SIZE is the difference between the two: a size rule
    # called every 64 bracket bye-less and wiped sixteen real byes off
    # Winston-Salem's first round, which then rendered as "TBD".
    byes_allowed = bool(re.search(r"16TeamBracket-Compact-Tennis[\w\-]*-Byes",
                                  wikitext, re.I))
    # Find the 8TeamBracket finals section
    sections_8 = _extract_templates(wikitext, "8TeamBracket-Tennis")

    num_sections = len(sections_16)

    if num_sections == 8:
        draw_size, num_rounds = 128, 7
    elif num_sections == 4:
        draw_size, num_rounds = 64, 6
    elif num_sections == 2:
        draw_size, num_rounds = 32, 5
    elif num_sections == 0 and sections_8:
        # Small draw handled entirely by 8TeamBracket (edge case)
        draw_size, num_rounds = 8, 3
    else:
        # Fall back: infer from section count
        draw_size = num_sections * 16
        num_rounds = num_sections.bit_length() + 2  # rough estimate

    # Parse each 16TeamBracket section.
    # For a 128-draw (8 sections), each section runs all 4 internal rounds and
    # produces ONE Round-of-16 survivor — 8 sections give the 8 real
    # quarterfinalists the external finals bracket needs.
    # For a 64-draw (4 sections) with a *separate* finals bracket, the section's
    # own "RD4" is just an editorial re-display of a match the finals bracket
    # already covers authoritatively (see _parse_16team_section docstring) — so
    # each section only runs 3 internal rounds and contributes its TWO Round-3
    # survivors (not one already-reduced champion), giving 4×2=8 quarterfinalists.
    SECTION_LAST_ROUND = 4
    section_final_is_external = num_sections == 4 and bool(sections_8)
    section_winners: list[Optional[int]] = []
    for idx, (_, body) in enumerate(sections_16):
        params = _parse_params(body)
        round3_survivors = _parse_16team_section(
            byes_allowed=byes_allowed,
            params=params,
            section_index=idx,
            global_round_offset=1,
            players_out=players,
            matches_out=matches,
            draw_size=draw_size,
            include_section_final=not section_final_is_external,
        )
        if section_final_is_external:
            section_winners.extend(round3_survivors or [None, None])
        else:
            section_final_matches = [
                m for m in matches
                if m.round_number == SECTION_LAST_ROUND
                and m.match_number == idx + 1
            ]
            winner_pos = section_final_matches[-1].winner_position if section_final_matches else None
            section_winners.append(winner_pos)

    # Parse the finals bracket
    if sections_8:
        # 64/128-draw: 8TeamBracket covers QF → SF → Final
        _, finals_body = sections_8[0]
        finals_params = _parse_params(finals_body)
        qf_round = num_rounds - 2  # QF is 3 rounds from the end (QF, SF, F)
        _parse_8team_finals(finals_params, section_winners, qf_round, matches)
    else:
        # 32-draw: 4TeamBracket-Tennis covers SF + Final, but SF already exists
        # in each 16TeamBracket section (round 4). Only create the Final match.
        sections_4 = _extract_templates(wikitext, "4TeamBracket-Tennis")
        if sections_4 and num_sections == 2:
            _, finals_body = sections_4[0]
            finals_params = _parse_params(finals_body)
            _parse_4team_final_only(finals_params, section_winners, num_rounds, matches)

    ranking_ref_date = extract_ranking_ref_date(wikitext)
    return ParsedDraw(
        draw_size=draw_size,
        num_rounds=num_rounds,
        players=players,
        matches=matches,
        ranking_ref_date=ranking_ref_date,
    )


_SINGLES_SUFFIX_RE = re.compile(
    r"\s*[–\-—]\s*(?:(?:Men['‘’]s|Women['‘’]s|Gentlemen['‘’]s|Ladies['‘’]?)\s+)?Singles?$",
    re.IGNORECASE,
)


def strip_singles_suffix(title: str) -> str:
    """
    Strip a trailing singles suffix ('– Singles', '– Men's singles',
    '– Women's singles') from a draw-page title, returning the base
    tournament page title. Returns the title unchanged if no suffix found.
    """
    return _SINGLES_SUFFIX_RE.sub("", title).strip()


def singles_title_variants(title: str, gender: str = "") -> list[str]:
    """
    All plausible Wikipedia titles for the singles draw page that *title*
    refers to. Wikipedia uses '– Singles' for single-tour events but
    '– Men's/Women's singles' for combined events (and for events sharing
    their article with a Challenger/125 edition), and which one an editor
    will pick is not reliably predictable. Returns the original title first.

    When *gender* ('M'/'F') is given, the opposite gender's variant is
    EXCLUDED: for a combined event the opposite variant is a different,
    real page (e.g. Hamburg's ATP and WTA draws), and probing or watching
    it cross-pollinates one tournament with the other's data.
    """
    base = strip_singles_suffix(title)
    if gender == "M":
        ordered = ["Men's singles", "Singles"]
    elif gender == "F":
        ordered = ["Women's singles", "Singles"]
    else:
        ordered = ["Singles", "Men's singles", "Women's singles"]
    variants = [title] + [
        v for s in ordered if (v := f"{base} – {s}") != title
    ]
    return variants


def _general_page_title(singles_title: str) -> Optional[str]:
    """
    Derive the general tournament page title by stripping the singles suffix.
    e.g. '2026 French Open – Men's singles' → '2026 French Open'
    Returns None if no suffix was found (title is already the general page).
    """
    stripped = strip_singles_suffix(singles_title)
    return stripped if stripped != singles_title else None


_BRACKET_MARKER = "TeamBracket"

import logging as _logging
_scraper_logger = _logging.getLogger(__name__)


async def fetch_event_dates(
    wiki_page_title: str, year: int, gender: str = ""
) -> tuple[Optional[date], Optional[date]]:
    """
    (start, end) from the general event page alone — no singles draw required.

    scrape_tournament reads the same infobox, but only after it has successfully
    fetched the SINGLES page, and that page does not exist until roughly the day
    the draw is published. So for the whole time a tournament is upcoming, the
    one authoritative statement of when it runs is sitting on a page we already
    know how to reach and never look at.

    That gap is not cosmetic. Discovery seeds start_date with the Monday of the
    tournament's week, which is right for an ordinary Mon–Sun event and wrong for
    every extended-format 1000 and Slam: 2026 Cincinnati runs 13–23 August and
    was seeded 10 August. A draw whose start_date has already passed reads as
    "active" the instant it is released (Draw.computed_status), which locks picks
    — so the release that should have opened a Masters 1000 for picking would
    have closed it instead, with nothing logged.

    Returns (None, None) rather than raising: this is a best-effort refinement of
    a date we already have, and a Wikipedia blip must never be worse than not
    having called it.
    """
    if not year:
        return None, None
    general_title = _general_page_title(wiki_page_title) or wiki_page_title
    try:
        wikitext, _ = await fetch_wikitext(general_title)
    except Exception as exc:
        _scraper_logger.debug("Event-date refresh: could not fetch %r: %s", general_title, exc)
        return None, None
    return _parse_infobox_date(wikitext, year, gender)


async def scrape_tournament(
    wiki_page_title: str,
    year: int = 0,
    gender: str = "",
    page_id: Optional[int] = None,
    force_refresh: bool = False,
) -> ParsedDraw:
    effective_title = wiki_page_title
    try:
        wikitext, resolved_id = await fetch_wikitext(wiki_page_title, page_id=page_id, force_refresh=force_refresh)
    except ValueError:
        # The stored title may use the wrong suffix variant (Wikipedia titles
        # single-tour draw pages '– Singles' but combined events '– Men's/
        # Women's singles'). Try every other plausible variant before giving up.
        wikitext = None
        for alt_title in singles_title_variants(wiki_page_title, gender)[1:]:
            try:
                wikitext, resolved_id = await fetch_wikitext(alt_title, force_refresh=force_refresh)
                effective_title = alt_title
                break
            except ValueError:
                continue
        if wikitext is None:
            raise

    # If a specific page_id was provided but the fetched page has no bracket templates,
    # the stored page_id may point to the wrong Wikipedia article (e.g. the general
    # tournament overview page instead of the singles draw page). Retry by title alone
    # so Wikipedia resolves the current canonical target.
    if page_id is not None and _BRACKET_MARKER not in wikitext:
        try:
            fresh_wikitext, fresh_id = await fetch_wikitext(wiki_page_title, force_refresh=True)
            if fresh_id is not None and fresh_id != resolved_id:
                _scraper_logger.warning(
                    "page_id %s has no bracket templates for %r; "
                    "title lookup resolved to page_id %s — using corrected page",
                    page_id, wiki_page_title, fresh_id,
                )
                wikitext, resolved_id = fresh_wikitext, fresh_id
        except Exception as exc:
            _scraper_logger.debug(
                "Title-based page_id correction retry failed for %r: %s", wiki_page_title, exc
            )

    # OFF THE EVENT LOOP. parse_draw is seconds of pure-CPU regex over a
    # large page, and it used to run inline — during a live-play edit storm
    # (the bracket page is edited every game) the scrapes queued and the loop
    # went dark for tens of seconds at a stretch: 2026-08-25's "everything
    # hangs, even the debug endpoint" windows, caught by the hang trap when
    # every other tool (py-spy, the txn watchdog, the raw writer probe) came
    # back clean — the loop they needed was the thing that was blocked.
    parsed = await asyncio.to_thread(parse_draw, wikitext)
    parsed.wiki_page_id = resolved_id or None
    if effective_title != wiki_page_title:
        parsed.resolved_title = effective_title

    # Extract location from infobox
    parsed.city, parsed.country = _parse_infobox_location(wikitext)

    # Extract dates from the general tournament page (which has the real date range).
    # Pass gender so gender-specific date lines (e.g. Hamburg "(men)"/"(women)") are chosen.
    # Fall back to the draw page's own infobox if the general page can't be fetched.
    if year:
        general_title = _general_page_title(wiki_page_title)
        if general_title:
            try:
                general_wt, _ = await fetch_wikitext(general_title)
                parsed.start_date, parsed.end_date = _parse_infobox_date(general_wt, year, gender)
            except Exception:
                pass
        if not parsed.start_date:
            parsed.start_date, parsed.end_date = _parse_infobox_date(wikitext, year, gender)

    # Detect if direct draw is present (main draw players exist)
    if parsed.players:
        parsed.has_direct_draw = True

    # Detect if qualifiers have been added (look for Qualifiers section)
    has_qualifiers_section = bool(re.search(r"===\s*Qualifiers\s*===", wikitext, re.IGNORECASE))
    if has_qualifiers_section and any(p.entry_type == "Q" and p.name and p.name.strip() for p in parsed.players):
        parsed.has_qualifiers = True

    # Check if the final match has a winner (tournament is complete)
    if parsed.matches:
        max_round = max((m.round_number for m in parsed.matches), default=0)
        finals = [m for m in parsed.matches if m.round_number == max_round]
        if finals and finals[0].winner_position is not None:
            parsed.has_final_winner = True

    return parsed
