#!/usr/bin/env python
"""
Stamp draw_entries.sofa_player_id and report what could not be resolved.

    python -m scripts.resolve_sofascore              # draws with unstamped entries
    python -m scripts.resolve_sofascore --draw 118   # one draw
    python -m scripts.resolve_sofascore --force      # re-resolve stamped entries
    python -m scripts.resolve_sofascore --dry-run    # resolve, then roll back

Run it from backend/ with the app's own environment, so DATABASE_URL points at
whichever database that environment already uses. Read-mostly: the only writes
are the three id columns.

The unresolved list is the output that matters. A name we cannot pin is left
NULL and printed here rather than guessed at, because a wrong id silently
attaches another player's live score to a bracket slot.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

# SQLAlchemy resolves relationship strings against a registry that only
# app.main fully populates; import the model modules before anything that
# touches them or `select(Draw)` fails with "failed to locate a name 'League'".
for _m in ("league", "user", "prediction", "notification", "push", "alert",
           "draw_history", "h2h", "rankings", "setting", "system_log",
           "tournament", "schedule"):
    try:
        __import__(f"app.models.{_m}")
    except ModuleNotFoundError:
        pass

from app.database import AsyncSessionLocal              # noqa: E402
from app.models.tournament import Draw                  # noqa: E402
from app.services import sofascore                      # noqa: E402


def _print(report: dict) -> None:
    head = (f"{report['draw']}  (draw {report['draw_id']})")
    print(f"\n=== {head} ===")
    if report["error"]:
        print(f"  ERROR: {report['error']}")
        return
    print(f"  sofascore field: {report['field_size']} players")
    print(f"  entries: {report['total']}   resolved now: {report['resolved']}"
          f"   already stamped: {report['already']}"
          f"   unresolved: {len(report['unresolved'])}")
    if report["rules"]:
        print("  matched by: " + ", ".join(
            f"{k}={v}" for k, v in sorted(report["rules"].items(),
                                          key=lambda x: -x[1])))
    for u in report["unresolved"]:
        print(f"    UNRESOLVED  {u['name']}  ({u['nationality'] or '??'})"
              f"  — {u['reason']}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draw", type=int, help="resolve a single draw id")
    ap.add_argument("--force", action="store_true",
                    help="re-resolve entries that already carry an id")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve, print, then roll back every write")
    args = ap.parse_args()

    blocked = False
    async with AsyncSessionLocal() as db:
        try:
            if args.draw:
                draw = (await db.execute(
                    select(Draw).where(Draw.id == args.draw))).scalar_one_or_none()
                if draw is None:
                    print(f"no draw with id {args.draw}", file=sys.stderr)
                    return 1
                reports = [await sofascore.resolve_draw(db, draw, force=args.force)]
            else:
                reports = await sofascore.resolve_pending_draws(db, force=args.force)
        except sofascore.SofascoreBlocked as exc:
            # Expected, not exceptional: Sofascore answers 403 both when it does
            # not like the client and when it has had enough of it. Anything
            # already stamped is committed and keeps its ids; re-running later
            # picks up exactly where this stopped.
            print(f"\nSofascore is refusing this host ({exc}).", file=sys.stderr)
            print("Nothing further was requested — retrying now would extend "
                  "the block, not clear it. Wait for the cooldown and re-run.",
                  file=sys.stderr)
            blocked = True
            reports = []

        if args.dry_run:
            await db.rollback()

    if blocked:
        return 2

    if not reports:
        print("nothing to do — every draw with entries is already resolved")
        return 0

    for r in sorted(reports, key=lambda x: x["draw"]):
        _print(r)

    total = sum(r["total"] for r in reports)
    done = sum(r["resolved"] + r["already"] for r in reports)
    stuck = sum(len(r["unresolved"]) for r in reports)
    print(f"\n{'-' * 60}")
    print(f"TOTAL {done}/{total} entries carry a Sofascore id"
          + (f"  ({100 * done / total:.1f}%)" if total else ""))
    if stuck:
        print(f"{stuck} unresolved — listed above; pin them by hand if they matter")
    if args.dry_run:
        print("DRY RUN — all writes rolled back")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
