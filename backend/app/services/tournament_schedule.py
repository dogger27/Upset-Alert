"""
Tournament Day-1 schedule lookup.

Maps tournament names and venues to their first-match start time on Day 1
of the main draw.  Used to auto-populate closing_time.

Sources: official tournament websites, ATP/WTA schedules, LTA, broadcasters.
Research conducted June 2026.
"""
from datetime import datetime, timezone
from typing import Optional

# ── Per-tournament lookup ─────────────────────────────────────────────────────
# Each entry: (name_fragments, gender_filter, iana_tz, start_hour, start_minute)
# - name_fragments : list of lowercase substrings — any one match wins
# - gender_filter  : 'M' | 'F' | None (applies to both)
# - iana_tz        : IANA timezone string
# - start_hour     : local hour (0–23)
# - start_minute   : local minute (0–59)
# First matching entry wins; place more specific entries before broader ones.
_LOOKUP: list[tuple[list[str], Optional[str], str, int, int]] = [

    # ── Grand Slams ──────────────────────────────────────────────────────────
    # All four start outer-court play at 11:00 AM local. Confirmed from
    # official sites and broadcaster schedules. Consistent year-to-year.
    (['australian open'],               None, 'Australia/Melbourne', 11,  0),
    (['french open', 'roland garros'],  None, 'Europe/Paris',        11,  0),
    (['wimbledon'],                     None, 'Europe/London',       11,  0),
    (['us open'],                       None, 'America/New_York',    11,  0),

    # ── Masters 1000 ─────────────────────────────────────────────────────────
    (['bnp paribas open', 'indian wells'],           None, 'America/Los_Angeles', 11,  0),
    (['miami open'],                                 None, 'America/New_York',    11,  0),
    (['monte-carlo', 'monte carlo rolex'],           None, 'Europe/Monaco',       11,  0),
    # Madrid: ATP + WTA combined, both 11 AM CEST
    (['madrid open', 'mutua madrid'],                None, 'Europe/Madrid',       11,  0),
    # Rome: WTA starts Tue, ATP starts Wed–Thu; outer courts 11 AM CEST
    (['internazionali', "d'italia"],                 None, 'Europe/Rome',         11,  0),
    (['national bank open', 'canadian open', 'rogers cup'],
                                                     None, 'America/Toronto',     11,  0),
    (['western & southern', 'western and southern', 'cincinnati'],
                                                     None, 'America/New_York',    11,  0),
    # Shanghai: only Masters 1000 with a 12:30 PM start (afternoon heat)
    (['shanghai masters', 'rolex shanghai'],         None, 'Asia/Shanghai',       12, 30),
    (['wuhan open'],                                 None, 'Asia/Shanghai',       11,  0),
    (['china open'],                                 None, 'Asia/Shanghai',       11,  0),  # Beijing WTA 1000
    (['paris masters', 'rolex paris'],               None, 'Europe/Paris',        11,  0),

    # ── ATP/WTA 500 ──────────────────────────────────────────────────────────
    (['abn amro'],                                   None, 'Europe/Amsterdam',    11,  0),
    # Dubai: ATP and WTA run in SEPARATE weeks (WTA Feb 15–21, ATP Feb 23–28).
    # ATP starts at 14:00 to avoid midday heat; WTA at 11:00.
    (['dubai duty free', 'dubai tennis'],            'M',  'Asia/Dubai',          14,  0),
    (['dubai duty free', 'dubai tennis'],            'F',  'Asia/Dubai',          11,  0),
    (['barcelona open', 'conde de godo'],            None, 'Europe/Madrid',       11,  0),
    # Halle: grass, outdoor — 11:30 AM start (confirmed 2025)
    (['terra wortmann', 'halle open'],               None, 'Europe/Berlin',       11, 30),
    # Queen's: outer courts 11 AM, Centre Court noon (use 11 AM for closing time)
    (["queen's club", 'hsbc championships'],         None, 'Europe/London',       11,  0),
    # Hamburg: clay, outdoor — noon start (confirmed 2025)
    (['hamburg open', 'europa-park stadium'],        None, 'Europe/Berlin',       12,  0),
    (['citi dc open', 'mubadala citi', 'citi open'], None, 'America/New_York',    11,  0),
    # Vienna: indoor fall — 13:30 start (confirmed, consistently later than outdoor events)
    (['erste bank open'],                            None, 'Europe/Vienna',       13, 30),
    # Basel: indoor fall — noon start (confirmed 2025)
    (['swiss indoors'],                              None, 'Europe/Zurich',       12,  0),
    (['toray pan pacific', 'pan pacific open'],      None, 'Asia/Tokyo',          11,  0),
    (['eastbourne'],                                 None, 'Europe/London',       11,  0),
    # Additional 500s with standard 11 AM starts
    (['stuttgart open', 'porsche tennis'],           None, 'Europe/Berlin',       11,  0),
    (['lyon open'],                                  None, 'Europe/Paris',        11,  0),
    (['astana open'],                                None, 'Asia/Almaty',         11,  0),
    (['tokyo'],                                      None, 'Asia/Tokyo',          11,  0),  # Japan Women's Open / Toray
    (['memphis open', 'open 13'],                    None, 'America/Chicago',     11,  0),
    (['hong kong open', 'hong kong tennis'],         None, 'Asia/Hong_Kong',      11,  0),
    (['singapore open'],                             None, 'Asia/Singapore',      11,  0),
]

# ── Country → default timezone ────────────────────────────────────────────────
_COUNTRY_TZ: dict[str, str] = {
    'australia':              'Australia/Sydney',
    'france':                 'Europe/Paris',
    'united kingdom':         'Europe/London',
    'great britain':          'Europe/London',
    'uk':                     'Europe/London',
    'united states':          'America/New_York',
    'usa':                    'America/New_York',
    'canada':                 'America/Toronto',
    'germany':                'Europe/Berlin',
    'spain':                  'Europe/Madrid',
    'italy':                  'Europe/Rome',
    'netherlands':            'Europe/Amsterdam',
    'switzerland':            'Europe/Zurich',
    'austria':                'Europe/Vienna',
    'monaco':                 'Europe/Monaco',
    'united arab emirates':   'Asia/Dubai',
    'uae':                    'Asia/Dubai',
    'china':                  'Asia/Shanghai',
    'japan':                  'Asia/Tokyo',
    'argentina':              'America/Argentina/Buenos_Aires',
    'brazil':                 'America/Sao_Paulo',
    'mexico':                 'America/Mexico_City',
    'romania':                'Europe/Bucharest',
    'hungary':                'Europe/Budapest',
    'sweden':                 'Europe/Stockholm',
    'denmark':                'Europe/Copenhagen',
    'finland':                'Europe/Helsinki',
    'norway':                 'Europe/Oslo',
    'poland':                 'Europe/Warsaw',
    'czech republic':         'Europe/Prague',
    'czechia':                'Europe/Prague',
    'slovakia':               'Europe/Bratislava',
    'croatia':                'Europe/Zagreb',
    'serbia':                 'Europe/Belgrade',
    'greece':                 'Europe/Athens',
    'turkey':                 'Europe/Istanbul',
    'russia':                 'Europe/Moscow',
    'kazakhstan':             'Asia/Almaty',
    'india':                  'Asia/Kolkata',
    'south korea':            'Asia/Seoul',
    'korea':                  'Asia/Seoul',
    'taiwan':                 'Asia/Taipei',
    'thailand':               'Asia/Bangkok',
    'new zealand':            'Pacific/Auckland',
    'south africa':           'Africa/Johannesburg',
    'morocco':                'Africa/Casablanca',
    'saudi arabia':           'Asia/Riyadh',
    'qatar':                  'Asia/Qatar',
    'belgium':                'Europe/Brussels',
    'portugal':               'Europe/Lisbon',
    'israel':                 'Asia/Jerusalem',
    'chile':                  'America/Santiago',
    'colombia':               'America/Bogota',
    'peru':                   'America/Lima',
    'ecuador':                'America/Guayaquil',
    'uruguay':                'America/Montevideo',
    'bolivia':                'America/La_Paz',
    'singapore':             'Asia/Singapore',
    'hong kong':             'Asia/Hong_Kong',
    'indonesia':             'Asia/Jakarta',
    'malaysia':              'Asia/Kuala_Lumpur',
    'philippines':           'Asia/Manila',
    'vietnam':               'Asia/Ho_Chi_Minh',
}

# ── City overrides (for cities where country default would be wrong) ──────────
_CITY_TZ: dict[str, str] = {
    'melbourne':      'Australia/Melbourne',
    'sydney':         'Australia/Sydney',
    'brisbane':       'Australia/Brisbane',
    'perth':          'Australia/Perth',
    'adelaide':       'Australia/Adelaide',
    'hobart':         'Australia/Hobart',
    'indian wells':   'America/Los_Angeles',
    'los angeles':    'America/Los_Angeles',
    'san jose':       'America/Los_Angeles',
    'stanford':       'America/Los_Angeles',
    'miami':          'America/New_York',
    'miami gardens':  'America/New_York',
    'new york':       'America/New_York',
    'new haven':      'America/New_York',
    'newport':        'America/New_York',
    'winston-salem':  'America/New_York',
    'washington':     'America/New_York',
    'mason':          'America/New_York',   # Cincinnati is in Mason, OH
    'houston':        'America/Chicago',
    'dallas':         'America/Chicago',
    'chicago':        'America/Chicago',
    'toronto':        'America/Toronto',
    'montreal':       'America/Toronto',
    'vancouver':      'America/Vancouver',
    'auckland':       'Pacific/Auckland',
    'roquebrune':     'Europe/Monaco',
    'cap-martin':     'Europe/Monaco',
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_schedule(
    name: str,
    gender: str,
    city: Optional[str] = None,
    country: Optional[str] = None,
) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """
    Return (venue_timezone, day1_start_hour, day1_start_minute) for a tournament.
    Returns (None, None, None) if the timezone cannot be determined.
    """
    name_lower = name.lower()

    # 1. Named-tournament lookup (gender-specific entries first)
    for fragments, gender_filter, tz, hour, minute in _LOOKUP:
        if gender_filter and gender_filter != gender:
            continue
        if any(frag in name_lower for frag in fragments):
            return tz, hour, minute

    # 2. City-based timezone fallback (default 11:00 AM)
    if city:
        city_lower = city.lower()
        for key, tz in _CITY_TZ.items():
            if key in city_lower:
                return tz, 11, 0

    # 3. Country-based timezone fallback
    if country:
        tz = _COUNTRY_TZ.get(country.lower())
        if tz:
            return tz, 11, 0

    return None, None, None


def closing_time_utc(
    start_date,
    venue_timezone: str,
    day1_start_hour: int,
    day1_start_minute: int = 0,
) -> Optional[datetime]:
    """Convert local Day-1 start time to a UTC-naive datetime for storage."""
    if not start_date or not venue_timezone or day1_start_hour is None:
        return None
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(venue_timezone)
        local_dt = datetime(
            start_date.year,
            start_date.month,
            start_date.day,
            day1_start_hour,
            day1_start_minute,
            0,
            tzinfo=tz,
        )
        return local_dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def apply_schedule(tournament) -> bool:
    """
    Set venue_timezone, day1_start_hour, day1_start_minute on *tournament*
    from the lookup table if not already set.  Returns True if any field changed.
    """
    if tournament.venue_timezone is not None:
        return False

    tz, hour, minute = get_schedule(
        tournament.name,
        tournament.gender,
        tournament.city,
        tournament.country,
    )
    if not tz:
        return False

    tournament.venue_timezone = tz
    tournament.day1_start_hour = hour
    tournament.day1_start_minute = minute
    return True


def apply_closing_time(tournament) -> bool:
    """
    Set closing_time on *tournament* from its schedule fields if not already set.
    Returns True if closing_time was written.
    """
    if tournament.closing_time:
        return False

    ct = closing_time_utc(
        tournament.start_date,
        tournament.venue_timezone,
        tournament.day1_start_hour,
        tournament.day1_start_minute or 0,
    )
    if ct is None:
        return False

    tournament.closing_time = ct
    return True
