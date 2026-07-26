#!/usr/bin/env python3
"""
One-off: recompute and save TournamentResult rows for every completed draw,
so the "Highest_Rank" bot's now-backdated predictions (see
backfill_highest_rank_bot.py) are reflected in Draw History.

This is the exact same operation as POST /admin/backfill-draw-history — just
invoked directly here since the bot account has no password to log in with.
Recomputes from scratch (existing rows for each tournament are deleted and
reinserted), so it also folds the bot into every real user's Global rank/
total_participants for those past tournaments — matching how the live
Global standings already treat it. Per-league rows are unaffected (the bot
isn't a member of any private league).

Safe to re-run.

Run in the production container:
  docker cp backend/backfill_draw_history.py app-backend-1:/app/backfill_draw_history.py
  docker exec app-backend-1 python /app/backfill_draw_history.py
"""

import asyncio
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import selectinload

import app.models.draw_history  # noqa: F401
import app.models.h2h  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.rankings  # noqa: F401
import app.models.system_log  # noqa: F401
import app.models.user  # noqa: F401
from app.database import AsyncSessionLocal
from app.models.league import League
from app.models.prediction import UserPrediction
from app.models.tournament import Draw, Match
from app.services.notifications import _persist_tournament_results


async def main() -> None:
    async with AsyncSessionLocal() as db:
        tournaments = (
            await db.execute(select(Draw).where(Draw.status == "completed"))
        ).scalars().all()

        all_leagues = (
            await db.execute(select(League).options(selectinload(League.members)))
        ).scalars().all()

        saved = 0
        for tournament in tournaments:
            completed_matches = (
                await db.execute(
                    select(Match).where(Match.draw_id == tournament.id, Match.status == "completed")
                )
            ).scalars().all()
            if not completed_matches:
                continue

            all_preds = (
                await db.execute(
                    select(UserPrediction).where(
                        UserPrediction.draw_id == tournament.id,
                        UserPrediction.predicted_winner_id.isnot(None),
                    )
                )
            ).scalars().all()
            if not all_preds:
                continue

            preds_by_user: dict = defaultdict(list)
            for p in all_preds:
                preds_by_user[p.user_id].append(p)

            await _persist_tournament_results(
                db, tournament.id, set(preds_by_user.keys()),
                preds_by_user, completed_matches, tournament, all_leagues,
            )
            saved += 1

        print(f"Draw history recomputed for {saved} tournament(s)")


if __name__ == "__main__":
    asyncio.run(main())
