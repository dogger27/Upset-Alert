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


async def publish(tournament_id: int) -> None:
    for q in list(_subscribers.get(tournament_id, [])):
        try:
            q.put_nowait("draw_updated")
        except asyncio.QueueFull:
            pass
