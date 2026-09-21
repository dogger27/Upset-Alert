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
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tournament import Draw, DrawCategory, DrawCategoryVariant
from app.services.discovery import DiscoveredTournament
from app.services.draw_dates import (calculate_draw_release_dates, compute_entry_ranking_week,
                                      compute_seed_ranking_week, tournament_monday)

logger = logging.getLogger(__name__)


def _num_rounds(draw_size: int) -> int:
    return max(1, math.ceil(math.log2(draw_size))) if draw_size > 0 else 1


def tennis_week(d: date, season_year: int) -> int:
    """Return the ATP/WTA tennis season week number for a date.

    Week 1 = the week whose Monday is the first Monday of January in season_year.
    Early-Jan events before that Monday (e.g. United Cup Jan 02) are clamped to 1.
    December-start events that belong to the following season (d.year < season_year)
    return 0 — they straddle the year boundary (e.g. Auckland Open Dec 29).
    """
    if d.year < season_year:
        return 0
    jan1 = date(season_year, 1, 1)
    days_to_monday = (7 - jan1.weekday()) % 7
    first_monday = jan1 + timedelta(days=days_to_monday)
    # FROM THE TOURNAMENT'S OWN MONDAY, not from the start date. A Sunday start
    # is six days into the PREVIOUS week by arithmetic and in the NEXT week by
    # the tour's calendar — which put Guadalajara (Sun 13 Sep) in week 36 and
    # SP Open (Mon 14 Sep) in week 37, so the draw-release batcher treated one
    # tour week as two and sent an email for each (owner, 2026-09-12).
    return max(1, (tournament_monday(d) - first_monday).days // 7 + 1)


async def _resolve_variant_id(
    db: AsyncSession, category: Optional[str], draw_size: int, name: str
) -> Optional[int]:
    """Return the tournament_categories_variants.id that best matches this tournament."""
    if not category:
        return None

    res = await db.execute(
        select(DrawCategoryVariant).where(DrawCategoryVariant.category_name == category)
    )
    variants = res.scalars().all()
    if not variants:
        return None

    if category == "Grand Slam":
        n = name.lower()
        for label, kw in [
            ("Australian Open", "australian"),
            ("French Open",     "french"),
            ("French Open",     "roland"),
            ("Wimbledon",       "wimbledon"),
            ("US Open",         "us open"),
        ]:
            if kw in n:
                match = next((v for v in variants if v.label == label), None)
                if match:
                    return match.id

    # For all other categories (and Grand Slam fallback): match on draw_size
    size_match = next((v for v in variants if v.draw_size == draw_size), None)
    if size_match:
        return size_match.id

    # Fall back to the default variant for this category
    default = next((v for v in variants if v.is_default), None)
    return default.id if default else None


def _name_overlap(a: str, b: str) -> bool:
    """True if one name contains the other (case-insensitive)."""
    a, b = a.lower(), b.lower()
    return a in b or b in a


async def find_existing_match(
    db: AsyncSession,
    discovered: DiscoveredTournament,
    year: int,
) -> Optional[Draw]:
    """Return the best existing DB record for *discovered*, or None."""

    # 1. Exact wiki_page_title
    res = await db.execute(
        select(Draw).where(Draw.wiki_page_title == discovered.wiki_page_title)
    )
    exact = res.scalar_one_or_none()
    if exact:
        return exact

    # 1b. The stored title may use a different suffix variant than the
    #     discovered one ("– Women's singles" vs "– Singles", either way
    #     round). Match on any variant — gender-filtered, because the
    #     "– Singles" variant of a combined event's title is shared by both
    #     tours' records.
    from app.services.scraper import singles_title_variants
    variants = singles_title_variants(discovered.wiki_page_title, discovered.gender)
    res = await db.execute(
        select(Draw).where(
            Draw.wiki_page_title.in_(variants),
            Draw.gender == discovered.gender,
            Draw.year == year,
        )
    )
    alt = res.scalars().first()
    if alt:
        return alt

    if not discovered.start_date:
        return None

    # 2. Same year / gender / category + date within 7 days
    date_str = discovered.start_date.isoformat()
    res = await db.execute(
        select(Draw)
        .where(
            Draw.year == year,
            Draw.gender == discovered.gender,
            Draw.category == discovered.category,
            Draw.start_date.isnot(None),
            func.abs(
                func.julianday(Draw.start_date) - func.julianday(date_str)
            ) <= 7,
        )
    )
    candidates = res.scalars().all()

    if not candidates:
        return None

    if len(candidates) == 1:
        # For 1000s and Grand Slams, a single date-match is definitive
        cat_row = await db.get(DrawCategory, discovered.category)
        if cat_row and cat_row.one_per_slot:
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
    existing: Draw,
    discovered: DiscoveredTournament,
    db: AsyncSession,
) -> bool:
    """Update *existing* from *discovered*. Returns True if any field changed."""
    changed = False
    # Season-page dates are rough week labels (a rowspan cell can cover several
    # events — the "Dec 29 / Jan 5" opener week spans United Cup + Brisbane +
    # Auckland). The scraper refines dates from the tournament infobox and
    # freezes them once active/completed (see tournaments.py), so discovery
    # must not clobber refined dates on frozen draws.
    # Frozen once play starts — and once the first ball has been OBSERVED,
    # which is earlier. Without that second clause the season page simply
    # rewrites a corrected start_date back to its guess on the next pass.
    dates_frozen = (existing.status in ("active", "completed")
                    or existing.first_match_at is not None)
    # Bracket shape belongs to the scraper once a real draw exists. The season
    # page carries a nominal entry count ("48S") that counts qualifying and bye
    # slots the played bracket doesn't contain, and applying it to a live draw
    # renumbers every round: 2026 Washington (M) was rewritten 32/5 → 48/6 hours
    # after its final, which moved "Final" onto a round 6 that has no matches.
    # Nothing could then record the draw as finished, so it silently dropped out
    # of the week's digest and its predictors lost their draw history.
    shape_frozen = dates_frozen or existing.draw_released_direct_at is not None

    # THE SEASON PAGE NAMES A WEEK, NOT A DAY.
    #
    # Its date cell is a rowspan covering every event in the week, so discovery
    # snaps whatever it reads to the Monday (see discovery.add). The one fact it
    # carries is therefore WHICH WEEK the event is in — the day of the week is
    # an artefact of the snapping, not information.
    #
    # The event page's infobox carries the real first day, and
    # _refresh_dates_from_event_page writes it here while a draw is still
    # upcoming. 2026 Chengdu and Hangzhou both start on the WEDNESDAY, moved to
    # work around the Laver Cup; both were seeded 21 September and corrected to
    # the 23rd. Overwriting that with the Monday is not a correction, it is a
    # loss — and because the correction and this sync are both daily jobs, the
    # same correction was made and lost again every day from 16 to 20 September,
    # leaving start_date permanently two days early with a closing_time derived
    # from the date it no longer held.
    #
    # That is not cosmetic. A start_date in the past reads as "active" the
    # moment the draw is released, which LOCKS PICKS — the release that should
    # have opened Chengdu for picking would have closed it, two days early. And
    # every health check that asks "has play started" believed it had: the
    # order-of-play alarms reported both events as under way with no sheet, at
    # 00:12 on 21 September, for tournaments that do not start until the 23rd.
    #
    # The clause above (`first_match_at is not None`) was written for exactly
    # this and cannot reach it: an unreleased draw has never had a first ball
    # observed, which is the whole period in which the event page is the only
    # source there is.
    #
    # So the season page may only move a date to a DIFFERENT WEEK — that is real
    # news, a rescheduled event. Inside the same week the stored date is at
    # least as precise as the guess, and usually more.
    same_week = (
        discovered.start_date is not None
        and existing.start_date is not None
        and tournament_monday(existing.start_date) == tournament_monday(discovered.start_date)
    )
    eff_start = existing.start_date if same_week else discovered.start_date
    # The end date travels with it: both are written in one breath by the event
    # page, so keeping one and taking the other would mix two sources. Falls
    # back to the season page's when nothing has been stored yet.
    eff_end = (existing.end_date if same_week and existing.end_date
               else discovered.end_date)

    fields = [
        ("wiki_page_title", discovered.wiki_page_title),
        ("name", discovered.name),
        ("surface", discovered.surface),
        ("category", discovered.category),
        ("city", discovered.city),
        ("country", discovered.country),
    ]
    if not shape_frozen:
        fields += [
            ("draw_size", discovered.draw_size),
            ("num_rounds", _num_rounds(discovered.draw_size)),
        ]
    # THE TOUR'S OWN DATES ARE NOT WIKIPEDIA'S TO MOVE. A women's draw whose
    # tournament carries a WTA id has its dates kept by wta_season.py from the
    # official season list; Wikipedia's season page may still name, categorise
    # and place it, but its dates stand aside.
    dates_official = await official_dates(db, existing)
    if dates_official:
        eff_start = existing.start_date
    if not dates_frozen and not dates_official:
        fields += [
            ("start_date", eff_start),
            ("week", tennis_week(eff_start, existing.year) if eff_start else None),
            ("end_date", eff_end),
        ]
    for attr, val in fields:
        if val is not None and getattr(existing, attr) != val:
            setattr(existing, attr, val)
            changed = True

    # Recalculate estimated draw release dates using category-specific history.
    # From the date we believe, not the one we just declined to store: a release
    # estimate derived from the week-Monday for a Wednesday-start event is two
    # days early, and release_deadline hangs off it.
    if not dates_frozen and eff_start and discovered.category:
        direct, qual = await calculate_draw_release_dates(
            eff_start, discovered.category, discovered.gender, db=db
        )
        if direct and existing.draw_release_direct != direct:
            existing.draw_release_direct = direct
            changed = True
        if qual != existing.draw_release_qualifiers:
            existing.draw_release_qualifiers = qual
            changed = True

    # Recompute ranking weeks whenever category or start_date may have changed
    if not dates_frozen:
        erw = compute_entry_ranking_week(existing.start_date, existing.category)
        if erw != existing.entry_ranking_week:
            existing.entry_ranking_week = erw
            changed = True

        srw = compute_seed_ranking_week(existing.start_date, existing.category)
        if srw != existing.seed_ranking_week:
            existing.seed_ranking_week = srw
            changed = True

    # Assign variant_id if missing or if draw_size/category just changed
    if existing.variant_id is None:
        vid = await _resolve_variant_id(db, existing.category, existing.draw_size, existing.name)
        if vid:
            existing.variant_id = vid
            changed = True

    return changed


async def create_discovered(db: AsyncSession, d: DiscoveredTournament, year: int,
                            *, scrape_new: bool = False) -> Draw:
    """Create the Draw a discovery describes. Shared by the Wikipedia season
    sync and the WTA's official season list (wta_season.py), so the two cannot
    drift in what a new draw is born with."""
    draw_direct, draw_qualifiers = await calculate_draw_release_dates(
        d.start_date, d.category, d.gender, db=db
    )
    variant_id = await _resolve_variant_id(db, d.category, d.draw_size, d.name)
    t = Draw(
        name=d.name,
        year=year,
        gender=d.gender,
        surface=d.surface,
        category=d.category,
        draw_size=d.draw_size,
        num_rounds=_num_rounds(d.draw_size),
        start_date=d.start_date,
        week=tennis_week(d.start_date, year) if d.start_date else None,
        end_date=d.end_date,
        draw_release_direct=draw_direct,
        draw_release_qualifiers=draw_qualifiers,
        city=d.city,
        country=d.country,
        wiki_page_title=d.wiki_page_title,
        variant_id=variant_id,
        status="upcoming",
    )
    db.add(t)
    await db.flush()
    if scrape_new:
        from app.routers.tournaments import _do_scrape
        await _do_scrape(t, db)
    return t


async def official_dates(db: AsyncSession, draw: Draw) -> bool:
    """Whether the tour's own feed, not Wikipedia, is this draw's date authority.

    True for a women's draw whose tournament carries a WTA liveScoringId: the
    WTA's season list states main-draw dates (measured equal to ours on
    Guadalajara, Seoul, Singapore and Beijing, 2026-09-21) and wta_season.py
    keeps them current. Every Wikipedia date path defers to this.
    """
    if (draw.gender or "").upper() != "F" or not draw.tournament_id:
        return False
    from app.models.tournament import Tournament
    row = await db.get(Tournament, draw.tournament_id)
    return bool(row and row.wta_live_scoring_id)


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

    discovered = await discover_tournaments(year)
    logger.info("Discovered %d tournaments for %d", len(discovered), year)

    updated = inserted = skipped = 0

    for d in discovered:
        existing = await find_existing_match(db, d, year)

        if existing:
            # A guessed title must never replace the title of a record whose
            # page is already resolved — the resolved title is ground truth.
            if d.title_is_guess and existing.wiki_page_id is not None:
                d.wiki_page_title = existing.wiki_page_title
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
                await create_discovered(db, d, year, scrape_new=scrape_new)

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
        from app.services.system_log import app_log
        await app_log(
            "warning", "discovery",
            f"Duplicate tournament records found after sync for {year} — needs manual review",
            {"year": year, "collisions": [str(d) for d in dups]},
            dedup_key=f"sync_duplicates_{year}", dedup_hours=24,
        )

    summary = dict(updated=updated, inserted=inserted, skipped=skipped, duplicates_found=len(dups))
    logger.info("Sync complete for %d: %s", year, summary)
    return summary


async def _find_duplicates(db: AsyncSession, year: int) -> list:
    """
    Detect real duplicate records.

    Three strategies:
    1. Same name + gender: always a duplicate regardless of tier.
    2. Same gender + category + start_date for unique-per-slot tiers (500/1000/GS):
       these tiers have exactly one tournament per slot, so two records = duplicate.
       ATP/WTA 250 are intentionally excluded because multiple run simultaneously.
    3. Same gender + category + start_date + city, for ANY tier (including 500/250).
       Strategy 1 misses duplicates discovered under two different name variants
       for the same real event (e.g. "BMW Open" vs "Munich" — same tournament,
       one named after its sponsor, one after its host city); Strategy 2 misses
       them for 500/250 tiers since multiple such events legitimately run in the
       same week. But two *same-tier* events in the *same city* on the *same
       date* cannot both be real — the tour doesn't schedule that — so a city
       match closes both gaps without flagging legitimate simultaneous events
       in different cities.
    """
    results = []

    # Strategy 1: identical name + gender
    res = await db.execute(
        select(
            Draw.name,
            Draw.gender,
            Draw.category,
            Draw.start_date,
            func.count().label("n"),
        )
        .where(Draw.year == year)
        .group_by(Draw.name, Draw.gender)
        .having(func.count() > 1)
    )
    results.extend(res.all())

    # Strategy 2: same slot in one-per-slot tiers (1000/Grand Slam only)
    # ATP/WTA 500 run two simultaneous events per week so they are intentionally excluded.
    one_per_slot_subq = select(DrawCategory.name).where(DrawCategory.one_per_slot == True)
    res = await db.execute(
        select(
            Draw.category,
            Draw.gender,
            Draw.start_date,
            func.count().label("n"),
        )
        .where(
            Draw.year == year,
            Draw.category.in_(one_per_slot_subq),
            Draw.start_date.isnot(None),
        )
        .group_by(Draw.gender, Draw.category, Draw.start_date)
        .having(func.count() > 1)
    )
    results.extend(res.all())

    # Strategy 3: same gender + category + start_date + city, any tier.
    res = await db.execute(
        select(
            Draw.category,
            Draw.gender,
            Draw.start_date,
            func.count().label("n"),
        )
        .where(
            Draw.year == year,
            Draw.start_date.isnot(None),
            Draw.city.isnot(None),
        )
        .group_by(Draw.gender, Draw.category, Draw.start_date, func.lower(Draw.city))
        .having(func.count() > 1)
    )
    results.extend(res.all())

    return results
