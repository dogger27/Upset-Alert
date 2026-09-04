"""Give every already-finished match its Sofascore event id.

The id is stamped going forward by the live poller and by the results sweep,
but a match that finished before the column existed has none — and without it
there is nothing to read the point-by-point feed by, so its scrubber can never
name a point.

Runs the ORDINARY sweep with its "everything here is already resolved" guard
lifted, so the matching logic is the sweep's own and cannot drift from it.
Read-mostly: the sweep only writes fields that differ.

    docker compose exec -T backend python -m scripts.backfill_sofa_event_ids
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")


async def main() -> None:
    from sqlalchemy import func, select

    from app.database import AsyncSessionLocal
    from app.models.tournament import Match
    from app.services.sofascore_results import sweep_once

    async def counts(db):
        total = (await db.execute(select(func.count()).select_from(Match).where(
            Match.is_bye == False))).scalar_one()                  # noqa: E712
        have = (await db.execute(select(func.count()).select_from(Match).where(
            Match.sofa_event_id.isnot(None)))).scalar_one()
        return total, have

    # THE ROUTE THE APP IS ACTUALLY ON. A fresh process defaults to the
    # residential proxy, and this one is a fresh process: without this every
    # request dies at the proxy with "402 CONNECT tunnel failed" and the
    # backfill silently does nothing. The running app loads the same setting
    # at startup (scheduler._load_sofa_egress).
    from app.services.sofascore import load_egress

    async with AsyncSessionLocal() as db:
        direct = await load_egress(db)
    print("egress:", "direct" if direct else "residential proxy")

    async with AsyncSessionLocal() as db:
        total, before = await counts(db)
        print(f"before: {before} of {total} playable matches carry an event id")

    async with AsyncSessionLocal() as db:
        result = await sweep_once(db, force=True)
        print("sweep:", result)

    async with AsyncSessionLocal() as db:
        total, after = await counts(db)
        print(f"after:  {after} of {total} (+{after - before})")


if __name__ == "__main__":
    asyncio.run(main())
