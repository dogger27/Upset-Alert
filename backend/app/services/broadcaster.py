"""In-process pub/sub for SSE push to browser clients."""
import asyncio
from collections import defaultdict

_subscribers: dict[int, list[asyncio.Queue]] = defaultdict(list)


def subscribe(tournament_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=10)
    _subscribers[tournament_id].append(q)
    return q


def unsubscribe(tournament_id: int, q: asyncio.Queue) -> None:
    try:
        _subscribers[tournament_id].remove(q)
    except ValueError:
        pass


async def publish(*ids) -> None:
    """Nudge every subscriber on any of these ids.

    VARIADIC BECAUSE THE KEY SPACE IS AMBIGUOUS, and was silently split.
    Subscribers key on whatever id their page happens to hold: the draw page
    passes a DRAW id (the route is /tournaments/:id but that id serialises a
    Draw), while the schedule page passes a TOURNAMENT id. Publishers were
    equally divided — espn_monitor sent draw ids, sofascore_live and the
    results sweep sent tournament ids — so each page heard exactly one of the
    two pollers and neither knew.

    The draw page therefore never saw a Sofascore nudge, which is the ten-second
    point score, and never saw the results sweep record a winner. The schedule
    page never saw ESPN.

    Rather than pick a winner and renumber every publisher — a change that
    fails silently in the same way if one is missed — publishers now pass every
    id that identifies what changed. The event carries no payload; it is a
    nudge, and a client refetches through its normal cached, authorised query.
    So a redundant publish costs one extra refetch at worst, and no page
    subscribes to both ids.
    """
    for tid in {i for i in ids if i is not None}:
        for q in list(_subscribers.get(tid, [])):
            try:
                q.put_nowait("draw_updated")
            except asyncio.QueueFull:
                pass
