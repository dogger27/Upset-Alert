"""
Notification dispatch helpers.

Called from the scheduler after each successful tournament scrape, once the
DB session has been committed.  Each function opens its own session so it is
independent of the caller's transaction.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.security import create_unsubscribe_token
from app.database import AsyncSessionLocal
from app.services.email import API_BASE
from app.models.league import League, LeagueMember
from app.models.notification import NotificationPreference
from app.models.prediction import UserPrediction
from app.models.tournament import Match, Draw
from app.models.user import User
from app.services.scoring import rank_users, score_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Round-complete notification
# ---------------------------------------------------------------------------

def _email_round_label(round_name: str) -> str:
    """Email-specific round label: R128/R64/R32/R16, Quarter-Finals, Semi-Finals, Final."""
    mapping = {
        "Final": "Final",
        "Semifinals": "Semi-Finals",
        "Quarterfinals": "Quarter-Finals",
    }
    if round_name in mapping:
        return mapping[round_name]
    if round_name.startswith("Round of "):
        return "R" + round_name[len("Round of "):]
    return round_name


async def notify_round_complete(
    tournament_id: int,
    round_number: int,
    only_user_ids: Optional[set] = None,
    force: bool = False,
) -> None:
    """
    For every participant who opted into 'round_standings', send ONE email
    showing their standing after this round in every qualifying group.
    Groups / global with fewer than 2 participants are excluded.
    """
    from sqlalchemy.exc import IntegrityError
    from app.services.email import send_round_complete_notification
    from app.services.system_log import app_log
    from app.models.notification import RoundCompleteNotification

    async with AsyncSessionLocal() as db:
        tournament = await db.get(Draw, tournament_id)
        if not tournament:
            return

        already_sent = None if force else await db.scalar(
            select(RoundCompleteNotification.id).where(
                RoundCompleteNotification.draw_id == tournament_id,
                RoundCompleteNotification.round_number == round_number,
            )
        )
        if already_sent:
            await app_log(
                "warning", "notifications",
                f"Round-complete email for round {round_number} of draw {tournament_id} "
                f"already sent — resend blocked",
                {"draw_id": tournament_id, "round_number": round_number},
                dedup_key=f"round-complete-dupe-{tournament_id}-{round_number}",
            )
            return

        round_name = _email_round_label(tournament.round_name(round_number))
        is_final_round = round_number == tournament.num_rounds
        t_name = tournament.name
        t_year = tournament.year
        m_res = await db.execute(
            select(Match)
            .options(selectinload(Match.player1), selectinload(Match.player2), selectinload(Match.winner))
            .where(Match.draw_id == tournament_id, Match.status == "completed")
        )
        completed_matches = m_res.scalars().all()

        # Total non-bye matches in the draw
        total_res = await db.execute(
            select(func.count()).where(
                Match.draw_id == tournament_id,
                Match.is_bye == False,
            )
        )
        total_matches = total_res.scalar_one()
        if total_matches == 0:
            return

        # Predictions
        pred_res = await db.execute(
            select(UserPrediction).where(
                UserPrediction.draw_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        all_preds = pred_res.scalars().all()

        preds_by_user: dict[int, list] = defaultdict(list)
        for p in all_preds:
            preds_by_user[p.user_id].append(p)

        eligible = {uid for uid, preds in preds_by_user.items() if len(preds) >= total_matches}
        if not eligible:
            return

        # Users opted into round_standings who participated.
        # For the final round: exclude users who also have tournament_end enabled —
        # they'll get the tournament-completion email and don't need a duplicate.
        round_prefs_res = await db.execute(
            select(NotificationPreference.user_id)
            .join(User, User.id == NotificationPreference.user_id)
            .where(
                NotificationPreference.pref_key == "round_standings",
                NotificationPreference.user_id.in_(eligible),
                User.email_verified == True,
            )
        )
        round_pref_ids = {r[0] for r in round_prefs_res.all()}

        if only_user_ids is not None:
            # Forced/test send: target these users directly (must still be eligible so
            # they appear in the standings), ignoring opt-in / verified filters.
            to_notify = eligible & only_user_ids
        elif is_final_round:
            # Find who has tournament_end; subtract them — they'll get the completion email
            end_pref_res = await db.execute(
                select(NotificationPreference.user_id)
                .where(
                    NotificationPreference.pref_key == "tournament_end",
                    NotificationPreference.user_id.in_(round_pref_ids),
                )
            )
            has_end_pref = {r[0] for r in end_pref_res.all()}
            to_notify = round_pref_ids - has_end_pref
        else:
            to_notify = round_pref_ids
        if not to_notify:
            return

        # Claim this (draw, round) before doing any more work / sending anything.
        # The unique constraint catches a concurrent duplicate trigger; the
        # already_sent check above catches one that arrives later (e.g. next day).
        # A forced/test send does not claim, so it can't block the real batch.
        if not force:
            db.add(RoundCompleteNotification(
                draw_id=tournament_id, round_number=round_number, recipient_count=len(to_notify),
            ))
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                await app_log(
                    "warning", "notifications",
                    f"Round-complete email for round {round_number} of draw {tournament_id} "
                    f"already sent — resend blocked (race)",
                    {"draw_id": tournament_id, "round_number": round_number},
                    dedup_key=f"round-complete-dupe-{tournament_id}-{round_number}",
                )
                return
        logger.info(
            "Round-complete email batch claimed for draw %d round %d (%s) — %d recipient(s)",
            tournament_id, round_number, round_name, len(to_notify),
        )

        # Global scores
        global_scores = {
            uid: score_user(uid, preds_by_user[uid], completed_matches, tournament, None)
            for uid in eligible
        }
        global_ranked = rank_users(list(global_scores.values()), tournament.num_rounds)

        # Per-league scores (≥2 participants only)
        lg_res = await db.execute(
            select(League).options(selectinload(League.members))
        )
        all_leagues = lg_res.scalars().all()

        league_data: dict[int, dict] = {}
        for lg in all_leagues:
            member_ids = {m.user_id for m in lg.members}
            participants = eligible & member_ids
            if len(participants) < 2:
                continue
            lg_scores = {
                uid: score_user(uid, preds_by_user[uid], completed_matches, tournament, None)
                for uid in participants
            }
            lg_ranked = rank_users(list(lg_scores.values()), tournament.num_rounds)
            league_data[lg.id] = {
                "name":   lg.name,
                "ranked": lg_ranked,  # rank-ordered UserScore list
                "member_ids": {s.user_id for s in lg_ranked},
            }

        user_league_ids: dict[int, list] = defaultdict(list)
        for lg_id, data in league_data.items():
            for uid in data["member_ids"]:
                user_league_ids[uid].append(lg_id)

        users_res = await db.execute(
            select(User.id, User.email, User.username).where(User.id.in_(eligible))
        )
        user_info = {r[0]: {"email": r[1], "username": r[2]} for r in users_res.all()}

    def _row_of(ranked: list, idx: int, me: int) -> tuple:
        s = ranked[idx]
        return (idx + 1, user_info.get(s.user_id, {}).get("username", "—"), s.total_points, s.user_id == me)

    def _display_plan(n: int, me_idx: int, target: int) -> list:
        """Ordered display of exactly `target` rows from an n-item ranked list,
        anchoring the rank leaders (top) and trailers (bottom) and always keeping
        the recipient (me_idx). `None` entries are ellipsis/gap rows. Assumes n > target."""
        def build(h: int, t: int) -> list:
            shown = sorted(set(range(0, min(h, n))) | set(range(max(0, n - t), n)) | {me_idx})
            out, prev = [], None
            for idx in shown:
                if prev is not None and idx != prev + 1:
                    out.append(None)  # gap
                out.append(idx)
                prev = idx
            return out
        best = None
        for h in range(1, target + 1):
            for t in range(1, target + 1):
                plan = build(h, t)
                if len(plan) != target:
                    continue
                content = sum(1 for x in plan if x is not None)
                # Center the recipient: prefer a balanced top/bottom split, then more
                # real rows, then a fuller head.
                score = (-abs(h - t), content, h)
                if best is None or score > best[0]:
                    best = (score, plan)
        if best:
            return best[1]
        # Defensive fallback: top rows + recipient, trimmed to `target`.
        plan = build(target, 0)
        if me_idx not in [x for x in plan if x is not None]:
            plan = plan[: target - 1] + [me_idx]
        return plan[:target]

    def _standings_rows(ranked: list, me: int, limit: Optional[int] = None) -> list[tuple]:
        """Competitor list for a group as (rank, username, score, is_you).
        When `limit` truncates, gap rows are (None, '…', None, False)."""
        if limit is None or len(ranked) <= limit:
            return [_row_of(ranked, i, me) for i in range(len(ranked))]
        me_idx = next((i for i, s in enumerate(ranked) if s.user_id == me), 0)
        rows = []
        for idx in _display_plan(len(ranked), me_idx, limit):
            rows.append((None, "…", None, False) if idx is None else _row_of(ranked, idx, me))
        return rows

    for uid in to_notify:
        email = user_info.get(uid, {}).get("email")
        if not email:
            continue

        leagues = []
        my_league_ids = sorted(user_league_ids.get(uid, []))
        if len(eligible) >= 2:
            # Global truncates to the largest league this user is in, but only once
            # Global has ≥10 people; otherwise it's shown in full.
            largest = max((len(league_data[lg_id]["ranked"]) for lg_id in my_league_ids), default=None)
            g_limit = largest if (len(global_ranked) >= 10 and largest is not None) else None
            leagues.append(("Global", _standings_rows(global_ranked, uid, g_limit)))
        for lg_id in my_league_ids:
            data = league_data[lg_id]
            leagues.append((data["name"], _standings_rows(data["ranked"], uid)))

        if not leagues:
            continue
        unsubscribe_url = (
            f"{API_BASE}/unsubscribe?token="
            f"{create_unsubscribe_token(uid, 'round_standings')}"
        )
        try:
            await send_round_complete_notification(
                email, t_name, t_year, tournament_id, round_name, leagues,
                category=tournament.category or "", gender=tournament.gender or "M",
                unsubscribe_url=unsubscribe_url,
            )
            logger.info(
                "Round-complete email sent to user %d (%d group(s)) — %d %s %s",
                uid, len(leagues), t_year, t_name, round_name,
            )
        except Exception as exc:
            logger.warning("Failed to send round-complete email to user %d: %s", uid, exc)


# ---------------------------------------------------------------------------
# Match-start notification
# ---------------------------------------------------------------------------

async def notify_match_start(tournament_id: int, name: str, year: int, category: str = "", gender: str = "M") -> None:
    """Email all users opted-in to 'match_start' for this tournament."""
    from app.services.email import send_match_start_notification
    from app.services.system_log import app_log

    async with AsyncSessionLocal() as db:
        total_res = await db.execute(
            select(func.count()).where(Match.draw_id == tournament_id, Match.is_bye == False)
        )
        total_matches = total_res.scalar_one()

        competing_subq = (
            select(UserPrediction.user_id)
            .where(
                UserPrediction.draw_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
            .group_by(UserPrediction.user_id)
            .having(func.count() >= total_matches)
        )

        result = await db.execute(
            select(User.email)
            .join(NotificationPreference, NotificationPreference.user_id == User.id)
            .where(
                NotificationPreference.pref_key == "match_start",
                User.email_verified == True,
                User.id.in_(competing_subq),
            )
        )
        emails = [r[0] for r in result.all()]

    if not emails:
        logger.debug("notify_match_start: no opted-in users for tournament %d", tournament_id)
        return

    await send_match_start_notification(emails, name, year, tournament_id, category=category, gender=gender)
    await app_log("info", "notifications",
                  f"Match-start email sent to {len(emails)} user(s) for {year} {name}",
                  {"tournament_id": tournament_id, "recipient_count": len(emails)})


# ---------------------------------------------------------------------------
# Draw-released notification
# ---------------------------------------------------------------------------

def _draw_pref_key(category: str, gender: str) -> Optional[str]:
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
    """
    Email all users opted-in to this tournament's category/gender.

    Callers are expected to have already established (and persisted) that this
    is the ONE time this notification should fire for this draw — see
    draw_release_notified_at / _notify_pending_draw_releases in scheduler.py.
    This function itself does not check or set that flag.
    """
    from app.services.email import send_draw_notification
    from app.services.system_log import app_log

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

    await send_draw_notification(emails, name, tournament_id, category=category, gender=gender)
    await app_log("info", "notifications",
                  f"Draw-released email sent to {len(emails)} user(s) for {year} {name}",
                  {"tournament_id": tournament_id, "recipient_count": len(emails),
                   "category": category, "gender": gender})


# ---------------------------------------------------------------------------
# Tournament results persistence
# ---------------------------------------------------------------------------

async def _persist_tournament_results(
    db,
    tournament_id: int,
    all_participants: set,
    preds_by_user: dict,
    completed_matches: list,
    tournament,
    all_leagues: list,
) -> None:
    """Upsert TournamentResult rows for every participant in every group."""
    from datetime import datetime, timezone as tz
    from app.models.draw_history import TournamentResult

    now = datetime.now(tz.utc).replace(tzinfo=None)

    # Global scores
    global_scores = {
        uid: score_user(uid, preds_by_user[uid], completed_matches, tournament, None)
        for uid in all_participants
    }
    global_ranked = rank_users(list(global_scores.values()), tournament.num_rounds)
    global_rank_of = {s.user_id: i + 1 for i, s in enumerate(global_ranked)}
    global_total = len(all_participants)

    rows = []
    for uid in all_participants:
        s = global_scores[uid]
        rows.append({
            "user_id": uid,
            "draw_id": tournament_id,
            "league_id": None,
            "league_name": "Global",
            "rank": global_rank_of[uid],
            "total_participants": global_total,
            "points": s.total_points,
            "correct_count": s.correct_count,
            "saved_at": now,
        })

    # Per-league scores
    for lg in all_leagues:
        member_ids = {m.user_id for m in lg.members}
        participants = all_participants & member_ids
        if len(participants) < 2:
            continue
        lg_scores = {
            uid: score_user(uid, preds_by_user[uid], completed_matches, tournament, None)
            for uid in participants
        }
        lg_ranked = rank_users(list(lg_scores.values()), tournament.num_rounds)
        lg_rank_of = {s.user_id: i + 1 for i, s in enumerate(lg_ranked)}
        for uid in participants:
            s = lg_scores[uid]
            rows.append({
                "user_id": uid,
                "draw_id": tournament_id,
                "league_id": lg.id,
                "league_name": lg.name,
                "rank": lg_rank_of[uid],
                "total_participants": len(participants),
                "points": s.total_points,
                "correct_count": s.correct_count,
                "saved_at": now,
            })

    # Delete existing results for this tournament before re-inserting.
    # ON CONFLICT DO UPDATE cannot match NULL league_id in SQLite (NULL != NULL),
    # so upsert silently inserts duplicates for Global rows.
    from sqlalchemy import delete as _delete
    await db.execute(_delete(TournamentResult).where(TournamentResult.draw_id == tournament_id))
    for row in rows:
        db.add(TournamentResult(**row))
    await db.commit()
    logger.info("Saved %d result row(s) for tournament %d", len(rows), tournament_id)


# ---------------------------------------------------------------------------
# Tournament-completion notification
# ---------------------------------------------------------------------------

async def notify_tournament_complete(tournament_id: int) -> None:
    """
    For every participant who opted into 'tournament_end', send ONE email
    showing their final standing in every group (global + all leagues).
    Idempotent: sets completion_notified_at on first call; subsequent calls no-op.
    """
    from app.services.email import send_tournament_complete_notification
    from datetime import datetime, timezone as tz

    async with AsyncSessionLocal() as db:
        tournament = await db.get(Draw, tournament_id)
        if not tournament:
            return

        # Idempotency guard — whichever trigger fires first wins
        if tournament.completion_notified_at is not None:
            return
        tournament.completion_notified_at = datetime.now(tz.utc)
        await db.commit()

        t_name = tournament.name
        t_year = tournament.year
        t_category = tournament.category or ""
        t_gender = tournament.gender or "M"

        # All completed matches (needed for scoring)
        m_res = await db.execute(
            select(Match)
            .options(selectinload(Match.player1), selectinload(Match.player2), selectinload(Match.winner))
            .where(Match.draw_id == tournament_id, Match.status == "completed")
        )
        completed_matches = m_res.scalars().all()

        total_res = await db.execute(
            select(func.count()).where(
                Match.draw_id == tournament_id,
                Match.is_bye == False,
            )
        )
        total_matches = total_res.scalar_one()
        if total_matches == 0:
            return

        # All predictions for this tournament
        pred_res = await db.execute(
            select(UserPrediction).where(
                UserPrediction.draw_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        all_preds = pred_res.scalars().all()

        preds_by_user: dict[int, list] = defaultdict(list)
        for p in all_preds:
            preds_by_user[p.user_id].append(p)

        # All users with any predictions (for draw history); eligible = complete bracket
        all_participants = set(preds_by_user.keys())
        eligible = {uid for uid, preds in preds_by_user.items() if len(preds) >= total_matches}

        # Load all leagues (needed for both results persistence and notifications)
        lg_res = await db.execute(
            select(League).options(selectinload(League.members))
        )
        all_leagues = lg_res.scalars().all()

        # Persist final standings for ALL participants (draw history)
        if all_participants:
            await _persist_tournament_results(
                db, tournament_id, all_participants, preds_by_user,
                completed_matches, tournament, all_leagues,
            )

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

        # Recompute scores for email (eligible subset only)
        global_scores = {
            uid: score_user(uid, preds_by_user[uid], completed_matches, tournament, None)
            for uid in eligible
        }
        global_ranked = rank_users(list(global_scores.values()), tournament.num_rounds)
        global_rank_of = {s.user_id: i + 1 for i, s in enumerate(global_ranked)}

        league_data: dict[int, dict] = {}
        for lg in all_leagues:
            member_ids = {m.user_id for m in lg.members}
            participants = eligible & member_ids
            if len(participants) < 2:
                continue
            lg_scores = {
                uid: score_user(uid, preds_by_user[uid], completed_matches, tournament, None)
                for uid in participants
            }
            lg_ranked = rank_users(list(lg_scores.values()), tournament.num_rounds)
            league_data[lg.id] = {
                "name": lg.name,
                "rank_of": {s.user_id: i + 1 for i, s in enumerate(lg_ranked)},
                "total":   len(participants),
                "points":  {s.user_id: s.total_points for s in lg_ranked},
            }

        user_league_ids: dict[int, list] = defaultdict(list)
        for lg_id, data in league_data.items():
            for uid in data["rank_of"]:
                user_league_ids[uid].append(lg_id)

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
            await send_tournament_complete_notification(
                email, t_name, t_year, tournament_id, groups,
                category=t_category, gender=t_gender,
            )
            logger.info(
                "Tournament-complete email sent to user %d (%d group(s)) for %d %s",
                uid, len(groups), t_year, t_name,
            )
        except Exception as exc:
            logger.warning("Failed to send completion email to user %d: %s", uid, exc)
