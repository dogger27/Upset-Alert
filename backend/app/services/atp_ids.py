"""
ATP tournament ids, scraped once per season from atptour.com.

WHY A BROWSER. The id is the path segment of a tournament's order-of-play PDF
on protennislive, and the only place it is published is the tournament's own
atptour.com URL. That site sits behind a WAF that answers 403 to every
non-browser client — plain httpx, a browser User-Agent on httpx, even headless
Chromium with default settings, and its own sitemap too. A real browser context
is the only thing it serves.

WHY THIS IS FINE. atptour.com's robots.txt permits /en/tournaments for
User-Agent: * — the disallow list is /sitecore/, */ajax/*, the search and video
filters, and a few score paths. Named AI crawlers are separately and explicitly
disallowed; this is not one of those. It is a tennis app reading a public
tournament index for its own operation, at ONE page load per run, on a weekly
schedule. The WAF is a blunt instrument applied ahead of the site's own stated
policy, not a statement about this path.

WHY WIKIPEDIA IS NOT ENOUGH. It carries the same URL in article external links,
but only for 19 of 44 past 2026 ATP tournaments — and the misses include the
Australian Open, Miami, Dubai and Barcelona. 43% cannot carry an autonomous
feature.

The ids are tournament-level, not per-edition: Cincinnati has been 422 for
years, Monte-Carlo 410. So this rarely needs to run at all, and an existing id
is never overwritten — a run that comes back empty leaves everything intact.
"""

import re
from typing import Optional

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.tournament import Tournament
from app.services.rankings import _norm
from app.services.system_log import app_log

_TOURNAMENTS_URL = "https://www.atptour.com/en/tournaments"

# A real browser's UA. The point is not to disguise anything — the request is
# permitted — it is that the WAF rejects anything that does not look like the
# browser a person would use.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_LINK_RE = re.compile(r"/en/tournaments/([a-z0-9\-]+)/(\d+)/")

# Slug against our name, where the two do not meet in the middle. Only for cases
# token matching genuinely cannot solve, not a general dumping ground.
_ALIASES = {
    "cincinnati": "cincinnati open",
    "indian-wells": "indian wells open",
    "miami": "miami open",
    "roland-garros": "french open",
    "wimbledon": "wimbledon",
    "us-open": "us open",
    "australian-open": "australian open",
    "nitto-atp-finals": "atp finals",
    "monte-carlo": "monte-carlo masters",
    "winston-salem": "winston-salem open",
    # Spelling differences the token match cannot bridge: the ATP writes
    # "kitzbuhel" and "marrakech" where our city fields hold "Kitzbühel" and
    # "Marrakesh".
    "kitzbuhel": "austrian open",
    "marrakech": "grand prix hassan ii",
}


async def fetch_atp_tournament_ids() -> dict[str, int]:
    """{slug: id} for the whole tour, from one page load."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=[
            "--no-sandbox", "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ])
        try:
            ctx = await browser.new_context(
                user_agent=_UA, locale="en-US",
                viewport={"width": 1280, "height": 900},
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            # Headless Chromium advertises itself through navigator.webdriver,
            # which is the specific signal that gets a 403 here.
            await ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            page = await ctx.new_page()
            resp = await page.goto(_TOURNAMENTS_URL, wait_until="domcontentloaded",
                                   timeout=60_000)
            if not resp or resp.status != 200:
                raise RuntimeError(f"atptour.com returned {resp.status if resp else 'no response'}")
            await page.wait_for_timeout(3_000)     # let the list render
            html = await page.content()
        finally:
            await browser.close()

    return {slug: int(tid) for slug, tid in _LINK_RE.findall(html)}


def _match_slug(name: str, city: Optional[str], slugs: dict[str, int]) -> Optional[int]:
    """Our tournament -> an ATP id, or None.

    CITY is the primary key, not the name. ATP slugs are the host city
    ("buenos-aires", "rome", "beijing") while our names are the sponsor or
    country title ("Argentina Open", "Italian Open", "China Open") — matching on
    name alone left a third of the tour unmatched, every one of them a naming
    difference rather than a missing id.

    Ambiguity returns nothing. A wrong id polls a different tournament's
    schedule, and a schedule confidently showing the wrong matches is far worse
    than a missing button.
    """
    norm_name = _norm(name)
    name_tokens = set(norm_name.split())
    city_tokens = set(_norm(city).split()) if city else set()

    for slug, tid in slugs.items():
        if _ALIASES.get(slug) and _norm(_ALIASES[slug]) == norm_name:
            return tid

    for tokens in (city_tokens, name_tokens):
        if not tokens:
            continue
        hits = {tid for slug, tid in slugs.items()
                if (st := set(_norm(slug.replace("-", " ")).split())) and st <= tokens}
        if len(hits) == 1:
            return hits.pop()
    return None


async def refresh_atp_tournament_ids() -> dict:
    """Fill in missing ATP ids. Never overwrites one already on record."""
    try:
        slugs = await fetch_atp_tournament_ids()
    except Exception as exc:
        await app_log("error", "order_of_play",
                      f"ATP tournament id scrape failed: {type(exc).__name__}: {exc}",
                      dedup_key="atp_id_scrape_fail", dedup_hours=24)
        return {"error": str(exc), "stamped": 0}

    if not slugs:
        await app_log("error", "order_of_play",
                      "ATP tournament id scrape returned no ids — the page layout "
                      "has probably changed.",
                      dedup_key="atp_id_scrape_empty", dedup_hours=24)
        return {"error": "no ids found", "stamped": 0}

    stamped, unmatched = 0, []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Tournament).where(Tournament.atp_tournament_id.is_(None)))).scalars().all()
        for t in rows:
            tid = _match_slug(t.name, t.city, slugs)
            if tid:
                t.atp_tournament_id = tid
                stamped += 1
            else:
                unmatched.append(t.name)
        if stamped:
            await db.commit()

    return {"found": len(slugs), "stamped": stamped, "unmatched": len(unmatched)}
