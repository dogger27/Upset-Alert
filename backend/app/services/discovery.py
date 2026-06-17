"""
Tournament discovery from Wikipedia ATP/WTA season pages.

Handles both date formats (ATP: "25 May / 1 Jun", WTA: "Dec 29 / Jan 5"),
explicit singles-page links, and unlinked future tournament entries.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.services.scraper import fetch_wikitext

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

CATEGORY_RANK = {
    "Grand Slam": 0,
    "ATP 1000": 1, "WTA 1000": 1,
    "ATP 500":  2, "WTA 500":  2,
    "ATP 250":  3, "WTA 250":  3,
}

# Minimum singles draw to include (excludes round-robin Finals with 8 players)
MIN_DRAW_SIZE = 28

# Name fragments that indicate team/special events — skip these
EXCLUDE_NAME_FRAGMENTS = (
    "cup", "finals", "davis", "hopman", "united cup", "billie jean"
)


@dataclass
class DiscoveredTournament:
    name: str
    year: int
    gender: str
    surface: str
    category: str
    draw_size: int
    wiki_page_title: str
    start_date: Optional[date]
    end_date: Optional[date]
    city: Optional[str] = None
    country: Optional[str] = None

    @property
    def sort_key(self):
        return (
            self.start_date or date(self.year, 12, 31),
            CATEGORY_RANK.get(self.category, 9),
        )


# ---------------------------------------------------------------------------
# Date helpers — handle both "25 May" and "May 25" orderings
# ---------------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate(
    ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1
)}

_DAY_MONTH_RE = re.compile(
    r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b",
    re.IGNORECASE,
)
_MONTH_DAY_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\b",
    re.IGNORECASE,
)

# Date column cells: handles both ATP "|rowspan=3|" and WTA "| rowspan="3" |" styles
_ROWSPAN_RE = re.compile(r"\|\s*rowspan\s*=\s*[\"']?(\d+)[\"']?\s*\|")


def _all_dates_in(text: str) -> list[tuple[str, str]]:
    """Return [(day, month_abbr), ...] for every date found, preserving order."""
    hits: list[tuple[int, str, str]] = []
    for m in _DAY_MONTH_RE.finditer(text):
        hits.append((m.start(), m.group(1), m.group(2)))
    for m in _MONTH_DAY_RE.finditer(text):
        hits.append((m.start(), m.group(2), m.group(1)))  # normalise to (day, month)
    hits.sort()
    return [(d, mo) for _, d, mo in hits]


def _parse_date_pair(text: str, year: int) -> tuple[Optional[date], Optional[date]]:
    """Extract start and end dates from a short cell string."""
    pairs = _all_dates_in(text)
    sd = ed = None
    if pairs:
        d, m = pairs[0]
        mon = _MONTHS.get(m[:3].lower())
        try:
            sd = date(year, mon, int(d)) if mon else None
        except ValueError:
            pass
    if len(pairs) >= 2:
        d, m = pairs[1]
        mon = _MONTHS.get(m[:3].lower())
        try:
            ed = date(year, mon, int(d)) if mon else None
            if sd and ed and ed < sd:               # year wrap (Dec → Jan)
                ed = date(year + 1, mon, int(d))
        except ValueError:
            pass
    return sd, ed


def _build_date_index(wikitext: str, year: int) -> list[tuple[int, date, Optional[date]]]:
    """
    Walk all rowspan markers (both ATP and WTA format).
    Accepts cells with one OR two date patterns.
    Skips cells whose snippet starts with {{flagicon, [[ or style= (non-date cells).
    """
    entries: list[tuple[int, date, Optional[date]]] = []
    skip_re = re.compile(r"^\s*(\{\{flagicon|\[\[|style\s*=)", re.IGNORECASE)

    for rm in _ROWSPAN_RE.finditer(wikitext):
        snippet = wikitext[rm.end(): rm.end() + 80]
        if skip_re.match(snippet):
            continue  # result/tournament cell, not a date cell
        sd, ed = _parse_date_pair(snippet, year)
        if sd:  # only need start date
            entries.append((rm.start(), sd, ed))
    return sorted(entries)


def _lookup_date(date_index: list[tuple[int, date, date]], pos: int):
    """Return the (start, end) date whose rowspan marker is closest before pos."""
    best = (None, None)
    for dpos, sd, ed in date_index:
        if dpos <= pos:
            best = (sd, ed)
        else:
            break
    return best


# ---------------------------------------------------------------------------
# Misc pattern helpers
# ---------------------------------------------------------------------------

_SURFACE_INDOOR_RE = re.compile(r"\bHard\s*\(i\)", re.IGNORECASE)
_SURFACE_RE = re.compile(r"\b(Hard|Clay|Grass)\b", re.IGNORECASE)
_DRAW_RE = re.compile(r"(\d+)S[/\b]")
_CATEGORY_RE = re.compile(
    r"(Grand\s*Slam|ATP\s*1000|WTA\s*1000|ATP\s*500|WTA\s*500|"
    r"ATP\s*250|WTA\s*250|Masters\s*1000)",
    re.IGNORECASE,
)
# Main tournament wiki link: [[2026 French Open|French Open]]
_DISPLAY_LINK_RE = re.compile(r"\[\[(\d{4}[^\]|–]+?)\|([^\]–]{2,40}?)\]\]")

# Explicit singles link — matches gender-specific and gender-neutral forms.
# Built as a non-raw string so \u escapes resolve to actual Unicode characters,
# ensuring the pattern works regardless of which apostrophe the wikitext uses.
# After parse_season_schedule normalises the wikitext, both U+0027 and U+2019
# will have been replaced with plain ASCII ‘, so the pattern just needs to
# match the plain ASCII ‘.
_APOS = chr(39)  # plain ASCII apostrophe U+0027, avoids smart-quote substitution
_SINGLES_LINK_RE = re.compile(
    "\\[\\[((\\d{4}[^\\]|]*–\\s*"
    "(?:(?:Men" + _APOS + "s|Women" + _APOS + "s)\\s+)?"
    "[Ss]ingles))\\s*\\|\\s*[Ss]ingles\\s*\\]\\]",
    re.IGNORECASE,
)

# Unlinked "Singles" marker in a cell that has a year-prefixed main tournament link
_UNLINKED_SINGLES_RE = re.compile(
    r"(\[\[(\d{4}[^\]|–]+?)\|([^\]–]{2,40}?)\]\])"   # group 1=full link, 2=page, 3=display
    r"(?:(?!\[\[\d{4}[^\]]*singles).){0,900}?"         # lazy: match nearest Singles, not farthest
    r"\bSingles\b",
    re.DOTALL | re.IGNORECASE,
)

# No-year, no-pipe format: [[Swedish Open]] at start of cell
# Requires | before link — prevents matching inline city links like [[Eastbourne]], [[Santa Ponsa]]
# Stops at \n|- (wikitext table row separator) so one row can't consume the next row's Singles
_SIMPLE_TOURNAMENT_RE = re.compile(
    r"\|\s*\[\[([A-Z][^\]|–]+?)\]\]"    # [[Tournament]] at start of table cell (no year, no pipe)
    r"(?:(?!\n\|-)[\s\S]){0,2000}?"
    r"\bSingles\b",
    re.IGNORECASE,
)

# No-year, piped format: [[Swiss Open (tennis)|Swiss Open]] at start of cell
# Handles tournaments whose Wikipedia page title includes disambiguation or alternate name
# Stops at \n|- so one row can't consume the next row's Singles
_NOYR_PIPED_RE = re.compile(
    r"\|\s*\[\[([A-Z][^\]|]+)\|([^\]|]{2,40}?)\]\]"   # [[Page|Display]] at cell start, no year
    r"(?:(?!\n\|-)[\s\S]){0,2000}?"
    r"\bSingles\b",
    re.IGNORECASE,
)


# ATP/WTA schedule tables embed location as:
#   [[TournamentName|Display]]<br/> [[City]], Country<br/>
# or  [[City, State|City]], Country
_LOCATION_RE = re.compile(
    r"<br\s*/?>\s*"                                     # <br/> after tournament display name
    r"\[\[([^\]|,]+)(?:[^\]]+)?\]\]"                   # [[City]] or [[City, State|City]]
    r"[,\s]+([A-Z][a-zA-Z](?:[a-zA-Z\s\-]{1,30}?))"   # , Country (capitalized, no digits)
    r"(?:<br|<br|\n|\|)",                               # terminated by <br>, newline, or |
    re.IGNORECASE,
)


def _location(text: str) -> tuple[Optional[str], Optional[str]]:
    """Extract (city, country) from tournament wikitext cell context."""
    m = _LOCATION_RE.search(text)
    if not m:
        return None, None
    return m.group(1).strip(), m.group(2).strip()


def _surface(text: str) -> str:
    if _SURFACE_INDOOR_RE.search(text):
        return "Hard (i)"
    m = _SURFACE_RE.search(text)
    return m.group(1).capitalize() if m else "Hard"


def _norm_category(raw: str) -> str:
    r = raw.replace(" ", "").upper()
    if "GRANDSLAM" in r: return "Grand Slam"
    if "ATP1000" in r or "MASTERS1000" in r: return "ATP 1000"
    if "WTA1000" in r: return "WTA 1000"
    if "ATP500" in r: return "ATP 500"
    if "WTA500" in r: return "WTA 500"
    if "ATP250" in r: return "ATP 250"
    if "WTA250" in r: return "WTA 250"
    return raw.strip()


def _cell_context(wikitext: str, pos: int) -> str:
    start = max(0, pos - 1000)
    chunk = wikitext[start: pos + 300]
    sep = chunk.rfind("\n|-")
    return chunk[sep:] if sep != -1 else chunk


def _should_exclude(name: str, draw_size: int) -> bool:
    if draw_size < MIN_DRAW_SIZE:
        return True
    low = name.lower()
    return any(frag in low for frag in EXCLUDE_NAME_FRAGMENTS)


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_season_schedule(wikitext: str, year: int, gender: str) -> list[DiscoveredTournament]:
    # Normalise all apostrophe variants to plain ASCII so regex literals match
    wikitext = wikitext.replace("’", "’").replace("‘", "’")

    results: list[DiscoveredTournament] = []
    seen: set[str] = set()
    date_index = _build_date_index(wikitext, year)
    gender_suffix = "Men's singles" if gender == "M" else "Women's singles"

    def add(singles_page: str, pos: int, ctx: str, display_name: str = "") -> None:
        if singles_page in seen:
            return
        seen.add(singles_page)

        name = display_name
        if not name:
            lm = _DISPLAY_LINK_RE.search(ctx)
            if lm:
                cand = lm.group(2).strip()
                if len(cand) > 3 and cand.lower() not in ("singles", "doubles", "mixed"):
                    name = cand
        if not name:
            name = re.sub(r"^\d{4}\s+", "", singles_page)
            # Strip gender suffix — normalize dashes and apostrophes before matching
            name_norm = name.replace("–", "-").replace("—", "-").replace("’", "'").replace("‘", "'")
            stripped = re.sub(r"\s*[-–—]\s*(Men's|Women's)\s+singles$", "", name_norm, flags=re.IGNORECASE)
            if stripped != name_norm:
                name = stripped

        draw_m = _DRAW_RE.search(ctx)
        draw_size = int(draw_m.group(1)) if draw_m else 128

        if _should_exclude(name, draw_size):
            return

        cat_m = _CATEGORY_RE.search(ctx)
        category = _norm_category(cat_m.group(1)) if cat_m else (
            "ATP 250" if gender == "M" else "WTA 250"
        )
        surface = _surface(ctx)
        start_date, sched_end_date = _lookup_date(date_index, pos)
        city, country = _location(ctx)

        results.append(DiscoveredTournament(
            name=name, year=year, gender=gender,
            surface=surface, category=category, draw_size=draw_size,
            wiki_page_title=singles_page,
            start_date=start_date,
            end_date=sched_end_date,  # rough schedule date; overridden by scraper with real infobox date
            city=city, country=country,
        ))

    def _norm_title(t: str) -> str:
        t = t.replace("’", "’").replace("’", "’").strip()
        # Normalize gender-less "– Singles" → "– Men’s/Women's singles"
        if re.search(r"–\s*Singles$", t, re.IGNORECASE):
            t = re.sub(r"–\s*Singles$", f"– {gender_suffix}", t, flags=re.IGNORECASE)
        return t

    # Pass 1 — explicit singles links
    # Use the exact title from the wikilink — don't inject gender suffix.
    # Wikipedia sometimes uses "– Singles" (not "– Men's singles") even for
    # single-gender events (e.g. "2026 Halle Open – Singles"). Normalising
    # to "– Men's singles" produces a non-existent page title, causing every
    # subsequent fetch to fail and leaving wiki_page_id permanently null.
    for m in _SINGLES_LINK_RE.finditer(wikitext):
        ctx = _cell_context(wikitext, m.start())
        add(m.group(1).strip(), m.start(), ctx)

    # Pass 2 — unlinked "Singles –" entries (future tournaments)
    for m in _UNLINKED_SINGLES_RE.finditer(wikitext):
        wiki_page = m.group(2).strip()
        display = m.group(3).strip()
        singles_page = f"{wiki_page} – {gender_suffix}"
        if singles_page in seen:
            continue
        ctx = wikitext[m.start(): m.start() + 700]
        add(singles_page, m.start(), ctx, display_name=display)

    # Pass 3 — simplified format without year: [[Swedish Open]] ... Singles
    for m in _SIMPLE_TOURNAMENT_RE.finditer(wikitext):
        tournament_name = m.group(1).strip()
        if not tournament_name or len(tournament_name) < 3:
            continue
        # Build the full page title with year
        wiki_page = f"{year} {tournament_name}"
        singles_page = f"{wiki_page} – {gender_suffix}"
        if singles_page in seen:
            continue
        ctx = wikitext[m.start(): m.start() + 700]
        add(singles_page, m.start(), ctx, display_name=tournament_name)

    # Pass 4 — no-year piped format: [[Swiss Open (tennis)|Swiss Open]] at cell start
    for m in _NOYR_PIPED_RE.finditer(wikitext):
        page_title = m.group(1).strip()
        display = m.group(2).strip()
        # Skip year-prefixed links (handled by Pass 2), file/namespace links, and non-name display values
        if re.match(r'^\d{4}', page_title):
            continue
        if ':' in page_title:  # File:, Image:, Template:, etc.
            continue
        if not display or not display[0].isupper() or re.match(r'^\d', display):
            continue
        wiki_page = f"{year} {page_title}"
        singles_page = f"{wiki_page} – {gender_suffix}"
        if singles_page in seen:
            continue
        ctx = wikitext[m.start(): m.start() + 700]
        add(singles_page, m.start(), ctx, display_name=display)

    return sorted(results, key=lambda t: t.sort_key)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def discover_tournaments(year: int) -> list[DiscoveredTournament]:
    atp_wt, _ = await fetch_wikitext(f"{year} ATP Tour")
    wta_wt, _ = await fetch_wikitext(f"{year} WTA Tour")
    atp = parse_season_schedule(atp_wt, year, "M")
    wta = parse_season_schedule(wta_wt, year, "F")
    return sorted(atp + wta, key=lambda t: t.sort_key)
