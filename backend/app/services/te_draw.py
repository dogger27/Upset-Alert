"""TENNIS EXPLORER'S DRAW PAGE — the complete ATP field two days out, keyed by
the player slugs this project already stores.

    https://www.tennisexplorer.com/{tournament}/{year}/atp-men/?draw=1

Found 2026-09-21 after every other route for the men's draw came up short:
Sofascore's cup tree is a view over events and hides a player until his first
match exists (a seed facing a qualifier is invisible until qualifying ends);
the ATP's JSON feed needs an operator credential; its PDF is the parser this
project has been nursing for months. TE, which we already fetch for rankings
and H2H, renders the bracket as ABSOLUTELY-POSITIONED DIVS on a fixed grid:

    <div style="position:absolute; left:10px; top:44px; ...">bye</div>
    <div style="... left:10px; top:404px; ..."><a href="/player/marozsan/">Marozsan</a> [6]</div>
    <div style="... left:10px; top:428px; ..."> [Q]</div>

    left   the round: 10px is round 1, then 150, 290, 430, 570, 710
    top    the slot, in 24px steps — its rank within the column IS the
           bracket position
    text   "bye"; a player with "[N]" seed and "[WC]"/"[Q]"/"[LL]" entry
           marks; or an empty name with "[Q]" for a qualifier not yet known
    href   /player/{slug}/ — the te_slug already on draw_entries, so identity
           needs no name matching at all

MEASURED AGAINST OUR WIKIPEDIA-BUILT DRAWS, 2026-09-21, two days before play:
Hangzhou and Chengdu both 28 of 32 slots identical, every qualifier placeholder
in the right slot, and 24 of 24 slugs equal to our stored te_slug. The other
four slots per draw were the bottom-half bye pairs, where TE — like the WTA's
official sheet — prints the bye ABOVE the seed; the parser normalises to the
odd-slot convention every draw in the database uses. Marozsán, Safiullin,
Sweeny and Hijikata, the four Sofascore could not see, were all there.

TWO LIMITS, STATED PLAINLY. Seeds are not always marked yet: Hangzhou had all
eight, Chengdu none, on the same afternoon. So a seed from TE is taken when
printed and never required; Sofascore's teamSeed fills gaps once its events
exist. And nationality is not on the bracket; it arrives with the ranking
assignment that keys off the slug.

THIS IS A SCRAPE OF A THIRD-PARTY PAGE. It is not JSON and it can change
without notice — which is why every geometric assumption above is a tested
constant, why a page that fails those assumptions yields None rather than a
half-bracket, and why Sofascore corroborates every draw this builds.
"""
import hashlib
import html as _html
import logging
import math
import os
import re
import time
import unicodedata
from collections import defaultdict
from typing import Optional

from app.services.sofa_draw_shape import DrawShape, ShapeEntrant

logger = logging.getLogger(__name__)

BASE = "https://www.tennisexplorer.com"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"),
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 20

# Polite by construction: one fetch of a page per hour is plenty for a draw
# that changes once, and the refresh loop asks every 30 minutes.
CACHE_DIR = os.environ.get("TE_CACHE_DIR", "/data/te-cache")
CACHE_TTL = 3600.0

# The grid. Round-1 slots are 24px apart; a page that violates this is not a
# bracket this parser understands.
SLOT_PITCH_PX = 24
_ENTRY = {"Q": "Q", "WC": "WC", "LL": "LL", "SE": "SE", "PR": "PR",
          "ALT": "Alt", "A": "Alt", "NG": "NG"}

_DIV = re.compile(
    r'<div style="\s*position:\s*absolute;\s*left:\s*(\d+)px;\s*top:\s*(\d+)px;[^"]*"\s*>(.*?)</div>',
    re.S)
_SEED = re.compile(r"\[(\d{1,2})\]")
_MARK = re.compile(r"\[(Q|WC|LL|SE|PR|ALT|Alt|A|NG)\]")
_SLUG = re.compile(r'href="/player/([^"/]+)/?"')


def _text(inner: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", inner))).strip()


def parse_bracket(page: str) -> Optional[DrawShape]:
    """The main-draw bracket on a TE draw page, or None if there is none.

    Only round 1 is read for the shape; later columns only tell us how many
    rounds there are. Results are never taken from here.
    """
    cols: dict = defaultdict(list)
    for left, top, inner in _DIV.findall(page):
        if "match-detail" in inner:
            continue                       # the H2H buttons between pairs
        cols[int(left)].append((int(top), inner))
    if not cols:
        return None
    first = min(cols)
    slots = sorted(cols[first])
    if len(slots) < 4 or len(slots) & (len(slots) - 1):
        return None                        # not a power-of-two bracket
    tops = [t for t, _ in slots]
    if any(b - a != SLOT_PITCH_PX for a, b in zip(tops, tops[1:])):
        return None                        # the grid is not the grid we know

    size = len(slots)
    shape = DrawShape(bracket_size=size, num_rounds=int(math.log2(size)))
    raw: dict = {}
    for pos, (_, inner) in enumerate(slots, start=1):
        txt = _text(inner)
        if txt.lower() == "bye":
            raw[pos] = None
            continue
        seed = _SEED.search(txt)
        mark = _MARK.search(txt)
        name = re.sub(r"\s*\[[^\]]*\]", "", txt).strip()
        slug = _SLUG.search(inner)
        raw[pos] = ShapeEntrant(
            bracket_position=pos, name=name,
            seed=int(seed.group(1)) if seed else None,
            entry_type=_ENTRY.get(mark.group(1).upper()) if mark else None,
            te_slug=slug.group(1) if slug else None)

    # Normalise byes: the player takes the odd slot of the pair, the bye the
    # even one, as every draw already in the database has it.
    for pos in range(1, size + 1, 2):
        a, b = raw.get(pos, "missing"), raw.get(pos + 1, "missing")
        if a is None and b is None:
            return None                    # two byes in one pair is not a draw
        if a is None and isinstance(b, ShapeEntrant):
            b.bracket_position = pos
            raw[pos], raw[pos + 1] = b, None
    for pos in range(1, size + 1):
        v = raw.get(pos, "missing")
        if v is None:
            shape.byes.append(pos)
        elif isinstance(v, ShapeEntrant):
            shape.entrants.append(v)
    shape.entrants.sort(key=lambda e: e.bracket_position)
    return shape


# ── finding the page for a draw ─────────────────────────────────────────

def _fold(s: str) -> str:
    n = unicodedata.normalize("NFKD", s or "")
    n = "".join(c for c in n if not unicodedata.combining(c))
    return " ".join(n.lower().replace("-", " ").split())


# TE prints a tournament row two ways — the front page puts a flag span INSIDE
# the anchor, the index embedded in a draw page puts a type span BEFORE it —
# so this reads only what both share: the t-name cell, the anchor's path, and
# the anchor's text with its tags stripped. The tour is in the path.
_ROW = re.compile(
    r'<td class="t-name">(?:<span[^>]*>[^<]*</span>)?\s*'
    r'<a href="(/[^"/]+/(\d{4})/(atp-men|wta-women)/)"[^>]*>(.*?)</a>', re.S)
_NOISE = {"open", "atp", "wta", "the", "championships", "international", "cup"}


def _tokens(s: str) -> set:
    return {t for t in _fold(s).split() if t not in _NOISE}


def index_tournaments(index_page: str) -> list:
    """Every (name, path, year, tour) TE lists on its front page."""
    out, seen = [], set()
    for path, year, tour, inner in _ROW.findall(index_page):
        if path in seen:
            continue                       # the front page lists some rows twice
        seen.add(path)
        out.append({"name": _text(inner), "path": path,
                    "year": int(year), "tour": "M" if tour == "atp-men" else "F"})
    return out


def match_tournament(rows: list, *, name: str, city: Optional[str],
                     gender: str, year: int) -> Optional[str]:
    """The one TE path that is this draw, or None — never a best guess.

    TE names an event by its CITY ("Seoul WTA", "Sao Paulo WTA", "Hangzhou"),
    so the city is tried first and the tournament name second. Two candidates
    is no candidate: a name is not an identity, and the geometry check that
    follows the fetch is what makes accepting one safe.
    """
    want = [r for r in rows if r["tour"] == gender and r["year"] == year
            and "challenger" not in r["path"] and "itf" not in r["path"]
            and "utr" not in r["path"] and "davis" not in r["path"]]
    for probe in (city, name):
        if not probe:
            continue
        toks = _tokens(probe)
        if not toks:
            continue
        hits = [r for r in want if toks & _tokens(r["name"]) == toks
                or _tokens(r["name"]) and _tokens(r["name"]) <= toks]
        if len(hits) == 1:
            return hits[0]["path"]
        if len(hits) > 1:
            return None
    return None


# ── fetching, politely ─────────────────────────────────────────────────

async def _get(path: str) -> str:
    """One page, served from a one-hour disk cache when it can be."""
    f = f"{CACHE_DIR}/{hashlib.sha1(path.encode()).hexdigest()}.html"
    try:
        if time.time() - os.path.getmtime(f) < CACHE_TTL:
            with open(f, "r", encoding="utf-8") as fh:
                return fh.read()
    except OSError:
        pass
    import httpx
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(f"{BASE}{path}", headers=HEADERS)
        resp.raise_for_status()
        page = resp.text
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(page)
    except OSError:
        pass
    return page


async def fetch_shape(draw) -> Optional[DrawShape]:
    """The bracket for this draw, or None when TE has no page or no draw yet.

    Two requests at most — the front page (cached an hour, shared by every
    draw) and the draw page — and none when the draw cannot be identified.
    """
    rows = index_tournaments(await _get("/"))
    path = match_tournament(rows, name=draw.name, city=draw.city,
                            gender=draw.gender, year=draw.year)
    if not path:
        logger.debug("TE: no unique tournament for %s %s (%s)", draw.year, draw.name, draw.gender)
        return None
    shape = parse_bracket(await _get(f"{path}?draw=1"))
    if shape is None:
        logger.debug("TE: %s has no parseable bracket yet", path)
    return shape
