"""THE DRAW-LEVEL REFERENCE FIGURES, WORKED OUT ONCE AND KEPT (owner, 2026-09-19).

The three tiebreak questions show figures of two kinds. Some depend only on the
DRAW — its tour, its tier and its surface — so they are the same for everybody
who opens the drawer and they cannot change while the tournament runs:

  * how many sets a final at this tour and tier, on this surface, has gone
    over the past ten years
  * the aces per set, and the PLAYING minutes per set, in those finals over
    the past five
  * and from the second of those, what a two, three, four or five-set final
    works out to in minutes

The rest are about the two players THIS bracket has picked, so they are
per-reader and per-pick and are fetched live every time.

Everything here belongs to the first kind. It is computed once and stored on
the draw as `final_ref_json`, so opening the drawer costs no history queries
for it at all.

WHY A SWEEP RATHER THAN A CALL AT CREATION. A draw is created by three
different paths — the discovery route, the tournament sync and the admin's own
add endpoint — and this project has already paid for the per-call-site version
of exactly this: the "draw released" email lived at the call sites, two of the
four had it, and Swedish Open's release was never announced
(reference_draw_release_notifications). One sweep covers every path, including
whatever path is added next, and it fills a draw within a cycle of its
creation — long before the bracket is out and anybody can open the drawer.

READS NEVER WRITE. `for_draw` returns the stored block when there is one and
computes the same thing in memory when there is not. It does not save: a GET
that marks a row dirty ends up holding the writer on the next query in the
session, which is how a draw page came to hold a write lock
(feedback_reads_must_not_write). The sweep is the only writer.
"""
import json
import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import or_, select

from app.database import AsyncSessionLocal
from app.models.tournament import Draw

logger = logging.getLogger(__name__)

# Bump when the shape or the arithmetic changes, so stored blocks are
# recomputed rather than read forever under a schema they predate.
#   2 — per-set durations became PLAYING time, breaks stripped before
#       averaging and re-added for the predicted set count (owner,
#       2026-09-19). A block from version 1 has the breaks counted twice in
#       its minutes_by_sets and must not be trusted.
VERSION = 2
# The set counts a final can go, per format. A best-of-three final cannot be
# four sets, and offering a figure for one would be nonsense.
SET_COUNTS = {3: (2, 3), 5: (3, 4, 5)}


def compute(conn, tour: str, tier: str, surface: str, best_of: int,
            today: Optional[date] = None) -> dict:
    """The block, from one connection. Pure: no session, no draw, no writes."""
    from app.services.history.final_stats import (
        RATE_YEARS, SETS_YEARS, estimate_minutes, tier_finals,
    )
    sets = tier_finals(conn, tour, tier, surface, SETS_YEARS, today)
    rates = tier_finals(conn, tour, tier, surface, RATE_YEARS, today)
    # PLAYING minutes per set: breaks already stripped, so putting them back
    # below gives each predicted set count its own correct number of them.
    play = (rates or {}).get("play_minutes_per_set")
    return {
        "version": VERSION,
        "tour": tour, "tier": tier, "surface": surface, "best_of": best_of,
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # How many sets a final here goes, over ten years.
        "sets": None if not sets else {
            "sets_per_match": sets["sets_per_match"],
            "matches": sets["matches"],
            "years": sets["years"],
            "surface_scoped": sets["surface_scoped"],
        },
        # The per-set rates, over five.
        "rates": None if not rates else {
            "aces_per_set": rates["aces_per_set"],
            "play_minutes_per_set": rates["play_minutes_per_set"],
            "matches": rates["matches"],
            "years": rates["years"],
            "surface_scoped": rates["surface_scoped"],
        },
        # A two, three, four or five-set final in minutes — playing time times
        # the sets, plus a changeover between each pair. NOT per_set * n: that
        # would carry the history's break count instead of this length's.
        "minutes_by_sets": (
            {str(n): estimate_minutes(play, n) for n in SET_COUNTS.get(best_of, SET_COUNTS[3])}
            if play else None
        ),
    }


def _conditions(draw) -> tuple:
    """(tour, tier, surface, best_of) for a draw — the whole cache key."""
    from app.services.history.link import norm_surface
    from app.services.schedule import _best_of
    tour = "wta" if (getattr(draw, "gender", "") or "").upper() == "F" else "atp"
    return (tour, draw.scoring_tier, norm_surface(getattr(draw, "surface", None)),
            _best_of(draw, "singles", "main"))


def _stale(block, draw) -> bool:
    """Whether a stored block still describes this draw.

    A draw's surface or category can be corrected after it is created — a
    discovery seeds both from a season page — and the figures have to follow,
    or a clay 250 keeps answering with hard-court 500 numbers.
    """
    if not isinstance(block, dict) or block.get("version") != VERSION:
        return True
    tour, tier, surface, best_of = _conditions(draw)
    return (block.get("tour") != tour or block.get("tier") != tier
            or block.get("surface") != surface or block.get("best_of") != best_of)


async def for_draw(db, draw) -> Optional[dict]:
    """The stored block, or the same figures computed in memory. NEVER WRITES."""
    stored = getattr(draw, "final_ref_json", None)
    if isinstance(stored, str):                     # older rows, stored as text
        try:
            stored = json.loads(stored)
        except ValueError:
            stored = None
    if stored and not _stale(stored, draw):
        return stored
    from app.services.history import db as hdb
    tour, tier, surface, best_of = _conditions(draw)
    try:
        return await hdb.run(lambda c: compute(c, tour, tier, surface, best_of))
    except Exception:       # noqa: BLE001 — a missing reference must not break the drawer
        logger.debug("final reference unavailable for draw %s", getattr(draw, "id", "?"))
        return None


async def fill_missing(limit: int = 40) -> int:
    """THE ONLY WRITER. Fills or refreshes every draw that needs it.

    Scoped to draws that could still be picked or played — a finished season's
    draws would be thousands of history queries for figures nobody will open —
    and capped per pass so one sweep never runs long.
    """
    from app.services.history import db as hdb

    filled = 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Draw).where(
                or_(Draw.status != "completed", Draw.status.is_(None)),
            ).order_by(Draw.start_date.desc().nullslast()).limit(300)
        )).scalars().all()
        todo = [d for d in rows if _stale(getattr(d, "final_ref_json", None), d)][:limit]
        if not todo:
            return 0
        for d in todo:
            tour, tier, surface, best_of = _conditions(d)
            try:
                d.final_ref_json = await hdb.run(
                    lambda c, t=tour, ti=tier, s=surface, b=best_of: compute(c, t, ti, s, b))
                filled += 1
            except Exception as exc:    # noqa: BLE001
                logger.warning("final reference failed for draw %s: %s", d.id, exc)
        await db.commit()
    if filled:
        logger.info("Final reference: cached figures for %d draw(s)", filled)
    return filled
