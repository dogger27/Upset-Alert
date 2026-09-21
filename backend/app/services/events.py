"""WHICH EVENT A DRAW BELONGS TO.

A Tournament row is one real-world event edition, and its draws are that
event's gendered halves — the men's and women's singles of a combined week.
Everything keyed on tournament_id trusts that: the schedule's headings and
their tier stamps, the day payload's tournament list, the `tour` a schedule
row inherits when it carries no draw id, and which draws move together
between Active and Last Week.

IT WAS TRUSTING SOMETHING THAT WAS NOT TRUE. The only thing that ever set
draws.tournament_id was the one-off migration that created the table, and it
grouped on NAME AND YEAR alone:

    UPDATE draws SET tournament_id = (
      SELECT t.id FROM tournaments t
      WHERE t.name = draws.name AND t.year = draws.year LIMIT 1)

Two different tournaments can share a city's name in one year. Four did:
Hong Kong's ATP 250 in January and its WTA 250 in November, Hamburg's in May
and July, Stuttgart's in April and June, Tokyo's in September and October.
Each pair became one row, and the consequences were visible — the January
Hong Kong event reappeared under ACTIVE in September, ten months after its
final, because it shared a row with a November draw (owner, 2026-09-21) —
and invisible: the `tour` backfill in database.py sets a schedule row's tour
only when every draw of its event agrees on a gender, so for those four it
sets nothing, and a row with no tour wears no pink or blue bar.

A NAME AND A YEAR ARE NOT AN EVENT. A WEEK IS. So an event is matched on the
name, the year AND being played at the same time; when no such row exists,
one is created rather than the nearest namesake borrowed.
"""
import logging
from datetime import timedelta
from typing import Optional

from sqlalchemy import select

from app.models.tournament import Draw, Tournament

logger = logging.getLogger(__name__)

# How far apart two draws of ONE event can start. A combined week's halves
# begin on the same day or a day apart; a Slam's can differ by two. Ten days
# is generous enough to absorb a qualifying-week start date and far short of
# the twenty-five that separated the nearest of the four conflated pairs, so
# it neither splits an event nor joins two.
SAME_EVENT_DAYS = 10


def _plays_together(a: Draw, b: Draw) -> bool:
    """Whether two draws are halves of one event, by when they are played."""
    for x, y in ((a.start_date, b.start_date), (a.end_date, b.end_date)):
        if x and y:
            return abs((x - y).days) <= SAME_EVENT_DAYS
    return False        # nothing to compare on: not evidence of togetherness


async def event_for(db, draw: Draw) -> Optional[Tournament]:
    """The Tournament row this draw belongs to, creating it if there is none.

    Returns None only when the draw has no name or year to go on, which no
    real draw reaches — both are NOT NULL columns.

    Never MOVES a draw that already has an event: that is a repair, and it
    belongs in a migration where it can be reviewed, not in a call that runs
    while somebody is adding a tournament.
    """
    if not draw.name or not draw.year:
        return None
    if draw.tournament_id is not None:
        return await db.get(Tournament, draw.tournament_id)

    candidates = (await db.execute(
        select(Tournament).where(Tournament.name == draw.name,
                                 Tournament.year == draw.year))).scalars().all()
    for t in candidates:
        siblings = (await db.execute(
            select(Draw).where(Draw.tournament_id == t.id))).scalars().all()
        # A row with no draws yet is this draw's — nothing about it disagrees.
        if not siblings or any(_plays_together(draw, s) for s in siblings):
            return t

    # A namesake played at another time of year is a different tournament.
    event = Tournament(
        name=draw.name, year=draw.year, city=draw.city,
        country=draw.country, surface=draw.surface,
    )
    db.add(event)
    await db.flush()
    if candidates:
        logger.info(
            "New event row for %s %s (%s): %d namesake row(s) exist but none is "
            "played within %d days of %s",
            draw.year, draw.name, draw.gender, len(candidates),
            SAME_EVENT_DAYS, draw.start_date)
    return event


async def attach(db, draw: Draw) -> Optional[int]:
    """Give a draw its event, and return the id. Safe to call twice."""
    event = await event_for(db, draw)
    if event is None:
        return None
    if draw.tournament_id != event.id:
        draw.tournament_id = event.id
    return event.id


def split_plan(draws: list) -> list[list]:
    """Group one row's draws into the events they actually are.

    Sorted by start date and split wherever consecutive draws are further
    apart than one event can be. Returns one list per event, the first being
    the one that keeps the existing row.

    Pure, so the migration's judgement can be tested without a database.
    """
    dated = sorted([d for d in draws if d.start_date], key=lambda d: d.start_date)
    undated = [d for d in draws if not d.start_date]
    if not dated:
        return [list(draws)] if draws else []
    groups = [[dated[0]]]
    for d in dated[1:]:
        if (d.start_date - groups[-1][-1].start_date) <= timedelta(days=SAME_EVENT_DAYS):
            groups[-1].append(d)
        else:
            groups.append([d])
    # A draw with no dates cannot be placed; it stays with the original row.
    groups[0].extend(undated)
    return groups
