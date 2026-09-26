"""EVERY REQUEST WE SEND protennislive AND TENNIS EXPLORER, RECORDED (owner,
2026-09-26: "We want to learn metrics about how and when we get blocked, so
that we can get as much data as we are able to.")

Sofascore's ledger (services/sofa_ledger) proved the point: a block can only
be explained from a record of the requests before it. This extends that
record to the other hosts we depend on, in the same format and the same
storage, so the admin's request views read any of them:

  protennislive  the ATP's order-of-play and draw-sheet PDFs. It refuses with
                 429 PER IP, not per file: measured over 2,870 requests from
                 production and staging together (2026-09-24..26), none of
                 2,028 was refused with fewer than 10 requests in the previous
                 ten minutes, and a third to a half were refused above that.
  tennisexplorer rankings, player pages, H2H and draw pages. It has never
                 refused us; this is here so that the day it does, we have the
                 record. It costs one appended line per request and sends
                 nothing of its own.

HOW: `client(...)` is httpx.AsyncClient with a transport that records each
request whose host is one of HOSTS — each redirect hop separately, because
each is a request the host counts. Every fetch site for these hosts builds its
client here, so none can be missed by a caller that forgot to log.

A refusal (403/429) also writes a block snapshot, at most one per source per
hour — protennislive refuses whole sweeps at a time, and one snapshot of the
six hours before says everything the next nine would.

Recording never fails a request: every write is guarded. Nothing here sends a
request of its own (see feedback: measurements must never add third-party
load).
"""
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.services import sofa_ledger

logger = logging.getLogger(__name__)

ROOT = os.environ.get("REQUEST_LEDGER_DIR", "/data/requests")

# One entry per source the admin's request views can show. `window` is the
# limit the source is known to enforce, as (minutes, most requests allowed);
# the view draws the busiest span of that length against it.
SOURCES = {
    "sofascore": {
        "label": "Sofascore",
        "hourly": sofa_ledger.HOURLY_WARN,
        "callers": sofa_ledger.CALLER_WARN,
        "caller_default": sofa_ledger.CALLER_WARN_DEFAULT,
        "window": None,
    },
    "protennislive": {
        "label": "protennislive",
        "hourly": 54,
        "callers": {},
        "caller_default": None,
        "window": (10, 9),
    },
    "tennisexplorer": {
        "label": "Tennis Explorer",
        "hourly": None,
        "callers": {},
        "caller_default": None,
        "window": None,
    },
}

HOSTS = {
    "www.protennislive.com": "protennislive",
    "protennislive.com": "protennislive",
    "www.tennisexplorer.com": "tennisexplorer",
    "tennisexplorer.com": "tennisexplorer",
}

_SNAPSHOT_EVERY = 3600
_last_snapshot: dict = {}

# Frames that are plumbing, not the caller.
_SKIP = ("httpx", "httpcore", "anyio", "asyncio", "contextlib", "h11", "h2",
         __name__)


def dir_for(source: str) -> str:
    if source == "sofascore":
        return sofa_ledger.DIR
    return os.path.join(ROOT, source)


def _caller() -> str:
    """The first frame outside httpx and this module: 'module.function'."""
    try:
        f = sys._getframe(2)
        while f is not None:
            mod = f.f_globals.get("__name__", "")
            if not mod.startswith(_SKIP):
                return f"{mod.rsplit('.', 1)[-1]}.{f.f_code.co_name}"
            f = f.f_back
    except Exception:
        pass
    return "?"


def _refused(source: str, path: str, status) -> None:
    now = time.time()
    if now - _last_snapshot.get(source, 0) < _SNAPSHOT_EVERY:
        return
    _last_snapshot[source] = now
    # Off the event loop: reading six hours of rows back takes ~40 ms, and
    # every other request the server is answering would wait for it.
    try:
        import asyncio
        asyncio.get_running_loop().run_in_executor(
            None, sofa_ledger.snapshot, f"{status} on {path}", dir_for(source))
    except Exception:
        pass


class _LedgerTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport):
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        source = HOSTS.get(request.url.host)
        if source is None:
            return await self._inner.handle_async_request(request)
        caller = _caller()
        path = request.url.raw_path.decode("ascii", "replace")
        t0 = time.perf_counter()
        try:
            resp = await self._inner.handle_async_request(request)
        except Exception as exc:
            sofa_ledger.record(path, "direct", f"error:{type(exc).__name__}",
                               (time.perf_counter() - t0) * 1000,
                               dir_=dir_for(source), caller=caller)
            raise
        try:
            size = int(resp.headers.get("content-length") or 0)
        except ValueError:
            size = 0
        sofa_ledger.record(path, "direct", resp.status_code, (time.perf_counter() - t0) * 1000,
                           size, dir_=dir_for(source), caller=caller)
        if resp.status_code in (403, 429):
            _refused(source, path, resp.status_code)
        return resp

    async def aclose(self) -> None:
        await self._inner.aclose()


def client(**kwargs) -> httpx.AsyncClient:
    """httpx.AsyncClient, recording every request to a host in HOSTS."""
    return httpx.AsyncClient(transport=_LedgerTransport(httpx.AsyncHTTPTransport()), **kwargs)


def view(source: str, minutes: int, recent: int) -> dict:
    """The admin's request view for one source (blocking: run in a thread)."""
    d = dir_for(source)
    cfg = SOURCES[source]
    rows = sofa_ledger._read_since(datetime.now(timezone.utc) - timedelta(minutes=minutes), d)
    bucket = sofa_ledger.bucket_minutes(minutes)
    summary = sofa_ledger.summary(minutes, rows)
    window = cfg["window"]
    if window:
        summary["busiest_window"] = sofa_ledger.busiest_window(rows, window[0])
    return {"source": source, "label": cfg["label"],
            "sources": [{"key": k, "label": v["label"]} for k, v in SOURCES.items()],
            "summary": summary,
            "series": sofa_ledger.series(rows, minutes, bucket),
            "bucket_minutes": bucket,
            "budgets": {"hourly": cfg["hourly"], "callers": cfg["callers"],
                        "caller_default": cfg["caller_default"],
                        "window": {"minutes": window[0], "limit": window[1]} if window else None},
            "last": sofa_ledger.last_outcomes(dir_=d),
            "snapshots": sofa_ledger.snapshots(dir_=d),
            "recent": rows[-max(0, min(recent, 1000)):]}


def prune() -> None:
    for source in SOURCES:
        if source != "sofascore":
            sofa_ledger.prune(dir_for(source))
