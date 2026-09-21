"""
Tournament Day-1 schedule lookup.

Maps tournament names and venues to their first-match start time on Day 1
of the main draw.  Used to auto-populate closing_time.

Sources: official tournament websites, ATP/WTA schedules, LTA, broadcasters.
Research conducted June 2026.
"""
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

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

    # ── ATP/WTA 250 ──────────────────────────────────────────────────────────
    # Los Cabos (Mifel Open): Baja California Sur runs on America/Mazatlan
    # (UTC-7), NOT the America/Mexico_City default, and play starts in the
    # evening to duck the July heat — ESPN has 2026 day 1 R1 at 01:00Z, i.e.
    # 18:00 local. The country fallback (Mexico City, 11:00) was eight hours
    # early.
    (['los cabos', 'mifel'],                         None, 'America/Mazatlan',    18,  0),
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


def sync_closing_time(tournament) -> bool:
    """
    Re-derive closing_time from the CURRENT start_date, replacing a stale value.

    closing_time is day 1's first ball, so it is a function of start_date — and
    start_date moves. 2026 Cincinnati was seeded with the Monday of its week and
    later corrected to its real Thursday start, but the deadline had already
    been written from the Monday and apply_closing_time() will not touch a value
    that exists. The draw sat open advertising a deadline three days in the past.

    Refuses to move a deadline once play has started: past that point the
    deadline has already done its job, picks are locked on evidence
    (picks_locked_at), and rewriting it could only rewrite history.

    ALSO REFUSES ONCE THE FIRST BALL HAS BEEN OBSERVED. This re-derivation is a
    guess built from start_date and a venue lookup; first_match_at is a
    published order of play. 2026 Guadalajara starts Sunday, Wikipedia's
    calendar says Monday, and the two writers took turns: ESPN set the deadline
    to Sun 12:00, the next scrape put it back to Mon 12:00, ESPN set it again —
    the same "deadline set from the published order of play" line every pass,
    for hours. Evidence outranks the estimate, so the estimate stands aside.

    Returns True if closing_time changed.
    """
    if tournament.picks_locked_at is not None or tournament.status in ("active", "completed"):
        return False
    if tournament.first_match_at is not None:
        return False

    ct = closing_time_utc(
        tournament.start_date,
        tournament.venue_timezone,
        tournament.day1_start_hour,
        tournament.day1_start_minute or 0,
    )
    if ct is None or ct == tournament.closing_time:
        return False

    tournament.closing_time = ct
    return True


def adopt_observed_start_date(tournament) -> bool:
    """Move start_date onto the day the first ball was actually observed.

    start_date comes from Wikipedia's calendar, which is a plan written months
    ahead; first_match_at comes from a published order of play. When they name
    different days the calendar is the one that is wrong, and it is what the
    draw card prints — 2026 Guadalajara advertised "Sep 14 – 19" while its first
    match was seven minutes from starting on the 13th (owner, 2026-09-13).

    Deliberately narrow:

      • one day only. A larger gap is not a tournament that moved its start, it
        is evidence about some other event, and the refiners that write
        first_match_at already refuse those.
      • never once picks are locked or play has begun. Then start_date is
        history, and `week`, the ranking weeks and the release dates hang off it.
      • never when the move would make the draw look already started. Reading a
        start_date as "this began yesterday" shuts picks that should still be
        open — the direction is not the danger, the appearance is
        (feedback_start_date_backwards_locks_picks).

    `week` follows, via tennis_week, which already knows a Sunday start belongs
    to the week ahead — so a Monday→Sunday correction leaves the week alone.

    Returns True if start_date changed.
    """
    from datetime import date as _date

    from app.services.tournament_sync import tennis_week

    if tournament.first_match_at is None or tournament.start_date is None:
        return False
    if tournament.picks_locked_at is not None or tournament.status in ("active", "completed"):
        return False

    hour = tournament.first_match_local_hour
    if hour is None:
        return False
    observed = tournament.first_match_at.date()
    if tournament.venue_timezone:
        try:
            observed = tournament.first_match_at.replace(
                tzinfo=timezone.utc).astimezone(
                    ZoneInfo(tournament.venue_timezone)).date()
        except Exception:
            return False
    if observed == tournament.start_date:
        return False
    if abs((observed - tournament.start_date).days) > 1:
        return False
    if observed < _date.today():
        # Would read as "started yesterday" and shut picks that are still open.
        return False

    tournament.start_date = observed
    week = tennis_week(observed, tournament.year)
    if week is not None:
        tournament.week = week
    return True


def adopt_scheduled_end_date(draw, last_main_day) -> bool:
    """Extend end_date onto the last day the order of play has main-draw play.

    The twin of adopt_observed_start_date, and for the same reason: end_date
    comes from Wikipedia's calendar, a plan written months ahead, while the
    order of play is what the tournament is actually doing. When rain moves a
    final, the sheet says so within the hour and the calendar may never say it
    at all — 2026 SP Open advertised "Sep 15 - 20" with both finals sitting on
    the 21st (owner, 2026-09-21).

    It matters more than the dates a card prints. `computed_status` reads
    end_date to decide a draw is finished, so a postponed final leaves the
    draw reading "completed" with its last match unplayed — and the same
    property is what the standings, the cohorts and the draw list all key off.
    Extending it also un-finishes a draw the scraper called completed early,
    through the `today <= end_date` arm of that property.

    EXTENDS ONLY, NEVER PULLS IN. A day with no sheet is not evidence that
    play has stopped — we may simply not have fetched it — and shrinking the
    range would retire a live tournament. The asymmetry is the point: a
    postponement adds days, and the calendar's date is the floor.

    Bounded to a week past the plan. A row further out than that is not this
    tournament running over; it is evidence about some other event, or a
    misparsed year, and the same reasoning keeps its twin to a single day.

    Main draw only. Qualifying runs before a tournament, so it cannot speak
    to when one ends.

    Returns True if end_date changed.
    """
    if last_main_day is None or draw.end_date is None:
        return False
    if last_main_day <= draw.end_date:
        return False
    if (last_main_day - draw.end_date).days > 7:
        return False
    draw.end_date = last_main_day
    return True


def apply_closing_time(tournament) -> bool:
    """
    Set closing_time on *tournament* from its schedule fields if not already set.
    Returns True if closing_time was written.

    Prefer sync_closing_time() anywhere start_date may have changed; this one
    only ever fills a blank.
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


# ── Learned start times ───────────────────────────────────────────────────────
#
# _LOOKUP above is hand-researched: one guess per venue, correct when it was
# written and silently wrong the year a tournament moves its first ball. Once
# ESPN's order of play has been observed (draws.first_match_at, written by
# espn_monitor._refine_closing_time) there is evidence to prefer instead.
#
# Deliberately narrow about what counts as evidence, in the order it is trusted:
#
#   1. THIS tournament in a previous year. A venue keeps its start time far more
#      reliably than a category shares one, so one prior edition of the same
#      event beats any amount of category data.
#   2. The same category and tour, if enough editions agree. Used only as a
#      fallback for an event never seen before.
#
# There is deliberately no third tier. Below this the curated table is the
# better answer, and a wide average across mixed categories would be worse than
# the guess it replaced — the trap the bracket_first_seen_at comment in
# models/tournament.py records paying for once already.

# How many observed editions a CATEGORY needs before its consensus is trusted.
# One event's quirk should not set the default for a whole tier.
_CATEGORY_MIN_SAMPLES = 3


async def learned_day1_start(db, draw) -> Optional[tuple[int, int, str]]:
    """
    (hour, minute, why) in venue-local time, learned from observed editions.

    Returns None when there is nothing better than the curated table, which is
    the expected answer for a whole season after this ships — no past draw has a
    published order of play left to read, so the record starts empty and fills
    one tournament at a time.
    """
    from sqlalchemy import select
    from app.models.tournament import Draw

    rows = (await db.execute(
        select(Draw.year, Draw.first_match_local_hour, Draw.first_match_local_minute)
        .where(
            Draw.name == draw.name,
            Draw.gender == draw.gender,
            Draw.id != draw.id,
            Draw.first_match_local_hour.isnot(None),
        )
        .order_by(Draw.year.desc())
        .limit(1)
    )).first()
    if rows:
        year, hour, minute = rows
        return hour, minute or 0, f"{draw.name} started at this time in {year}"

    if not draw.category:
        return None
    cat_rows = (await db.execute(
        select(Draw.first_match_local_hour, Draw.first_match_local_minute)
        .where(
            Draw.category == draw.category,
            Draw.gender == draw.gender,
            Draw.id != draw.id,
            Draw.first_match_local_hour.isnot(None),
        )
    )).all()
    if len(cat_rows) < _CATEGORY_MIN_SAMPLES:
        return None

    # The mode, not the mean: start times are a handful of discrete clock values
    # and averaging 11:00 with 13:00 invents a 12:00 nobody plays at.
    from collections import Counter
    common = Counter((h, m or 0) for h, m in cat_rows).most_common(1)[0]
    (hour, minute), hits = common
    return hour, minute, f"{hits} of {len(cat_rows)} {draw.category} draws start at this time"


async def apply_learned_start(db, draw) -> bool:
    """
    Override the curated start hour with an observed one, before the deadline is
    derived from it. Returns True if anything changed.

    Only ever runs ahead of play: past that the deadline has done its job, and
    sync_closing_time refuses to move it anyway.
    """
    if draw.picks_locked_at is not None or draw.status in ("active", "completed"):
        return False
    # Its own observation always wins over anything inferred — once ESPN has
    # published this draw's schedule there is nothing left to estimate.
    if draw.first_match_local_hour is not None:
        if (draw.day1_start_hour, draw.day1_start_minute or 0) == (
            draw.first_match_local_hour, draw.first_match_local_minute or 0
        ):
            return False
        draw.day1_start_hour = draw.first_match_local_hour
        draw.day1_start_minute = draw.first_match_local_minute or 0
        return True

    learned = await learned_day1_start(db, draw)
    if not learned:
        return False
    hour, minute, _why = learned
    if (draw.day1_start_hour, draw.day1_start_minute or 0) == (hour, minute):
        return False
    draw.day1_start_hour = hour
    draw.day1_start_minute = minute
    return True
