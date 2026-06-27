"""Calculate draw release dates and entry ranking weeks based on tournament category."""

from datetime import date, timedelta
from typing import Optional

# Days before the tournament Monday that the entry ranking snapshot is taken.
# Grand Slams use 42 days (6 weeks); all ATP/WTA tour events use 28 days (4 weeks).
ENTRY_DAYS_BEFORE: dict[str, int] = {
    "Grand Slam": 42,
    "ATP 1000":   28,
    "WTA 1000":   28,
    "ATP 500":    28,
    "WTA 500":    28,
    "ATP 250":    28,
    "WTA 250":    28,
}

QUAL_ENTRY_DAYS_BEFORE: dict[str, int] = {
    "Grand Slam": 28,
    "ATP 1000":   21,
    "WTA 1000":   21,
    "ATP 500":    21,
    "WTA 500":    21,
    "ATP 250":    21,
    "WTA 250":    21,
}

# Days before the tournament Monday that seedings are confirmed (post-withdrawal acceptance list).
# Grand Slams use 28 days (4 weeks = qual entry deadline); all tour events use 14 days (2 weeks).
# Use this snapshot when looking up inferred rankings in te_rankings_snapshots.
SEED_DAYS_BEFORE: dict[str, int] = {
    "Grand Slam": 28,
    "ATP 1000":   14,
    "WTA 1000":   14,
    "ATP 500":    14,
    "WTA 500":    14,
    "ATP 250":    14,
    "WTA 250":    14,
}


def _lookup_days(table: dict[str, int], category: Optional[str]) -> Optional[int]:
    """Return days value for category, with loose prefix matching as fallback."""
    if not category:
        return None
    days = table.get(category)
    if days is None:
        for key, val in table.items():
            if key in category or category in key:
                return val
    return days


def _ranking_week(start_date: Optional[date], category: Optional[str], table: dict[str, int]) -> Optional[date]:
    if not start_date:
        return None
    days_before = _lookup_days(table, category)
    if days_before is None:
        return None
    tournament_monday = start_date - timedelta(days=start_date.weekday())
    return tournament_monday - timedelta(days=days_before)


def compute_entry_ranking_week(start_date: date, category: Optional[str]) -> Optional[date]:
    """Monday of the ranking snapshot that determines direct-acceptance cutoff.
    Grand Slams = 42 days before tournament Monday; all others = 28 days."""
    return _ranking_week(start_date, category, ENTRY_DAYS_BEFORE)


def compute_seed_ranking_week(start_date: date, category: Optional[str]) -> Optional[date]:
    """Monday of the ranking snapshot that drives actual seed order within the bracket.
    Grand Slams = 28 days before tournament Monday; all others = 14 days.
    Use this when looking up inferred rankings in te_rankings_snapshots."""
    return _ranking_week(start_date, category, SEED_DAYS_BEFORE)

# Hardcoded fallbacks used when there is insufficient historical data (< MIN_SAMPLES)
_DEFAULTS: dict[str, tuple[int, int]] = {
    # (da_days_before, qual_days_before)
    "Grand Slam":  (3, 3),
    "ATP 1000":    (5, 3),
    "WTA 1000":    (5, 3),
    "ATP 500":     (4, 1),
    "WTA 500":     (2, 1),
    "ATP 250":     (2, 1),
    "WTA 250":     (2, 1),
}

MIN_SAMPLES = 3  # minimum historical entries before we trust the average


def _key(category: Optional[str], gender: Optional[str]) -> str:
    """Normalise category + gender into a lookup key."""
    cat = (category or "").strip()
    # Grand Slam is stored without ATP/WTA prefix — keep it as-is
    if "Grand Slam" in cat or "Slam" in cat:
        return cat
    # Prefix ATP/WTA if not already present
    if gender == "M" and not cat.startswith("ATP"):
        cat = f"ATP {cat.replace('ATP ', '').replace('WTA ', '')}"
    elif gender == "F" and not cat.startswith("WTA"):
        cat = f"WTA {cat.replace('ATP ', '').replace('WTA ', '')}"
    return cat


async def _db_defaults(category: Optional[str], gender: Optional[str], db) -> Optional[tuple[int, int]]:
    """Load default_da_days / default_qual_days from tournament_categories if available."""
    from sqlalchemy import select as sa_select
    from app.models.tournament import TournamentCategory
    key = _key(category, gender)
    row = await db.get(TournamentCategory, key)
    if row and row.default_da_days is not None and row.default_qual_days is not None:
        return row.default_da_days, row.default_qual_days
    return None


def get_defaults(category: Optional[str], gender: Optional[str]) -> tuple[int, int]:
    """Return hardcoded (da_days_before, qual_days_before) for this category/gender."""
    key = _key(category, gender)
    return _DEFAULTS.get(key, (3, 2))


async def calculate_draw_release_dates(
    start_date: Optional[date],
    category: Optional[str],
    gender: Optional[str] = None,
    db=None,
) -> tuple[Optional[date], Optional[date]]:
    """
    Return (direct_acceptance_date, qualifiers_added_date) for a tournament.

    Uses the median of historical da_days_before / qual_days_before values for the
    same category+gender when MIN_SAMPLES or more are available. Falls back to
    hardcoded defaults when there is insufficient history.

    Pass db=None (or omit) to always use the hardcoded defaults — useful in
    contexts where no DB session is available.
    """
    if not start_date or not category:
        return None, None

    da_days, qual_days = get_defaults(category, gender)

    if db is not None:
        db_vals = await _db_defaults(category, gender, db)
        if db_vals:
            da_days, qual_days = db_vals
        from sqlalchemy import select
        from app.models.tournament import Tournament

        # Match on the full "WTA 500" / "ATP 1000" key — never mix across categories
        key = _key(category, gender)

        rows = await db.execute(
            select(
                Tournament.da_days_before,
                Tournament.qual_days_before,
            ).where(
                Tournament.category == key,
                Tournament.da_days_before.isnot(None),
                Tournament.da_days_before > 0,
                Tournament.da_days_before <= 14,   # exclude implausible outliers
            ).order_by(Tournament.da_days_before)
        )
        records = rows.all()

        if len(records) >= MIN_SAMPLES:
            da_vals = sorted(r.da_days_before for r in records)
            da_days = da_vals[len(da_vals) // 2]  # median

            qual_vals = sorted(
                r.qual_days_before for r in records
                if r.qual_days_before is not None and 0 < r.qual_days_before <= 14
            )
            if len(qual_vals) >= MIN_SAMPLES:
                qual_days = qual_vals[len(qual_vals) // 2]

    da_date = start_date - timedelta(days=da_days)
    # Grand Slams place all players (including qualifier slots) in the draw at the
    # same time as direct acceptance — qual date equals DA date.
    if "Grand Slam" in (category or ""):
        return da_date, da_date
    return da_date, start_date - timedelta(days=qual_days)
