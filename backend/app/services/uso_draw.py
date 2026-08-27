"""The US Open's own published draw — the field, when Wikipedia lags.

Wikipedia is our bracket of record, but its draw pages are filled by editors
over hours: the 2026 draws published with 29 (men) and 24 (women) blank RD1
slots while qualifying was still being played, so a third of the first round
read "TBD" on the site the day picks opened. The tournament publishes the
same draw itself, complete, at

    /en_US/scores/feeds/{year}/draws/{MS|WS}.json

with every player named, seeded and coded (Q/LL, WC) — including the
qualifier positions Wikipedia leaves empty until the names are known.

This module fills ONLY what our bracket is missing: an empty side of a first
round match. It never overwrites a slot Wikipedia has filled, never touches
results, and never moves a player who is already placed — Wikipedia stays the
record, and this is the field it has not finished writing down.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from sqlalchemy import select

from app.models.tournament import Draw, DrawEntry, Match
from app.services.uso_feed import BROWSER_HEADERS

logger = logging.getLogger(__name__)

DRAW_FEED = "https://www.usopen.org/en_US/scores/feeds/{year}/draws/{code}.json"
# Their code for the singles event of each tour.
EVENT_CODE = {"M": "MS", "F": "WS"}
# "Q/LL" is one status on the feed because a lucky loser fills a qualifier's
# place; ours are separate. Q is the truthful half — the slot is a qualifying
# position either way, and a wrong LL badge is worse than a right Q one.
ENTRY_STATUS = {"Q/LL": "Q", "Q": "Q", "LL": "LL", "WC": "WC", "PR": "PR", "SE": "SE"}


# The feed names an undetermined slot rather than leaving it blank. Ours is a
# Q entry with an empty name — the rendering convention the bracket already
# uses for a qualifier nobody has won yet ("Qualifier", not clickable) — so
# these become that instead of a player called "Qualifier/Lucky Loser".
_PLACEHOLDER = ("qualifier", "lucky loser", "qualifier/lucky loser", "bye", "tbd")


def _is_placeholder(name: str) -> bool:
    return (name or "").strip().casefold() in _PLACEHOLDER


def _person(team) -> Optional[dict]:
    """The singles player on one side of a feed match, or None if unnamed."""
    if isinstance(team, list):
        team = team[0] if team else None
    if not isinstance(team, dict):
        return None
    first, last = team.get("firstNameA"), team.get("lastNameA")
    if not last:
        return None
    return {
        "name": f"{first} {last}".strip() if first else last,
        "nationality": team.get("nationA") or None,
        "seed": team.get("seed"),
        "entry_type": ENTRY_STATUS.get(team.get("entryStatus") or ""),
    }


async def fetch_first_round(year: int, gender: str) -> dict[int, list]:
    """{match_number: [side_a, side_b]} for round one, from the official feed."""
    code = EVENT_CODE.get(gender)
    if not code:
        return {}
    async with httpx.AsyncClient(timeout=30, headers=BROWSER_HEADERS) as client:
        r = await client.get(DRAW_FEED.format(year=year, code=code))
        r.raise_for_status()
        payload = r.json()
    out: dict[int, list] = {}
    for m in payload.get("matches") or []:
        if str(m.get("roundCode")) != "1":
            continue
        try:
            # 1101..1164 — the low two digits are the match's place in the round.
            number = int(str(m["match_id"])[-2:])
        except (KeyError, ValueError):
            continue
        out[number] = [_person(m.get("team1")), _person(m.get("team2"))]
    return out


async def fill_missing_slots(db, draw: Draw) -> int:
    """Fill empty first-round sides from the official draw. Returns slots filled."""
    try:
        by_number = await fetch_first_round(draw.year, draw.gender)
    except Exception as exc:  # noqa: BLE001 — a lagging feed is not a failure
        logger.warning("US Open draw feed unavailable for draw %s: %s", draw.id, exc)
        return 0
    if not by_number:
        return 0

    matches = (await db.execute(
        select(Match).where(Match.draw_id == draw.id,
                            Match.round_number == 1))).scalars().all()
    entries = (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == draw.id))).scalars().all()
    # Match on the surname-and-initial the feed and the bracket agree on, so a
    # player Wikipedia has already placed elsewhere is reused rather than
    # duplicated under a slightly different rendering.
    by_key = {_key(e.name): e for e in entries if e.name}

    filled = 0
    for m in matches:
        sides = by_number.get(m.match_number)
        if not sides:
            continue
        for idx, attr in ((0, "player1_id"), (1, "player2_id")):
            if getattr(m, attr) is not None:
                continue        # Wikipedia already placed someone here.
            person = sides[idx]
            if not person:
                continue        # The feed has no name either.
            placeholder = _is_placeholder(person["name"])
            # bracket_position is NOT NULL and is the slot itself: two per
            # first-round match, in order. Omitting it aborted the whole fill
            # mid-transaction and left one half of the draw populated.
            position = (m.match_number - 1) * 2 + idx + 1
            entry = None if placeholder else by_key.get(_key(person["name"]))
            if entry is None:
                entry = DrawEntry(
                    draw_id=draw.id,
                    # Empty name + Q is how this bracket says "a qualifier,
                    # not yet known". Each such slot gets its own row: they
                    # are different positions, not one shared player.
                    name="" if placeholder else person["name"],
                    nationality=None if placeholder else person["nationality"],
                    seed=None if placeholder else person["seed"],
                    entry_type="Q" if placeholder else person["entry_type"],
                    bracket_position=position)
                db.add(entry)
                await db.flush()
                if not placeholder:
                    by_key[_key(person["name"])] = entry
            setattr(m, attr, entry.id)
            filled += 1
    return filled


def _key(name: str) -> str:
    """Surname plus first initial, casefolded — the two feeds' common ground."""
    parts = (name or "").replace(".", " ").split()
    if not parts:
        return ""
    return f"{parts[-1]}|{parts[0][:1]}".casefold()
