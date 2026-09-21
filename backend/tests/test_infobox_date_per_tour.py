"""A combined event's infobox names a date range per tour.

2026 China Open reads

    | date=30 September – 11 October (WTA)<br> 30 September – 6 October (ATP)

— the WTA 1000 runs twelve days in Beijing and the ATP 500 seven. The parser
knew "(men)" and "(women)" only, so the men's draw matched nothing, fell
through to the first parseable line, and took the women's end date: an ATP
500 apparently running twelve days (owner, 2026-09-21).
"""
from datetime import date

import pytest

from app.services.scraper import _parse_infobox_date

CHINA_OPEN = (
    "{{Infobox tennis tournament\n"
    "| date=30 September – 11 October (WTA)<br> 30 September – 6 October (ATP)\n"
    "| edition=25th (ATP) / 27th (WTA)\n"
    "}}\n"
)

WORDED = (
    "{{Infobox tennis tournament\n"
    "| date=17–23 May (men)<br>20–26 July (women)\n"
    "}}\n"
)

POSSESSIVE = (
    "{{Infobox tennis tournament\n"
    "| date=1–7 June (men's)<br>8–14 June (women's)\n"
    "}}\n"
)

ONE_RANGE = "{{Infobox tennis tournament\n| date=30 September – 6 October\n}}\n"

BOTH_TOURS = (
    "{{Infobox tennis tournament\n"
    "| date=25 September – 2 October (ATP and WTA)\n"
    "}}\n"
)


def test_the_tours_own_names_qualify_a_range():
    assert _parse_infobox_date(CHINA_OPEN, 2026, "M") == (date(2026, 9, 30), date(2026, 10, 6))
    assert _parse_infobox_date(CHINA_OPEN, 2026, "F") == (date(2026, 9, 30), date(2026, 10, 11))


def test_the_worded_form_still_works():
    assert _parse_infobox_date(WORDED, 2026, "M") == (date(2026, 5, 17), date(2026, 5, 23))
    assert _parse_infobox_date(WORDED, 2026, "F") == (date(2026, 7, 20), date(2026, 7, 26))


def test_and_the_possessive_form():
    assert _parse_infobox_date(POSSESSIVE, 2026, "M") == (date(2026, 6, 1), date(2026, 6, 7))
    assert _parse_infobox_date(POSSESSIVE, 2026, "F") == (date(2026, 6, 8), date(2026, 6, 14))


@pytest.mark.parametrize("gender", ["M", "F", ""])
def test_one_unqualified_range_serves_every_draw(gender):
    assert _parse_infobox_date(ONE_RANGE, 2026, gender) == (date(2026, 9, 30), date(2026, 10, 6))


@pytest.mark.parametrize("gender", ["M", "F"])
def test_a_range_naming_both_tours_serves_both(gender):
    """One range for both is one range for both — not a reason to fall through."""
    assert _parse_infobox_date(BOTH_TOURS, 2026, gender) == (date(2026, 9, 25), date(2026, 10, 2))


def test_no_date_field_says_so():
    assert _parse_infobox_date("{{Infobox tennis tournament\n| surface=Hard\n}}", 2026, "M") == (None, None)
