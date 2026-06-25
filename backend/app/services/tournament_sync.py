"""
Tournament sync service.

Provides a robust upsert that handles Wikipedia article renames (e.g. "Citi Open"
→ "Washington Open") without creating duplicates.

Matching priority
-----------------
1. Exact wiki_page_title  →  same record, update fields
2. Same year + gender + category + start_date within 7 days:
   • For unique-per-slot tiers (500/1000/Grand Slam): accept single match
   • For 250-tier (multiple per week): also require city agreement
   • Name-similarity as final tiebreaker
3. No match  →  INSERT new record

After every sync a deduplication pass runs and logs warnings for any remaining
(year, gender, category, start_date) collisions so they can be investigated.
"""

import logging
import math
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tournament import Tournament
from app.services.discovery import DiscoveredTournament
from app.services.draw_dates import calculate_draw_release_dates

logger = logging.getLogger(__name__)

# ATP/WTA 500 run 2 simultaneous events per week, so they are NOT unique per slot.
# Only Masters 1000 and Grand Slams have exactly one tournament per gender per week.
_UNIQUE_PER_SLOT = {"ATP 500", "WTA 500", "ATP 1000", "WTA 1000", "Grand Slam"}
_ONE_PER_SLOT = {"ATP 1000", "WTA 1000", "Grand Slam"}


def _num_rounds(draw_size: int) -> int:
    return max(1, math.ceil(math.log2(draw_size))) if draw_size > 0 else 1


def _name_overlap(a: str, b: str) -> bool:
    """True if one name contains the other (case-insensitive)."""
    a, b = a.lower(), b.lower()
    return a in b or b in a


async def find_existing_match(
    db: AsyncSession,
    discovered: DiscoveredTournament,
    year: int,
) -> Optional[Tournament]:
    """Return the best existing DB record for *discovered*, or None."""

    # 1. Exact wiki_page_title
    res = await db.execute(
        select(Tournament).where(Tournament.wiki_page_title == discovered.wiki_page_title)
    )
    exact = res.scalar_one_or_none()
    if exact:
        return exact

    if not discovered.start_date:
        return None

    # 2. Same year / gender / category + date within 7 days
    date_str = discovered.start_date.isoformat()
    res = await db.execute(
        select(Tournament)
        .where(
            Tournament.year == year,
            Tournament.gender == discovered.gender,
            Tournament.category == discovered.category,
            Tournament.start_date.isnot(None),
            func.abs(
                func.julianday(Tournament.start_date) - func.julianday(date_str)
            ) <= 7,
        )
    )
    candidates = res.scalars().all()

    if not candidates:
        return None

    if len(candidates) == 1:
        # For 1000s and Grand Slams, a single date-match is definitive
        if discovered.category in _ONE_PER_SLOT:
            return candidates[0]
        # For 500s and 250s, require city or name agreement as a sanity check
        c = candidates[0]
        if discovered.city and c.city and discovered.city.lower() == c.city.lower():
            return c
        if _name_overlap(discovered.name, c.name):
            return c
        return None

    # Multiple candidates (ATP/WTA 250, multiple per week)
    if discovered.city:
        city_matches = [
            c for c in candidates
            if c.city and c.city.lower() == discovered.city.lower()
        ]
        if len(city_matches) == 1:
            return city_matches[0]

    name_matches = [c for c in candidates if _name_overlap(discovered.name, c.name)]
    if len(name_matches) == 1:
        return name_matches[0]

    logger.warning(
        "Ambiguous match for %s %s (%s %s) — %d candidates, skipping upsert",
        year, discovered.name, discovered.gender, discovered.category, len(candidates),
    )
    from app.services.system_log import app_log
    await app_log(
        "warning", "discovery",
        f"Ambiguous tournament match — '{discovered.name}' {year} skipped",
        {"name": discovered.name, "year": year, "gender": discovered.gender,
         "category": discovered.category, "candidates": len(candidates)},
        dedup_key=f"ambiguous_{year}_{discovered.name}", dedup_hours=24,
    )
    return None


async def _apply_update(
    existing: Tournament,
    discovered: DiscoveredTournament,
    db: AsyncSession,
) -> bool:
    """Update *existing* from *discovered*. Returns True if any field changed."""
    changed = False
    for attr, val in [
        ("wiki_page_title", discovered.wiki_page_title),
        ("name", discovered.name),
        ("surface", discovered.surface),
        ("category", discovered.category),
        ("draw_size", discovered.draw_size),
        ("num_rounds", _num_rounds(discovered.draw_size)),
        ("start_date", discovered.start_date),
        ("end_date", discovered.end_date),
        ("city", discovered.city),
        ("country", discovered.country),
    ]:
        if val is not None and getattr(existing, attr) != val:
            setattr(existing, attr, val)
            changed = True

    # Recalculate estimated draw release dates using category-specific history
    if discovered.start_date and discovered.category:
        direct, qual = await calculate_draw_release_dates(
            discovered.start_date, discovered.category, discovered.gender, db=db
        )
        if direct and existing.draw_release_direct != direct:
            existing.draw_release_direct = direct
            changed = True
        if qual != existing.draw_release_qualifiers:
            existing.draw_release_qualifiers = qual
            changed = True

    return changed


async def sync_season(
    db: AsyncSession,
    year: int,
    *,
    scrape_new: bool = True,
) -> dict:
    """
    Discover and upsert all tournaments for *year*.

    Returns a summary dict with keys: updated, inserted, skipped, duplicates_found.
    """
    from app.services.discovery import discover_tournaments
    from app.services.draw_dates import calculate_draw_release_dates

    discovered = await discover_tournaments(year)
    logger.info("Discovered %d tournaments for %d", len(discovered), year)

    updated = inserted = skipped = 0

    for d in discovered:
        existing = await find_existing_match(db, d, year)

        if existing:
            old_title = existing.wiki_page_title
            changed = await _apply_update(existing, d, db)
            if changed:
                if old_title != d.wiki_page_title:
                    logger.info(
                        "Renamed %r → %r", old_title, d.wiki_page_title
                    )
                updated += 1
            else:
                skipped += 1

            # If we've never successfully fetched this singles page (page_id is
            # still null), try now — covers cases where the page didn't exist
            # when the tournament was first inserted, or where a title rename
            # just corrected a bad stored title.
            if scrape_new and existing.wiki_page_id is None:
                try:
                    from app.routers.tournaments import _do_scrape
                    await _do_scrape(existing, db)
                    logger.info("Confirmed wiki_page_id for %s", existing.wiki_page_title)
                except Exception as exc:
                    logger.debug("Still no page for %s: %s", existing.wiki_page_title, exc)

            continue

        # New tournament — each insert is isolated in a savepoint so that a scrape
        # failure (e.g. resolved wiki_page_title collides with an existing record)
        # only rolls back this one record and leaves the rest of the sync intact.
        try:
            async with db.begin_nested():
                draw_direct, draw_qualifiers = await calculate_draw_release_dates(
                    d.start_date, d.category, d.gender, db=db
                )
                t = Tournament(
                    name=d.name,
                    year=year,
                    gender=d.gender,
                    surface=d.surface,
                    category=d.category,
                    draw_size=d.draw_size,
                    num_rounds=_num_rounds(d.draw_size),
                    start_date=d.start_date,
                    end_date=d.end_date,
                    draw_release_direct=draw_direct,
                    draw_release_qualifiers=draw_qualifiers,
                    city=d.city,
                    country=d.country,
                    wiki_page_title=d.wiki_page_title,
                    status="upcoming",
                )
                db.add(t)
                await db.flush()

                if scrape_new:
                    from app.routers.tournaments import _do_scrape
                    await _do_scrape(t, db)

            inserted += 1
            logger.info("Added %d %s (%s)", year, d.name, d.gender)
        except Exception as exc:
            logger.warning("Skipped new tournament %s %s: %s", year, d.name, exc)
            skipped += 1

    await db.commit()

    dups = await _find_duplicates(db, year)
    if dups:
        logger.warning(
            "Duplicate tournaments found after sync for %d: %s",
            year,
            [(d[0], d[1], d[2]) for d in dups],
        )

    summary = dict(updated=updated, inserted=inserted, skipped=skipped, duplicates_found=len(dups))
    logger.info("Sync complete for %d: %s", year, summary)
    return summary


async def _find_duplicates(db: AsyncSession, year: int) -> list:
    """
    Detect real duplicate records.

    Two strategies:
    1. Same name + gender: always a duplicate regardless of tier.
    2. Same gender + category + start_date for unique-per-slot tiers (500/1000/GS):
       these tiers have exactly one tournament per slot, so two records = duplicate.
       ATP/WTA 250 are intentionally excluded because multiple run simultaneously.
    """
    results = []

    # Strategy 1: identical name + gender
    res = await db.execute(
        select(
            Tournament.name,
            Tournament.gender,
            Tournament.category,
            Tournament.start_date,
            func.count().label("n"),
        )
        .where(Tournament.year == year)
        .group_by(Tournament.name, Tournament.gender)
        .having(func.count() > 1)
    )
    results.extend(res.all())

    # Strategy 2: same slot in one-per-slot tiers (1000/Grand Slam only)
    # ATP/WTA 500 run two simultaneous events per week so they are intentionally excluded.
    res = await db.execute(
        select(
            Tournament.category,
            Tournament.gender,
            Tournament.start_date,
            func.count().label("n"),
        )
        .where(
            Tournament.year == year,
            Tournament.category.in_(_ONE_PER_SLOT),
            Tournament.start_date.isnot(None),
        )
        .group_by(Tournament.gender, Tournament.category, Tournament.start_date)
        .having(func.count() > 1)
    )
    results.extend(res.all())

    return results
