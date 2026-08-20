"""
Server-sent events — the missing half of broadcaster.py.

`espn_monitor` and `sofascore_live` have both been calling
`broadcaster.publish()` for a long time, and nothing was listening: there was no
route, and no EventSource in the client. The publishes went into queues nobody
read.

That is why a live score took up to two minutes to appear. The draw page polls
every 120s and the schedule page has no interval at all — it only refetches when
you open it or return to the tab. For a set score that is merely slow; for the
POINT score, which changes every few seconds, it makes the whole feature
pointless. A 40-15 delivered two minutes late is worse than showing nothing,
which is the reasoning the server-side freshness guard is built on.

WHY SSE RATHER THAN FASTER POLLING. One held connection per viewer against a
request every ten seconds per open tab, and updates land within a second of the
score changing instead of on the next tick. EventSource also reconnects on its
own, which a polling loop has to be taught.

WHAT IT DELIBERATELY DOES NOT DO: send the data. The event is a bare nudge and
the client refetches through its normal query. Pushing score payloads down this
channel would mean two ways for a client to learn a score, which is two things
to keep consistent — and the refetch is cheap because it is already written,
already cached and already authorised.
"""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.services import broadcaster

router = APIRouter(tags=["stream"])

# Something has to cross the wire regularly or an idle connection is closed by
# the proxy in front of us. Cloudflare gives roughly 100 seconds of silence, so
# a comment every 25 keeps it open with a wide margin. ":" lines are SSE
# comments — the browser ignores them and they never reach an event handler.
_HEARTBEAT_SECONDS = 25


@router.get("/stream/{tournament_id}")
async def stream(tournament_id: int, request: Request):
    """Nudge this client whenever anything about a tournament changes."""

    async def events():
        q = broadcaster.subscribe(tournament_id)
        try:
            # Announce immediately. Without this the browser cannot distinguish
            # "connected and quiet" from "connecting", and neither can a proxy
            # deciding whether to buffer.
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=_HEARTBEAT_SECONDS)
                    yield f"event: {msg}\ndata: 1\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            # Always, or a queue is left attached to a tournament for the life
            # of the process and publish() keeps filling it.
            broadcaster.unsubscribe(tournament_id, q)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # nginx and several proxies buffer a response until it completes,
            # which for a stream is never. This is the documented opt-out and is
            # honoured by more than nginx.
            "X-Accel-Buffering": "no",
        },
    )
