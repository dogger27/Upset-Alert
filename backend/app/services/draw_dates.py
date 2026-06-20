"""Calculate draw release dates based on tournament category and gender."""

from datetime import date, timedelta
from typing import Optional


def calculate_draw_release_dates(
    start_date: Optional[date],
    category: Optional[str],
    gender: Optional[str] = None,
) -> tuple[Optional[date], Optional[date]]:
    """
    Calculate expected draw release dates based on tournament category, start date,
    and gender.

    Returns: (direct_acceptance_date, qualifiers_added_date)

    Timeline patterns (days before first match):
    - Grand Slams: Direct 8 days, Qualifiers 3 days before
    - Masters 1000: Direct 5 days, Qualifiers 3 days before
    - ATP 500: Direct 4 days, Qualifiers 1 day before
    - WTA 500: Direct 2 days, Qualifiers 1 day before  (draws released closer to event)
    - 250 level: Direct 2 days, Qualifiers 1 day before
    """
    if not start_date or not category:
        return None, None

    is_wta = gender == "F"

    if "Grand Slam" in category:
        direct_days_before = 8
        qualifiers_days_before = 3
    elif "1000" in category:
        direct_days_before = 5
        qualifiers_days_before = 3
    elif "500" in category:
        # WTA 500 draws released ~2 days before; ATP 500 ~4 days before
        direct_days_before = 2 if is_wta else 4
        qualifiers_days_before = 1
    elif "250" in category:
        direct_days_before = 2
        qualifiers_days_before = 1
    else:
        direct_days_before = 3
        qualifiers_days_before = 2

    direct_acceptance = start_date - timedelta(days=direct_days_before)
    qualifiers_added = start_date - timedelta(days=qualifiers_days_before)

    return direct_acceptance, qualifiers_added
