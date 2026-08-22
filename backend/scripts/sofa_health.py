#!/usr/bin/env python3
"""Has Sofascore refused us, and are the pollers still running?

The tripwire for staging, which cannot tell anyone anything itself: it runs with
OUTBOUND_NOTIFICATIONS=false, because its database is a copy of production's and
holds every real address and push subscription. So a 403 opens the thirty-minute
breaker, writes a warning nobody reads, and the only visible symptom is that
live scores quietly stop.

That matters more since the residential proxy was cancelled on 2026-08-22.
Sofascore requests leave from Jupiter's own address now, and the 403 handler's
rotate-to-a-fresh-exit path is a no-op without a proxy — correct, because
retrying into a block from a fixed address is what turns a short block into a
long one, but it means one refusal costs live scoring until it clears. Last time
that was about 25 hours.

Reads only. stdlib only — no venv, no SQLAlchemy — so it runs from cron, from a
shell, or from inside the container without setting anything up.

    python3 backend/scripts/sofa_health.py                 # staging
    python3 backend/scripts/sofa_health.py --db /path/db   # anywhere else

Exit code is the point: 0 healthy, 1 something to look at. That makes it usable
as a cron guard without parsing its output.
"""
import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

STAGING_DB = "/home/paulwiens/upsetalert/staging-data/tennis_fantasy.db"
STAGING_LOG = "/home/paulwiens/upsetalert/staging-logs/backend.log"

# A refusal is worth reporting long after it happened — the breaker is half an
# hour, but "we were blocked overnight" is the thing you want to walk into.
WARN_WINDOW_H = 24

# The doubles sweep runs every 60s and the results sweep every 180s, and both
# log a line whenever they change something. Quiet is normal when nothing is on
# court, so this only complains when a loop has said nothing for long enough
# that a whole day's play could not have passed unnoticed.
SILENT_AFTER_H = 6

_LOG_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}).*?(sofascore\S*)", re.I)


def _now():
    return datetime.now(timezone.utc)


def _parse(ts):
    """A stamp from either source, as an aware datetime, or None."""
    if not ts:
        return None
    try:
        at = datetime.fromisoformat(str(ts).replace("T", " ").strip())
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def refusals(db, hours):
    """Sofascore warnings and errors the app recorded for itself."""
    since = (_now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT created_at, level, category, message FROM system_logs "
            "WHERE category LIKE 'sofa%' AND level IN ('warning', 'error') "
            "AND created_at >= ? ORDER BY created_at DESC", (since,)).fetchall()
    except sqlite3.OperationalError:
        return None            # no system_logs table — say so rather than pass
    finally:
        con.close()
    return [dict(r) for r in rows]


def last_activity(path):
    """When each Sofascore loop last said anything, from the log file."""
    seen = {}
    try:
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                m = _LOG_LINE.search(line)
                if m:
                    seen[m.group(2).rstrip(":")] = m.group(1)
    except OSError:
        return None
    return seen


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=STAGING_DB)
    ap.add_argument("--log", default=STAGING_LOG)
    ap.add_argument("--hours", type=int, default=WARN_WINDOW_H)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    problems = []

    hits = refusals(args.db, args.hours)
    if hits is None:
        problems.append(f"no system_logs table in {args.db}")
        hits = []
    for h in hits:
        problems.append(f"{h['created_at']} {h['level']} {h['category']}: {h['message']}")

    activity = last_activity(args.log) or {}
    if not activity:
        problems.append(f"no Sofascore lines in {args.log}")
    for loop, ts in sorted(activity.items()):
        at = _parse(ts)
        if at and (_now() - at) > timedelta(hours=SILENT_AFTER_H):
            age = (_now() - at).total_seconds() / 3600
            problems.append(f"{loop} silent for {age:.1f}h (last {ts})")

    if args.json:
        print(json.dumps({"ok": not problems, "problems": problems,
                          "last_activity": activity}, indent=2))
    elif problems:
        print("SOFASCORE: something to look at")
        for p in problems:
            print("  -", p)
    else:
        print(f"SOFASCORE: ok — no refusals in {args.hours}h")
        for loop, ts in sorted(activity.items()):
            print(f"  {loop:28} last spoke {ts}")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
