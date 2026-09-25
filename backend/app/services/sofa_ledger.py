"""EVERY REQUEST WE SEND SOFASCORE, RECORDED (owner, 2026-09-25: "Our site
DEPENDS on us not being blocked. If we get blocked, we need to have an EXACT
log of our requests leading up to that.")

The ban of 2026-09-25 10:07 UTC could only be explained by estimating each
poller's rate from its timer, because nothing recorded the requests
themselves. This does, at the one place every request passes —
sofascore._fetch, which the pacing gate, the proxy fallback and the direct
probe all call:

  THE LEDGER   one JSON line per request, appended the moment it returns, to
               /data/sofa-requests/YYYY-MM-DD.jsonl (the host bind mount, so a
               redeploy keeps it) — time, path, the service and function that
               asked, route, HTTP status, bytes, milliseconds. Kept 30 days.
               A file, not a table: a database write per request would take
               SQLite's single writer from the live poller every few seconds,
               the lock storm this project has already had.

  THE WATCH    `check()` every five minutes: the last hour's total and each
               caller's share against a budget; over it is a warning in the
               alert digest BEFORE Sofascore answers with a ban.

  THE SNAPSHOT on a block, the last six hours of requests are copied to
               /data/sofa-requests/block-<time>.jsonl and summarised in the
               alarm itself — what we sent, who sent it, how fast.

Recording must never be able to fail a request: every write is guarded.
"""
import contextvars
import glob
import json
import logging
import os
import re
import sys
import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DIR = os.environ.get("SOFA_LEDGER_DIR", "/data/sofa-requests")
KEEP_DAYS = 30
SNAPSHOT_HOURS = 6
# The budget, per rolling hour. The live poller alone is ~360 (one request
# every ten seconds); everything else together should be a fraction of that.
HOURLY_WARN = 600
CALLER_WARN = {"sofascore_live": 450}
CALLER_WARN_DEFAULT = 150

# Who asked: set by sofascore._get (async, where the caller's frames are),
# read by _fetch (in a worker thread — asyncio.to_thread copies the context).
CALLER: contextvars.ContextVar = contextvars.ContextVar("sofa_caller", default="?")

_recent: deque = deque(maxlen=20000)
_lock = threading.Lock()
_NUM = re.compile(r"\d+")


def caller_of() -> str:
    """The first frame outside the Sofascore client: 'module.function'."""
    try:
        f = sys._getframe(2)
        while f is not None:
            mod = f.f_globals.get("__name__", "")
            if mod not in ("app.services.sofascore", __name__) and not mod.startswith("asyncio"):
                return f"{mod.rsplit('.', 1)[-1]}.{f.f_code.co_name}"
            f = f.f_back
    except Exception:
        pass
    return "?"


def shape(path: str) -> str:
    """"/event/17149658/statistics" -> "/event/N/statistics": the kind of request."""
    return _NUM.sub("N", (path or "").split("?")[0])


def record(path: str, route: str, status, ms: float, size: int = 0) -> None:
    """One request, as it came back. Called from _fetch's worker thread."""
    now = datetime.now(timezone.utc)
    row = {"t": now.isoformat(timespec="milliseconds"), "path": path,
           "caller": CALLER.get(), "route": route, "status": status,
           "ms": round(ms), "bytes": size}
    try:
        with _lock:
            _recent.append(row)
            os.makedirs(DIR, exist_ok=True)
            with open(os.path.join(DIR, f"{now:%Y-%m-%d}.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
    except Exception:
        pass


def _read_since(since: datetime) -> list:
    """Every row from `since`, from the files — the deque is lost on restart."""
    rows = []
    day = since.date()
    today = datetime.now(timezone.utc).date()
    while day <= today:
        p = os.path.join(DIR, f"{day:%Y-%m-%d}.jsonl")
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("t", "") >= since.isoformat(timespec="milliseconds"):
                        rows.append(r)
        except OSError:
            pass
        day += timedelta(days=1)
    return rows


def summary(minutes: int = 60, rows: Optional[list] = None) -> dict:
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    rows = rows if rows is not None else _read_since(since)
    by_caller = Counter(r.get("caller", "?") for r in rows)
    by_shape = Counter(shape(r.get("path", "")) for r in rows)
    by_status = Counter(str(r.get("status")) for r in rows)
    per_min = Counter(r.get("t", "")[:16] for r in rows)
    return {
        "minutes": minutes, "requests": len(rows),
        "per_hour": round(len(rows) * 60 / max(1, minutes)),
        "busiest_minute": max(per_min.values()) if per_min else 0,
        "by_caller": dict(by_caller.most_common()),
        "by_path": dict(by_shape.most_common(20)),
        "by_status": dict(by_status),
        "routes": dict(Counter(r.get("route") for r in rows)),
    }


def snapshot(reason: str) -> Optional[str]:
    """On a block: the last SNAPSHOT_HOURS of requests, copied beside the
    ledger. Returns the file's path, or None if it could not be written."""
    since = datetime.now(timezone.utc) - timedelta(hours=SNAPSHOT_HOURS)
    rows = _read_since(since)
    name = f"block-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"
    path = os.path.join(DIR, name)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"reason": reason, "summary_1h": summary(60, [r for r in rows if r["t"] >= (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="milliseconds")]),
                                 "summary_6h": summary(SNAPSHOT_HOURS * 60, rows)}) + "\n")
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        return path
    except Exception:
        return None


async def check() -> dict:
    """The five-minute watch: warn before the budget is spent, and prune."""
    from app.services.system_log import app_log
    s = summary(60)
    over = []
    if s["requests"] > HOURLY_WARN:
        over.append(f"{s['requests']} requests in the last hour (budget {HOURLY_WARN})")
    for caller, n in s["by_caller"].items():
        svc = caller.split(".", 1)[0]
        limit = CALLER_WARN.get(svc, CALLER_WARN_DEFAULT)
        if n > limit:
            over.append(f"{caller}: {n}/h (budget {limit})")
    if over:
        await app_log("warning", "sofascore",
                      "Sofascore request rate over budget — " + "; ".join(over[:3]),
                      s, dedup_key="sofa_ledger_budget", dedup_hours=1)
    # Prune: the ledger keeps KEEP_DAYS, block snapshots are kept for good.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).date()
    for p in glob.glob(os.path.join(DIR, "????-??-??.jsonl")):
        try:
            if datetime.strptime(os.path.basename(p)[:10], "%Y-%m-%d").date() < cutoff:
                os.remove(p)
        except (OSError, ValueError):
            pass
    return s


def timed() -> float:
    return time.perf_counter()
