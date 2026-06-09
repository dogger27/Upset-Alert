"""Calculate draw release dates based on tournament category."""

from datetime import date, timedelta
from typing import Optional


def calculate_draw_release_dates(
    start_date: Optional[date], category: Optional[str]
) -> tuple[Optional[date], Optional[date]]:
    """
    Calculate expected draw release dates based on tournament category and start date.

    Returns: (direct_acceptance_date, qualifiers_added_date)

    Timeline patterns (days before first match):
    - Grand Slams: Direct 7-10 days, Qualifiers 5-7 days before
    - Masters 1000: Direct 5-6 days, Qualifiers 3-4 days before
    - 500 level: Direct 4-5 days, Qualifiers 2-3 days before
    - 250 level: Direct 2-3 days, Qualifiers 1-2 days before
    """
    if not start_date or not category:
        return None, None

    if "Grand Slam" in category:
        direct_days_before = 8
        qualifiers_days_before = 6
    elif "1000" in category:
        direct_days_before = 5
        qualifiers_days_before = 3
    elif "500" in category:
        direct_days_before = 4
        qualifiers_days_before = 2
    elif "250" in category:
        direct_days_before = 2
        qualifiers_days_before = 1
    else:
        # Default for unknown categories
        direct_days_before = 3
        qualifiers_days_before = 2

    direct_acceptance = start_date - timedelta(days=direct_days_before)
    qualifiers_added = start_date - timedelta(days=qualifiers_days_before)

    return direct_acceptance, qualifiers_added
