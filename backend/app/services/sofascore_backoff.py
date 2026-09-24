"""Remember a failed on-demand Sofascore read, so readers cannot repeat it.

The point list and the match statistics are fetched when someone opens a
match, and re-asked while the popup is open (every 2s while labels are
pending, every 10s on a live match). Their caches held only SUCCESSES: a 404
— an event Sofascore keeps no point list for, common below tour level — or a
5xx left nothing behind, so every open and every poll of that match went to
Sofascore again. Behind the pacing gate that is not a burst, but it is a
steady stream of identical requests for an answer we already have, which is
the shape a scraper ban is made of.

After a failure the same (kind, event) is not asked again until the floor
passes. In process, like the caches it guards (reads must not write).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

# A 404 is an answer: it will not change for a long while, if ever.
NOT_FOUND_FLOOR = timedelta(minutes=30)
# Anything else (5xx, timeout, breaker open) may clear sooner.
ERROR_FLOOR = timedelta(minutes=2)

_FAILED: dict = {}          # (kind, event_id) -> retry-not-before
_MAX = 1024


def note_failure(kind: str, event_id: int, exc: BaseException,
                 now: Optional[datetime] = None) -> None:
    from app.services.sofascore import SofascoreNotFound
    now = now or datetime.now(timezone.utc)
    floor = NOT_FOUND_FLOOR if isinstance(exc, SofascoreNotFound) else ERROR_FLOOR
    if len(_FAILED) >= _MAX:
        _FAILED.pop(next(iter(_FAILED)), None)
    _FAILED[(kind, event_id)] = now + floor


def held_off(kind: str, event_id: int, now: Optional[datetime] = None) -> bool:
    until = _FAILED.get((kind, event_id))
    if until is None:
        return False
    if (now or datetime.now(timezone.utc)) >= until:
        _FAILED.pop((kind, event_id), None)
        return False
    return True
