"""
Notification dispatch helpers.

Called from the scheduler after each successful tournament scrape, once the
DB session has been committed.  Each function opens its own session so it is
independent of the caller's transaction.
"""

import asyncio
import logging
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models.league import League, LeagueMember
from app.models.notification import NotificationPreference
from app.models.prediction import UserPrediction
from app.models.tournament import Match, Tournament
from app.models.user import User
from app.services.scoring import rank_users, score_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Draw-released notification
# ---------------------------------------------------------------------------

def _draw_pref_key(category: str, gender: str) -> str | None:
    cat = category or ""
    if "Slam" in cat or "Grand" in cat:
        return f"draw_open:Grand Slam:{gender}"
    if cat.startswith("ATP") or cat.startswith("WTA"):
        return f"draw_open:{cat}"
    return None


async def notify_draw_released(
    tournament_id: int,
    category: str,
    gender: str,
    year: int,
    name: str,
) -> None:
    """Email all users opted-in to this tournament's category/gender."""
    from app.services.email import send_draw_notification

    pref_key = _draw_pref_key(category, gender)
    if not pref_key:
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User.email)
            .join(NotificationPreference, NotificationPreference.user_id == User.id)
            .where(
                NotificationPreference.pref_key == pref_key,
                User.email_verified == True,
            )
        )
        emails = [r[0] for r in result.all()]

    if not emails:
        logger.debug("notify_draw_released: no opted-in users for %s", pref_key)
        return

    display_name = f"{year} {name}"
    await send_draw_notification(emails, display_name, tournament_id)
    logger.info("Draw notification sent to %d user(s) for %s", len(emails), display_name)


# ---------------------------------------------------------------------------
# Tournament-completion notification
# ---------------------------------------------------------------------------

async def notify_tournament_complete(
    tournament_id: int,
    name: str,
    year: int,
    category: str,
    num_rounds: int,
    draw_size: int,
) -> None:
    """
    For every participant who opted into 'tournament_end', send ONE email
    showing their final standing in every group (global + all leagues).
    """
    from app.services.email import send_tournament_complete_notification

    async with AsyncSessionLocal() as db:
        tournament = await db.get(Tournament, tournament_id)
        if not tournament:
            return

        # All completed matches (needed for scoring)
        m_res = await db.execute(
            select(Match)
            .options(selectinload(Match.player1), selectinload(Match.player2), selectinload(Match.winner))
            .where(Match.tournament_id == tournament_id, Match.status == "completed")
        )
        completed_matches = m_res.scalars().all()

        total_res = await db.execute(
            select(func.count()).where(
                Match.tournament_id == tournament_id,
                Match.is_bye == False,
            )
        )
        total_matches = total_res.scalar_one()
        if total_matches == 0:
            return

        # All predictions for this tournament
        pred_res = await db.execute(
            select(UserPrediction).where(
                UserPrediction.tournament_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        all_preds = pred_res.scalars().all()

        preds_by_user: dict[int, list] = defaultdict(list)
        for p in all_preds:
            preds_by_user[p.user_id].append(p)

        # Only users with a complete bracket
        eligible = {uid for uid, preds in preds_by_user.items() if len(preds) >= total_matches}
        if not eligible:
            return

        # Users opted into tournament_end who also participated
        opted_res = await db.execute(
            select(NotificationPreference.user_id)
            .join(User, User.id == NotificationPreference.user_id)
            .where(
                NotificationPreference.pref_key == "tournament_end",
                NotificationPreference.user_id.in_(eligible),
                User.email_verified == True,
            )
        )
        to_notify = {r[0] for r in opted_res.all()}
        if not to_notify:
            return

        # Global scores for all eligible users
        global_scores = {
            uid: score_user(uid, preds_by_user[uid], completed_matches, tournament, None)
            for uid in eligible
        }
        global_ranked = rank_users(list(global_scores.values()))
        global_rank_of = {s.user_id: i + 1 for i, s in enumerate(global_ranked)}

        # Per-league scores (only leagues with at least one eligible participant)
        lg_res = await db.execute(
            select(League).options(selectinload(League.members))
        )
        all_leagues = lg_res.scalars().all()

        league_data: dict[int, dict] = {}
        for lg in all_leagues:
            member_ids = {m.user_id for m in lg.members}
            participants = eligible & member_ids
            if len(participants) < 2:  # skip solo leagues — no competition to report
                continue
            lg_scores = {
                uid: score_user(uid, preds_by_user[uid], completed_matches, tournament, None)
                for uid in participants
            }
            lg_ranked = rank_users(list(lg_scores.values()))
            league_data[lg.id] = {
                "name": lg.name,
                "rank_of": {s.user_id: i + 1 for i, s in enumerate(lg_ranked)},
                "total":   len(participants),
                "points":  {s.user_id: s.total_points for s in lg_ranked},
            }

        # Which leagues each user participated in
        user_league_ids: dict[int, list] = defaultdict(list)
        for lg_id, data in league_data.items():
            for uid in data["rank_of"]:
                user_league_ids[uid].append(lg_id)

        # Load user email addresses
        users_res = await db.execute(
            select(User.id, User.email).where(User.id.in_(to_notify))
        )
        user_email = {r[0]: r[1] for r in users_res.all()}

    # Send outside the session (no DB needed)
    for uid in to_notify:
        email = user_email.get(uid)
        if not email:
            continue

        groups = []
        if len(eligible) >= 2:
            groups.append(("Global", global_rank_of[uid], len(eligible), global_scores[uid].total_points))
        for lg_id in sorted(user_league_ids.get(uid, [])):
            data = league_data[lg_id]
            groups.append((
                data["name"],
                data["rank_of"][uid],
                data["total"],
                data["points"][uid],
            ))

        if not groups:
            continue
        try:
            await send_tournament_complete_notification(email, name, year, tournament_id, groups)
            logger.info(
                "Tournament-complete email sent to user %d (%d group(s)) for %d %s",
                uid, len(groups), year, name,
            )
        except Exception as exc:
            logger.warning("Failed to send completion email to user %d: %s", uid, exc)
