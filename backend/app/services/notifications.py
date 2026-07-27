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

# Max competitors shown in the Global block of a round-complete email.
GLOBAL_ROWS = 9


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


def _last_name(full: str) -> str:
    """Everything after the first token — mirrors the app-wide 'last name'
    convention (CombinedView.jsx's lastNameOf) so multi-word surnames like
    'Carreño Busta' stay together."""
    parts = full.strip().split()
    return " ".join(parts[1:]) if len(parts) > 1 else parts[0]


def _strip_tiebreak(val: str) -> str:
    idx = val.find("(")
    return val[:idx] if idx != -1 else val


def _match_score_str(match: Match) -> str:
    """Set-by-set score with tiebreak points stripped, e.g. '6-4, 3-6, 7-6'
    (never '7-6(12)') — kept compact for the round-complete email widget."""
    if not match.scores_json or len(match.scores_json) < 2:
        return ""
    p1_sets, p2_sets = match.scores_json[0], match.scores_json[1]
    own, opp = (p1_sets, p2_sets) if match.winner_id == match.player1_id else (p2_sets, p1_sets)
    parts = []
    for i in range(max(len(own), len(opp))):
        a = _strip_tiebreak(own[i]) if i < len(own) else ""
        b = _strip_tiebreak(opp[i]) if i < len(opp) else ""
        if not a and not b:
            continue
        parts.append(f"{a}-{b}")
    return ", ".join(parts)


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
            # is_bye excluded: a bye is not a contest. It is stamped completed with
            # an auto-advanced winner, and stray picks do exist on those rows, so
            # scoring them hands out free points (see _persist_tournament_results).
            .where(Match.draw_id == tournament_id, Match.status == "completed",
                   Match.is_bye == False)  # noqa: E712
        )
        completed_matches = m_res.scalars().all()

        # This round's results, in bracket order, for the email's results widget.
        # Per-user correctness (vs. this recipient's own pick) is layered on below,
        # once we know each recipient's predictions.
        round_matches = sorted(
            (m for m in completed_matches if m.round_number == round_number and not m.is_bye and m.winner_id),
            key=lambda m: m.match_number,
        )
        round_match_info = []  # (match_id, winner_id, winner_last, loser_last, score)
        for m in round_matches:
            winner_entry = m.winner
            loser_entry = m.player2 if m.winner_id == m.player1_id else m.player1
            if not winner_entry or not loser_entry:
                continue
            round_match_info.append((
                m.id, m.winner_id, _last_name(winner_entry.name), _last_name(loser_entry.name), _match_score_str(m),
            ))

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

    def _standings_rows(ranked: list, me: int, limit: Optional[int] = None) -> list[tuple]:
        """Competitor list for a group as (rank, username, score, is_you).

        With `limit` set, shows the top `limit` competitors — unless the
        recipient sits outside it, in which case the last of those slots goes
        to them, preceded by a "…" gap row: (None, '…', None, False). So the
        recipient is always present and the block never exceeds `limit`
        competitors.
        """
        if limit is None or len(ranked) <= limit:
            return [_row_of(ranked, i, me) for i in range(len(ranked))]
        me_idx = next((i for i, s in enumerate(ranked) if s.user_id == me), 0)
        if me_idx < limit:
            return [_row_of(ranked, i, me) for i in range(limit)]
        rows = [_row_of(ranked, i, me) for i in range(limit - 1)]
        rows.append((None, "…", None, False))
        rows.append(_row_of(ranked, me_idx, me))
        return rows

    for uid in to_notify:
        email = user_info.get(uid, {}).get("email")
        if not email:
            continue

        # This recipient's own pick correctness per match, for the results widget's
        # green check / red X — the winner list is shared, but "did I get it right"
        # is per-user.
        user_preds_by_match = {p.match_id: p.predicted_winner_id for p in preds_by_user.get(uid, [])}
        match_results = [
            (w_last, l_last, score, user_preds_by_match.get(mid) == winner_id)
            for mid, winner_id, w_last, l_last, score in round_match_info
        ]

        leagues = []
        my_league_ids = sorted(user_league_ids.get(uid, []))
        if len(eligible) >= 2:
            # Global shows at most 9 competitors, always including the recipient —
            # _standings_rows anchors the leaders and trailers and drops in a "…"
            # gap row when the recipient sits outside that head.
            g_limit = GLOBAL_ROWS if len(global_ranked) > GLOBAL_ROWS else None
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
                unsubscribe_url=unsubscribe_url, match_results=match_results,
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
    """
    Email all users opted-in to 'match_start' for this tournament.

    Idempotent: claims (draw_id) in match_start_notifications before sending.
    The picks_locked_at guard in espn_monitor.py already prevents this from
    being triggered twice in the normal case, but that check-then-set has no
    protection across a process restart racing an in-flight fire-and-forget
    call — this table's primary-key uniqueness is the hard backstop.
    """
    from sqlalchemy.exc import IntegrityError
    from app.services.email import send_match_start_notification
    from app.services.system_log import app_log
    from app.models.notification import MatchStartNotification

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
            .distinct()
        )
        emails = [r[0] for r in result.all()]

        db.add(MatchStartNotification(draw_id=tournament_id, recipient_count=len(emails)))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            await app_log(
                "warning", "notifications",
                f"Match-start email for draw {tournament_id} already sent — resend blocked",
                {"tournament_id": tournament_id},
                dedup_key=f"match-start-dupe-{tournament_id}",
            )
            return

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

# Draw-release emails are a single on/off. They were once selectable per tier
# ('draw_open:ATP 250', …), which stopped making sense when the email became a
# weekly digest: one message covers every draw released that week, so a per-tier
# opt-in could only ever have filtered rows out of a mail the user was getting
# regardless. The old keys are migrated into this one (see database.py).
DRAW_RELEASED_PREF = "draw_released"


async def notify_draw_release_batch(draw_ids: list[int], is_followup: bool = False) -> None:
    """
    Email every user with draw-release notifications on — one message covering
    every draw in the batch.

    Draws for a given week are announced together, so they are emailed together
    (scheduler.py's _notify_pending_draw_releases decides when a week's batch is
    ready) rather than as five separate messages.

    Claiming (draw_id) in draw_release_notifications is the hard,
    unique-constrained backstop behind the caller's coarse
    draw_release_notified_at check, which is a plain SELECT-then-UPDATE with no
    protection against two overlapping executions (a misfire re-run, or a
    migration resetting the detection timestamp, as happened 2026-07-12). Each
    claim gets its own savepoint: one already-claimed draw must drop out of the
    batch, not poison the session and abort the other four.
    """
    from datetime import datetime, timedelta, timezone as tz
    from sqlalchemy import update as sa_update
    from sqlalchemy.exc import IntegrityError
    from app.services.email import send_draw_release_digest, fmt_close_utc, _tier_badge
    from app.services.system_log import app_log
    from app.models.notification import DrawReleaseNotification

    if not draw_ids:
        return

    async with AsyncSessionLocal() as db:
        draws = (await db.execute(select(Draw).where(Draw.id.in_(draw_ids)))).scalars().all()

        # Claim first, send second. A draw that fails to claim has already been
        # emailed by an overlapping run and must be dropped from this batch.
        claimed = []
        for d in draws:
            try:
                async with db.begin_nested():
                    db.add(DrawReleaseNotification(draw_id=d.id, recipient_count=0))
                claimed.append(d)
            except IntegrityError:
                await app_log(
                    "warning", "notifications",
                    f"Draw-released email for draw {d.id} already sent — resend blocked",
                    {"tournament_id": d.id},
                    dedup_key=f"draw-release-dupe-{d.id}",
                )
        if not claimed:
            await db.rollback()
            return

        now_naive = datetime.now(tz.utc).replace(tzinfo=None)
        payload = []
        for d in claimed:
            location = ", ".join(p for p in (d.city, d.country) if p)
            payload.append({
                "id": d.id,
                "name": d.name,
                "gender": d.gender,
                "tier": _tier_badge(d.category or "", d.gender),
                "location": location or None,
                "surface": d.surface,
                "draw_size": d.draw_size,
                "closes": fmt_close_utc(d.closing_time) if d.closing_time else None,
                "closes_soon": bool(
                    d.closing_time and (d.closing_time - now_naive) < timedelta(hours=24)
                ),
                "_sort": d.closing_time or datetime.max,
            })
        payload.sort(key=lambda p: p["_sort"])

        starts = [d.start_date for d in claimed if d.start_date]
        week_start = min(starts) if starts else None
        week_label = f"{week_start.strftime('%B')} {week_start.day}" if week_start else "this week"

        # Keyed by email, not user id: one address gets one message even if it
        # somehow appears on two accounts.
        rows = (await db.execute(
            select(User.email, func.min(User.id))
            .join(NotificationPreference, NotificationPreference.user_id == User.id)
            .where(
                NotificationPreference.pref_key == DRAW_RELEASED_PREF,
                User.email_verified == True,
            )
            .group_by(User.email)
        )).all()
        recipients = {email: uid for email, uid in rows}

        await db.execute(
            sa_update(DrawReleaseNotification)
            .where(DrawReleaseNotification.draw_id.in_([d.id for d in claimed]))
            .values(recipient_count=len(recipients))
        )
        await db.commit()

    if not recipients:
        logger.debug("notify_draw_release_batch: no users opted in to %s", DRAW_RELEASED_PREF)
        return

    for email, uid in recipients.items():
        unsubscribe_url = (
            f"{API_BASE}/unsubscribe?token="
            f"{create_unsubscribe_token(uid, DRAW_RELEASED_PREF)}"
        )
        await send_draw_release_digest(
            email, payload, week_label,
            is_followup=is_followup, unsubscribe_url=unsubscribe_url,
        )

    names = ", ".join(f"{d.year} {d.name} ({d.gender})" for d in claimed)
    await app_log("info", "notifications",
                  f"Draw-release {'follow-up' if is_followup else 'digest'} sent to "
                  f"{len(recipients)} user(s) covering {len(claimed)} draw(s): {names}",
                  {"draw_ids": [d.id for d in claimed], "recipient_count": len(recipients),
                   "week_label": week_label, "is_followup": is_followup})


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
    showing their final standing in every group (global + all leagues), and
    persist final standings to draw history for every participant.

    Idempotent: claims (draw_id) in tournament_complete_notifications before
    doing any work — the unique-constrained primary key is the hard guard.
    Draw.completion_notified_at is kept as a cheap early-exit column, but a
    plain check-then-set-then-commit column alone isn't safe against two
    overlapping callers (this function can be triggered by the same
    process-restart race documented on MatchStartNotification), so it's no
    longer the sole guard.
    """
    from sqlalchemy.exc import IntegrityError
    from app.services.email import send_tournament_complete_notification
    from app.services.system_log import app_log
    from app.models.notification import TournamentCompleteNotification
    from datetime import datetime, timezone as tz

    async with AsyncSessionLocal() as db:
        tournament = await db.get(Draw, tournament_id)
        if not tournament:
            return

        if tournament.completion_notified_at is not None:
            return  # cheap early exit — the claim insert below is the real guard
        tournament.completion_notified_at = datetime.now(tz.utc)
        db.add(TournamentCompleteNotification(draw_id=tournament_id))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            await app_log(
                "warning", "notifications",
                f"Tournament-complete email for draw {tournament_id} already sent — resend blocked",
                {"tournament_id": tournament_id},
                dedup_key=f"tournament-complete-dupe-{tournament_id}",
            )
            return

        t_name = tournament.name
        t_year = tournament.year
        t_category = tournament.category or ""
        t_gender = tournament.gender or "M"

        # All completed matches (needed for scoring)
        m_res = await db.execute(
            select(Match)
            .options(selectinload(Match.player1), selectinload(Match.player2), selectinload(Match.winner))
            # is_bye excluded: a bye is not a contest. It is stamped completed with
            # an auto-advanced winner, and stray picks do exist on those rows, so
            # scoring them hands out free points (see _persist_tournament_results).
            .where(Match.draw_id == tournament_id, Match.status == "completed",
                   Match.is_bye == False)  # noqa: E712
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
        # Opts out of draw-completion emails ONLY — round_standings is a separate
        # preference with its own link.
        unsubscribe_url = (
            f"{API_BASE}/unsubscribe?token="
            f"{create_unsubscribe_token(uid, 'tournament_end')}"
        )
        try:
            await send_tournament_complete_notification(
                email, t_name, t_year, tournament_id, groups,
                category=t_category, gender=t_gender,
                unsubscribe_url=unsubscribe_url,
            )
            logger.info(
                "Tournament-complete email sent to user %d (%d group(s)) for %d %s",
                uid, len(groups), t_year, t_name,
            )
        except Exception as exc:
            logger.warning("Failed to send completion email to user %d: %s", uid, exc)
