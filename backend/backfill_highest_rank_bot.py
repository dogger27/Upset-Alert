#!/usr/bin/env python3
"""
One-off setup for the "Highest_Rank" baseline user:
  1. Creates the user row (is_bot=True) if it doesn't already exist.
  2. Backdates its picks into every draw since 2026-06-08 (the first draw a
     real user actually competed in — French Open on 2026-05-25 was solo
     dev/testing only), including already-completed draws.

Safe to re-run: sync_draw_picks() upserts, so this just recomputes.

Uses the app's own ORM (not raw sqlite3) so the exact same simulation logic
in app/services/highest_rank_bot.py is reused rather than duplicated.

Run locally (uses backend/tennis_fantasy.db via DATABASE_URL in .env):
  cd backend && python backfill_highest_rank_bot.py

Run in the production container (COPY only ships app/, so this file isn't
already in the image — copy it in first, and to /app/ specifically, not
/tmp/, so Python's sys.path picks up the sibling `app` package):
  docker cp backend/backfill_highest_rank_bot.py app-backend-1:/app/backfill_highest_rank_bot.py
  docker exec app-backend-1 python /app/backfill_highest_rank_bot.py
"""

import asyncio
import secrets
from datetime import date

from sqlalchemy import select

from app.core.security import hash_password
from app.database import AsyncSessionLocal
# Import every model module so SQLAlchemy can resolve all relationship()
# string references when mappers configure on first query (this script never
# imports app.main, which is what normally pulls all of these in together).
import app.models.draw_history  # noqa: F401
import app.models.h2h  # noqa: F401
import app.models.league  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.prediction  # noqa: F401
import app.models.rankings  # noqa: F401
import app.models.system_log  # noqa: F401
from app.models.tournament import Draw
from app.models.user import User
from app.services.highest_rank_bot import HIGHEST_RANK_USERNAME, sync_draw_picks

CUTOFF = date(2026, 6, 8)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == HIGHEST_RANK_USERNAME))
        bot = result.scalar_one_or_none()
        if bot:
            print(f"Bot user already exists: id={bot.id}")
        else:
            bot = User(
                username=HIGHEST_RANK_USERNAME,
                email="highest-rank@upsetalert.ca",
                full_name="Highest Rank",
                display_name="Highest_Rank",
                password_hash=hash_password(secrets.token_urlsafe(32)),
                is_active=True,
                is_admin=False,
                email_verified=True,
                is_bot=True,
            )
            db.add(bot)
            await db.flush()
            print(f"Created bot user: id={bot.id}")

        result = await db.execute(
            select(Draw).where(Draw.start_date.isnot(None), Draw.start_date >= CUTOFF)
        )
        draws = result.scalars().all()
        print(f"Backfilling {len(draws)} draw(s) with start_date >= {CUTOFF}")

        synced = skipped = 0
        for draw in draws:
            if await sync_draw_picks(db, draw, bot.id):
                synced += 1
            else:
                skipped += 1

        await db.commit()
        print(f"Done: synced {synced}, skipped {skipped} (no entries/matches yet)")


if __name__ == "__main__":
    asyncio.run(main())
