from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user, get_optional_user
from app.database import get_db
from app.models.prediction import UserPrediction
from app.models.rankings import TePlayer, TeRankingsSnapshot
from app.models.tournament import DrawEntry, Match, Draw
from app.models.user import User
from app.schemas.league import LeaderboardEntry, LeagueTournamentOut
from app.schemas.tournament import DrawEntryOut, DrawOut, MatchOut, TournamentCreate, TournamentOut
from app.schemas.user import UserPublicOut
from app.services.rankings import assign_rankings
from app.services.scraper import scrape_tournament, snap_to_monday
from app.services.scoring import UserScore, _points_table, rank_users
from app.services.upsets import has_upset_pick

router = APIRouter(prefix="/tournaments", tags=["tournaments"])

# How many named unseeded players must hold bracket slots before we accept that
# the draw has actually been made (see the publication-signal block in
# _do_scrape). Small on purpose — the point is to catch publication early, and
# unseeded names cannot appear from a seeds-only entry-list placement. Kept
# above 1 so a single stray wildcard or parse artefact can't trip it.
BRACKET_PUBLISHED_MIN_UNSEEDED = 4


@router.get("", response_model=list[TournamentOut])
async def list_tournaments(db: AsyncSession = Depends(get_db)):
    lat_subq = (
        select(Match.draw_id, func.max(Match.completed_at).label("lat"))
        .group_by(Match.draw_id)
        .subquery()
    )
    result = await db.execute(
        select(Draw, lat_subq.c.lat)
        .outerjoin(lat_subq, Draw.id == lat_subq.c.draw_id)
        .order_by(Draw.year.desc(), Draw.name)
    )
    rows = result.all()
    tournaments = []
    for t, lat in rows:
        t.status = t.computed_status
        t.latest_result_at = lat
        tournaments.append(t)
    return tournaments


@router.post("", response_model=TournamentOut, status_code=201)
async def create_tournament(
    body: TournamentCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    t = Draw(
        name=" ".join(body.name.split()),  # collapse any accidental extra spaces
        year=body.year,
        gender=body.gender,
        surface=body.surface,
        wiki_page_title=body.wiki_page_title,
        start_date=body.start_date,
        end_date=body.end_date,
        venue_timezone=body.venue_timezone,
        day1_start_hour=body.day1_start_hour,
        day1_start_minute=body.day1_start_minute,
        closing_time=body.closing_time,
        draw_size=0,
        num_rounds=0,
    )
    db.add(t)
    await db.flush()  # get ID before scraping
    await _do_scrape(t, db)
    await db.commit()
    await db.refresh(t)
    return t


@router.post("/refresh-completed", response_model=dict)
async def refresh_all_completed(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Re-scrape every in-progress tournament (skips fully completed ones).

    Covers:
    - Tournaments that have already started (start_date <= today)
    - Upcoming tournaments whose expected draw date has passed but draw is not yet confirmed
    """
    import logging
    from datetime import date, timedelta
    from sqlalchemy import or_, and_
    logger = logging.getLogger(__name__)
    today = date.today()
    result = await db.execute(
        select(Draw).where(
            and_(
                Draw.status != "completed",
                or_(
                    # Already started
                    and_(Draw.start_date != None, Draw.start_date <= today),
                    # DA draw date has passed but not yet confirmed
                    and_(
                        Draw.draw_release_direct != None,
                        Draw.draw_release_direct <= today,
                        Draw.draw_released_direct_at == None,
                    ),
                    # Qualifier date has passed but not yet confirmed
                    and_(
                        Draw.draw_release_qualifiers != None,
                        Draw.draw_release_qualifiers <= today,
                        Draw.draw_released_qualifiers_at == None,
                    ),
                )
            )
        )
    )
    # Capture id/name/title before any rollback can expire ORM objects
    tournament_info = [
        (t.id, t.name, t.wiki_page_title)
        for t in result.scalars().all()
    ]
    ok, failed = 0, []
    for t_id, t_name, t_title in tournament_info:
        try:
            # Re-fetch fresh each time so a previous rollback doesn't leave a stale object
            t = await db.get(Draw, t_id)
            if t is None or t.status == "completed":
                continue
            await _do_scrape(t, db, force_refresh=True)
            await db.commit()
            ok += 1
        except Exception as exc:
            logger.error("Failed to re-scrape %s: %s", t_title, exc)
            await db.rollback()
            failed.append(t_name)
    return {"refreshed": ok, "failed": failed}


@router.post("/backfill-rankings", response_model=dict)
async def backfill_rankings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Re-resolve te_player_id and refresh rankings for every tournament."""
    import logging
    from datetime import date
    logger = logging.getLogger(__name__)

    # Same rule as refresh_all above: hold ids/names, not ORM objects. One
    # failure's rollback expires every attached instance, and reading `t.name`
    # on the next pass would then need a lazy reload the event loop can't do.
    tournaments_res = await db.execute(select(Draw.id, Draw.name))
    tournament_info = tournaments_res.all()

    updated_total = 0
    failed = []

    for t_id, t_name in tournament_info:
        try:
            t = await db.get(Draw, t_id)
            if t is None:
                continue
            ref_date = t.entry_ranking_week or t.start_date or date.today()
            players_res = await db.execute(select(DrawEntry).where(DrawEntry.draw_id == t_id))
            players = players_res.scalars().all()

            before = [p.ranking for p in players]
            await assign_rankings(players, t.gender, ref_date, db)
            after = [p.ranking for p in players]

            updated = sum(1 for b, a in zip(before, after) if b != a)
            await db.commit()
            updated_total += updated
            logger.info("%s: updated %d/%d player rankings", t_name, updated, len(players))
        except Exception as exc:
            logger.error("Failed rankings backfill for %s: %s", t_name, exc)
            await db.rollback()
            failed.append(t_name)

    return {"updated_players": updated_total, "failed": failed}


@router.post("/backfill-dob", response_model=dict)
async def backfill_dob(
    _: User = Depends(get_current_user),
):
    """Admin: fetch date-of-birth from TE for all te_players missing it."""
    from app.services.rankings import backfill_all_dob
    import asyncio
    asyncio.create_task(backfill_all_dob())
    return {"status": "started"}


@router.post("/sync-tournaments", response_model=dict)
async def sync_tournaments(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Run a full discovery + title-correction + scrape cycle for the current year.
    Fixes wrong wiki page titles (e.g. '– Men's singles' stored when Wikipedia
    uses '– Singles') then immediately scrapes any tournament still missing a
    confirmed page ID.
    """
    import logging
    from datetime import datetime, timezone
    logger = logging.getLogger(__name__)
    current_year = datetime.now(timezone.utc).year
    try:
        from app.services.tournament_sync import sync_season
        summary = await sync_season(db, current_year, scrape_new=True)
        return {"status": "ok", **summary}
    except Exception as exc:
        logger.error("sync_tournaments failed: %s", exc)
        await db.rollback()
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/apply-schedules", response_model=dict)
async def apply_all_schedules(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Back-fill venue_timezone, day1_start_hour, day1_start_minute, and closing_time
    for all tournaments that are missing them.  Safe to re-run; won't overwrite
    manually-set values.
    """
    import logging
    from app.services.tournament_schedule import apply_schedule, apply_closing_time
    logger = logging.getLogger(__name__)

    result = await db.execute(select(Draw))
    tournaments = result.scalars().all()

    schedule_set = closing_set = 0
    for t in tournaments:
        if apply_schedule(t):
            schedule_set += 1
        if apply_closing_time(t):
            closing_set += 1
            logger.info("Set closing_time for %s %s: %s", t.year, t.name, t.closing_time)

    await db.commit()
    return {"schedule_fields_set": schedule_set, "closing_times_set": closing_set}


def _tier(category: Optional[str]) -> str:
    cat = (category or "").upper()
    if "SLAM" in cat or "GRAND" in cat:
        return "Grand Slam"
    if "1000" in cat:
        return "1000"
    if "500" in cat:
        return "500"
    return "250"


_TIER_ORDER = ["Grand Slam", "1000", "500", "250"]


_HOF_TOP_N = 5


@router.get("/hall-of-fame")
async def hall_of_fame(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Top 5 all-time scores per tier/gender, plus the caller's own best if outside the top 5."""
    from app.models.draw_history import TournamentResult
    from app.models.prediction import UserPrediction

    # Subqueries to enforce "competed" = user picked every non-bye match
    pick_count_sq = (
        select(
            UserPrediction.draw_id,
            UserPrediction.user_id,
            func.count().label("picks"),
        )
        .where(UserPrediction.predicted_winner_id.isnot(None))
        .group_by(UserPrediction.draw_id, UserPrediction.user_id)
        .subquery()
    )
    match_count_sq = (
        select(Match.draw_id, func.count().label("total"))
        .where(Match.is_bye == False)  # noqa: E712
        .group_by(Match.draw_id)
        .subquery()
    )

    res = await db.execute(
        select(
            TournamentResult.draw_id,
            TournamentResult.user_id,
            TournamentResult.points,
            TournamentResult.correct_count,
            match_count_sq.c.total.label("total_matches"),
            Draw.name,
            Draw.year,
            Draw.gender,
            Draw.category,
            User.username,
        )
        .join(Draw, Draw.id == TournamentResult.draw_id)
        .join(User, User.id == TournamentResult.user_id)
        .join(
            pick_count_sq,
            (pick_count_sq.c.draw_id == TournamentResult.draw_id)
            & (pick_count_sq.c.user_id == TournamentResult.user_id),
        )
        .join(match_count_sq, match_count_sq.c.draw_id == TournamentResult.draw_id)
        .where(
            TournamentResult.league_id.is_(None),
            pick_count_sq.c.picks >= match_count_sq.c.total,
        )
        .order_by(TournamentResult.points.desc())
    )
    rows = res.all()

    me_id = current_user.id if current_user else None

    by_tier: dict[str, dict[str, list]] = {t: {"M": [], "F": []} for t in _TIER_ORDER}
    seen: dict[str, set] = {t: set() for t in _TIER_ORDER}  # (username, tournament_id) per tier
    ranked: dict[str, dict[str, int]] = {t: {"M": 0, "F": 0} for t in _TIER_ORDER}
    # Caller's best result per tier/gender when it falls outside the top 5
    mine: dict[str, dict[str, Optional[dict]]] = {t: {"M": None, "F": None} for t in _TIER_ORDER}

    for row in rows:
        tier = _tier(row.category)
        gender = row.gender  # "M" or "F"
        if gender not in ("M", "F"):
            continue
        key = (row.username, row.draw_id)
        if key in seen[tier]:
            continue
        seen[tier].add(key)

        ranked[tier][gender] += 1
        entry = {
            "rank": ranked[tier][gender],
            "user_id": row.user_id,
            "username": row.username,
            "points": row.points,
            "correct_count": row.correct_count,
            "total_matches": row.total_matches,
            "tournament_id": row.draw_id,
            "tournament_name": row.name,
            "tournament_year": row.year,
            "is_current_user": row.user_id == me_id,
        }

        if entry["rank"] <= _HOF_TOP_N:
            by_tier[tier][gender].append(entry)
        elif row.user_id == me_id and mine[tier][gender] is None:
            # rows are ordered by points desc, so the first one seen is their best
            mine[tier][gender] = entry

    def bucket(tier: str, gender: str) -> list:
        entries = by_tier[tier][gender]
        extra = mine[tier][gender]
        if extra and not any(e["user_id"] == me_id for e in entries):
            return entries + [extra]
        return entries

    return [
        {"tier": tier, "men": bucket(tier, "M"), "women": bucket(tier, "F")}
        for tier in _TIER_ORDER
    ]


@router.get("/global-gs-totals")
async def global_gs_totals(db: AsyncSession = Depends(get_db)):
    """Grand Slam point totals for ALL verified users this year, with is_admin flag."""
    from datetime import date
    from collections import defaultdict
    from app.services.scoring import _points_table

    year = date.today().year
    gs_result = await db.execute(
        select(Draw).where(Draw.year == year, Draw.category.ilike('%grand slam%'))
    )
    gs_draws = gs_result.scalars().all()

    users_result = await db.execute(
        select(User).where(User.email_verified == True).order_by(User.username)
    )
    users = users_result.scalars().all()
    user_ids = [u.id for u in users]

    atp: dict = defaultdict(float)
    wta: dict = defaultdict(float)

    for draw in gs_draws:
        pts_table = _points_table(draw)
        cm_result = await db.execute(
            select(Match).where(
                Match.draw_id == draw.id,
                Match.status == "completed",
                Match.is_bye == False,
            )
        )
        completed = cm_result.scalars().all()
        if not completed:
            continue
        for user_id in user_ids:
            preds_result = await db.execute(
                select(UserPrediction).where(
                    UserPrediction.user_id == user_id,
                    UserPrediction.draw_id == draw.id,
                    UserPrediction.predicted_winner_id.isnot(None),
                )
            )
            pred_by_match = {p.match_id: p.predicted_winner_id for p in preds_result.scalars().all()}
            for m in completed:
                if m.winner_id and pred_by_match.get(m.id) == m.winner_id:
                    pts = pts_table.get(m.round_number, 0)
                    if draw.gender == 'M':
                        atp[user_id] += pts
                    else:
                        wta[user_id] += pts

    entries = [
        {
            "user_id": u.id,
            "username": u.username,
            "full_name": u.full_name,
            "is_admin": u.is_admin,
            "atp_points": int(atp[u.id]),
            "wta_points": int(wta[u.id]),
        }
        for u in users
    ]
    entries.sort(key=lambda x: -(x["atp_points"] + x["wta_points"]))
    return {"year": year, "members": entries}


@router.get("/global-draws", response_model=list[LeagueTournamentOut])
async def global_draws(db: AsyncSession = Depends(get_db)):
    """Draws where at least one user has fully entered picks, with global picker counts."""
    from collections import defaultdict

    picks_result = await db.execute(
        select(
            UserPrediction.draw_id,
            UserPrediction.user_id,
            func.count().label("pick_count"),
        )
        .where(UserPrediction.predicted_winner_id.isnot(None))
        .group_by(UserPrediction.draw_id, UserPrediction.user_id)
    )
    picks_rows = picks_result.all()

    t_ids = list({r.draw_id for r in picks_rows})
    if not t_ids:
        return []

    totals_result = await db.execute(
        select(Match.draw_id, func.count().label("total"))
        .where(Match.draw_id.in_(t_ids), Match.is_bye == False)
        .group_by(Match.draw_id)
    )
    total_by_t = {r.draw_id: r.total for r in totals_result.all()}

    fully_entered: defaultdict = defaultdict(int)
    for r in picks_rows:
        if r.pick_count >= total_by_t.get(r.draw_id, 0) > 0:
            fully_entered[r.draw_id] += 1

    out = []
    for draw_id, picker_count in fully_entered.items():
        t = await db.get(Draw, draw_id)
        if t:
            t.status = t.computed_status
            out.append(LeagueTournamentOut(
                tournament=TournamentOut.model_validate(t),
                picker_count=picker_count,
            ))
    return out


@router.get("/{tournament_id}", response_model=TournamentOut)
async def get_tournament(tournament_id: int, db: AsyncSession = Depends(get_db)):
    t = await db.get(Draw, tournament_id)
    if not t:
        raise HTTPException(404, "Tournament not found")
    # Same override every other serializing endpoint applies — "open" exists
    # only in computed_status, so without this the raw column leaks out and
    # any status === 'open' check against this endpoint silently fails.
    t.status = t.computed_status
    lat = await db.execute(
        select(func.max(Match.completed_at)).where(Match.draw_id == tournament_id)
    )
    t.latest_result_at = lat.scalar_one_or_none()
    return t


@router.get("/{tournament_id}/competitors", response_model=list[UserPublicOut])
async def tournament_competitors(tournament_id: int, db: AsyncSession = Depends(get_db)):
    """Return all users who have submitted complete picks for this tournament."""
    total_result = await db.execute(
        select(func.count())
        .where(Match.draw_id == tournament_id, Match.is_bye == False)
    )
    total = total_result.scalar_one()
    if total == 0:
        return []

    sub = (
        select(UserPrediction.user_id)
        .where(
            UserPrediction.draw_id == tournament_id,
            UserPrediction.predicted_winner_id.isnot(None),
        )
        .group_by(UserPrediction.user_id)
        .having(func.count() >= total)
    )
    result = await db.execute(
        select(User).where(User.id.in_(sub)).order_by(User.display_name)
    )
    return result.scalars().all()


@router.get("/{tournament_id}/standings", response_model=list[LeaderboardEntry])
async def global_standings(tournament_id: int, db: AsyncSession = Depends(get_db)):
    """Global standings for a tournament using classic scoring (no league)."""
    tournament = await db.get(Draw, tournament_id)
    if not tournament:
        raise HTTPException(404, "Tournament not found")

    total_result = await db.execute(
        select(func.count()).where(Match.draw_id == tournament_id, Match.is_bye == False)
    )
    total_matches = total_result.scalar_one()
    if total_matches == 0:
        return []

    completed_result = await db.execute(
        select(Match)
        .options(selectinload(Match.player1), selectinload(Match.player2), selectinload(Match.winner))
        # is_bye excluded: a bye is not a contest. It is stamped completed with
        # an auto-advanced winner, and stray picks do sit on those rows, so
        # scoring them hands out free points.
        .where(Match.draw_id == tournament_id, Match.status == "completed",
               Match.is_bye == False)  # noqa: E712
    )
    completed_matches = completed_result.scalars().all()

    # All matches (not just completed) + draw entries — needed to determine
    # whether a user's picks include at least one upset (a user must pick at
    # least one to count as "participating"), which requires resolving every
    # round's entrants, not just ones already decided.
    all_matches_result = await db.execute(
        select(Match).where(Match.draw_id == tournament_id)
    )
    all_matches = all_matches_result.scalars().all()
    all_entries_result = await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == tournament_id)
    )
    all_entries = all_entries_result.scalars().all()

    # The real Classic table (tier x round), same as league standings, stored
    # results, the Hall of Fame and the round-complete emails. This used to be
    # a local 2^(r-1) approximation, which quietly gave this one screen a
    # different point total than every other view of the same picks.
    pts_table = _points_table(tournament)

    # Users with at least one pick — those with a complete bracket are ranked
    # normally; partial pickers are appended after (greyed out on the frontend).
    sub = (
        select(UserPrediction.user_id)
        .where(UserPrediction.draw_id == tournament_id, UserPrediction.predicted_winner_id.isnot(None))
        .group_by(UserPrediction.user_id)
    )
    users_result = await db.execute(select(User).where(User.id.in_(sub)))
    users = users_result.scalars().all()

    complete_scores: list[UserScore] = []
    partial_scores: list[UserScore] = []
    has_upset_map: dict[int, bool] = {}
    for user in users:
        preds_result = await db.execute(
            select(UserPrediction).where(
                UserPrediction.user_id == user.id,
                UserPrediction.draw_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        preds = preds_result.scalars().all()
        pred_by_match = {p.match_id: p.predicted_winner_id for p in preds}
        has_upset_map[user.id] = has_upset_pick(preds, all_matches, all_entries)

        total_pts = 0.0
        correct = 0
        correct_by_round: dict[int, int] = {}
        for m in completed_matches:
            if m.winner_id is None:
                continue
            if pred_by_match.get(m.id) == m.winner_id:
                total_pts += pts_table.get(m.round_number, 0)
                correct += 1
                correct_by_round[m.round_number] = correct_by_round.get(m.round_number, 0) + 1
        score = UserScore(user_id=user.id, total_points=total_pts, correct_count=correct,
                          correct_by_round=correct_by_round)
        if len(preds) < total_matches:
            partial_scores.append(score)
        else:
            complete_scores.append(score)

    ranked = rank_users(complete_scores, tournament.num_rounds)
    partial_ranked = rank_users(partial_scores, tournament.num_rounds)
    user_map = {u.id: u for u in users}
    return [
        LeaderboardEntry(rank=i + 1, user=user_map[s.user_id], total_points=s.total_points,
                         correct_count=s.correct_count, has_upset_pick=has_upset_map[s.user_id])
        for i, s in enumerate(ranked)
    ] + [
        LeaderboardEntry(rank=len(ranked) + i + 1, user=user_map[s.user_id], total_points=s.total_points,
                         correct_count=s.correct_count, is_complete=False, has_upset_pick=has_upset_map[s.user_id])
        for i, s in enumerate(partial_ranked)
    ]


@router.get("/{tournament_id}/global-round-scores")
async def global_round_scores(tournament_id: int, db: AsyncSession = Depends(get_db)):
    """Per-round point breakdown for ALL fully-entered users in a tournament."""
    from collections import defaultdict
    from app.services.scoring import _points_table

    tournament = await db.get(Draw, tournament_id)
    if not tournament:
        raise HTTPException(404, "Tournament not found")

    pts_table = _points_table(tournament)

    completed_matches_result = await db.execute(
        select(Match)
        .options(selectinload(Match.player1), selectinload(Match.player2))
        .where(
            Match.draw_id == tournament_id,
            Match.status == "completed",
            Match.is_bye == False,
        )
    )
    completed_matches = completed_matches_result.scalars().all()

    total_result = await db.execute(
        select(func.count()).where(Match.draw_id == tournament_id, Match.is_bye == False)
    )
    total_matches = total_result.scalar_one()

    sub = (
        select(UserPrediction.user_id)
        .where(UserPrediction.draw_id == tournament_id, UserPrediction.predicted_winner_id.isnot(None))
        .group_by(UserPrediction.user_id)
        .having(func.count() >= total_matches)
    )
    users_result = await db.execute(select(User).where(User.id.in_(sub)))
    users = users_result.scalars().all()

    timeline_ids = {m.id for m in completed_matches}
    user_predictions: dict = {}
    entries = []
    for user in users:
        preds_result = await db.execute(
            select(UserPrediction).where(
                UserPrediction.user_id == user.id,
                UserPrediction.draw_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        preds = preds_result.scalars().all()
        pred_by_match = {p.match_id: p.predicted_winner_id for p in preds}
        user_predictions[str(user.id)] = {str(k): v for k, v in pred_by_match.items() if k in timeline_ids}
        by_round: defaultdict = defaultdict(float)
        correct_count = 0
        for match in completed_matches:
            if match.winner_id is None:
                continue
            if pred_by_match.get(match.id) != match.winner_id:
                continue
            by_round[match.round_number] += pts_table.get(match.round_number, 0)
            correct_count += 1

        pts_list = [by_round.get(r, 0) for r in range(1, (tournament.num_rounds or 7) + 1)]
        entries.append({
            "user_id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "round_points": pts_list,
            "total": sum(pts_list),
            "correct_count": correct_count,
        })

    entries.sort(key=lambda x: (-x["total"],) + tuple(-rp for rp in reversed(x["round_points"])))
    rounds_with_matches = sorted({m.round_number for m in completed_matches})

    # A round is "complete" only once every non-bye match in it has finished —
    # not just because it's the highest round with any match played so far
    # (that heuristic misfires when there's a rest day before the next round starts).
    total_by_round_result = await db.execute(
        select(Match.round_number, func.count())
        .where(Match.draw_id == tournament_id, Match.is_bye == False)
        .group_by(Match.round_number)
    )
    total_by_round = dict(total_by_round_result.all())
    completed_by_round: defaultdict = defaultdict(int)
    for m in completed_matches:
        completed_by_round[m.round_number] += 1
    completed_round_nums = sorted(
        r for r, total in total_by_round.items()
        if total > 0 and completed_by_round.get(r, 0) >= total
    )

    def _isoZ(dt):
        if dt is None: return None
        s = dt.isoformat()
        return s if (s.endswith('Z') or '+' in s) else s + 'Z'

    def _entry_name(entry): return entry.name if entry else None
    timeline = sorted(
        [{"id": m.id, "round_number": m.round_number, "winner_id": m.winner_id,
          "points": pts_table.get(m.round_number, 0), "completed_at": _isoZ(m.completed_at),
          "winner_name": _entry_name(m.player1 if m.player1_id == m.winner_id else m.player2),
          "loser_name": _entry_name(m.player2 if m.player1_id == m.winner_id else m.player1)}
         for m in completed_matches],
        key=lambda x: (x["completed_at"] is not None, x["completed_at"] or "", x["id"])
    )
    return {
        "entries": entries,
        "completed_matches_count": len(completed_matches),
        "rounds_with_matches": rounds_with_matches,
        "completed_round_nums": completed_round_nums,
        "matches_timeline": timeline,
        "user_predictions": user_predictions,
    }


@router.get("/{tournament_id}/draw", response_model=DrawOut)
async def get_draw(tournament_id: int, db: AsyncSession = Depends(get_db)):
    t = await db.get(Draw, tournament_id)
    if not t:
        raise HTTPException(404, "Tournament not found")
    # The raw `status` column only ever holds upcoming/active/completed — "open"
    # is purely computed (see Draw.computed_status). list_tournaments() and
    # global_draws() already apply this override before serializing; this
    # single-draw endpoint never did, so the frontend's `tournament.status`
    # was always the stale raw value here, silently breaking every
    # status === 'open' check on the draw page (auto-init banner, DA/Qual badges).
    t.status = t.computed_status

    players_result = await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == tournament_id).order_by(DrawEntry.bracket_position)
    )
    players = players_result.scalars().all()

    # Bulk-load TE player data for all players with a TE identity
    te_ids = [p.te_player_id for p in players if p.te_player_id is not None]
    te_dob_map: dict[int, "date"] = {}
    te_elo_rank_map: dict[int, int] = {}
    if te_ids:
        te_res = await db.execute(
            select(TePlayer.id, TePlayer.date_of_birth)
            .where(TePlayer.id.in_(te_ids))
        )
        for row in te_res:
            if row.date_of_birth:
                te_dob_map[row.id] = row.date_of_birth

        # ELO rank lives in the rankings snapshot closest to (on or before) this
        # tournament's own ranking-reference date — NOT always the single latest
        # snapshot, otherwise viewing an old/historical draw would show each
        # player's CURRENT Elo rank instead of their rank at the time it was played.
        elo_ref_date = t.entry_ranking_week or t.start_date
        max_week_subq = select(func.max(TeRankingsSnapshot.week_date)).where(
            TeRankingsSnapshot.player_id.in_(te_ids)
        )
        if elo_ref_date:
            max_week_subq = max_week_subq.where(TeRankingsSnapshot.week_date <= elo_ref_date)
        elo_snap_res = await db.execute(
            select(TeRankingsSnapshot.player_id, TeRankingsSnapshot.elo_rank)
            .where(
                TeRankingsSnapshot.player_id.in_(te_ids),
                TeRankingsSnapshot.elo_rank.isnot(None),
                TeRankingsSnapshot.week_date == max_week_subq.scalar_subquery(),
            )
        )
        for row in elo_snap_res:
            if row.elo_rank:
                te_elo_rank_map[row.player_id] = row.elo_rank

    matches_result = await db.execute(
        select(Match)
        .where(Match.draw_id == tournament_id)
        .options(
            selectinload(Match.player1),
            selectinload(Match.player2),
            selectinload(Match.winner),
        )
        .order_by(Match.round_number, Match.match_number)
    )
    matches = matches_result.scalars().all()

    def _player_out(p: DrawEntry) -> DrawEntryOut:
        out = DrawEntryOut.model_validate(p)
        # te_slug comes directly from draw_entries column now
        out.date_of_birth = te_dob_map.get(p.te_player_id) if p.te_player_id else None
        out.elo_rank = te_elo_rank_map.get(p.te_player_id) if p.te_player_id else None
        return out

    match_outs = []
    for m in matches:
        match_outs.append(MatchOut(
            id=m.id,
            round_number=m.round_number,
            match_number=m.match_number,
            player1=_player_out(m.player1) if m.player1 else None,
            player2=_player_out(m.player2) if m.player2 else None,
            winner=_player_out(m.winner) if m.winner else None,
            is_bye=m.is_bye,
            status=m.status,
            round_name=t.round_name(m.round_number),
            scores=m.scores_json,
            live_scores=m.live_scores_json,
        ))

    t.latest_result_at = max((m.completed_at for m in matches if m.completed_at), default=None)
    return DrawOut(
        tournament=TournamentOut.model_validate(t),
        draw_entries=[_player_out(p) for p in players],
        matches=match_outs,
    )


@router.post("/{tournament_id}/refresh", response_model=TournamentOut)
async def refresh_draw(
    tournament_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    import asyncio
    from app.services.h2h import prefetch_h2h_for_draw
    from app.services.rankings import prefetch_dob_for_draw

    t = await db.get(Draw, tournament_id)
    if not t:
        raise HTTPException(404, "Tournament not found")
    await _do_scrape(t, db, force_refresh=True)
    await db.commit()
    await db.refresh(t)
    # Kick off background tasks — neither blocks the response
    asyncio.create_task(prefetch_h2h_for_draw(tournament_id))
    asyncio.create_task(prefetch_dob_for_draw(tournament_id))
    return t


@router.post("/{tournament_id}/toggle-unlock", response_model=TournamentOut)
async def toggle_unlock_selections(
    tournament_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(403, "Admin only")
    t = await db.get(Draw, tournament_id)
    if not t:
        raise HTTPException(404, "Tournament not found")
    t.selections_unlocked = not t.selections_unlocked
    await db.commit()
    await db.refresh(t)
    return t


# ---------------------------------------------------------------------------
# Internal scrape helper
# ---------------------------------------------------------------------------

async def _do_scrape(tournament: Draw, db: AsyncSession, force_refresh: bool = False) -> None:
    from datetime import date
    import logging
    logger = logging.getLogger(__name__)

    parsed = await scrape_tournament(
        tournament.wiki_page_title,
        year=tournament.year,
        gender=tournament.gender,
        page_id=tournament.wiki_page_id,
        force_refresh=force_refresh,
    )
    if parsed.wiki_page_id and parsed.wiki_page_id != tournament.wiki_page_id:
        # Either first-time resolution (was None) or a correction from the scraper's
        # wrong-page retry (stored ID pointed to e.g. the general event page).
        clash = await db.execute(
            select(Draw.id).where(
                Draw.wiki_page_id == parsed.wiki_page_id,
                Draw.id != tournament.id,
            )
        )
        clash_id = clash.scalar_one_or_none()
        if clash_id is not None:
            # The fetched page IS another record's page (page_ids are unique) —
            # applying its draw data here would pollute this tournament with
            # another event's players/matches (this happened: Hamburg (F)
            # ingested the men's May draw via a title-variant probe). Abort.
            from app.services.system_log import app_log
            await app_log(
                "warning", "scraper",
                f"Scrape for {tournament.year} {tournament.name} ({tournament.gender}) "
                f"resolved to page_id {parsed.wiki_page_id}, which belongs to "
                f"tournament {clash_id} — not applying foreign page data",
                {"tournament_id": tournament.id, "tournament_name": tournament.name,
                 "wiki_title": tournament.wiki_page_title,
                 "resolved_page_id": parsed.wiki_page_id, "owner_tournament_id": clash_id},
                dedup_key=f"foreign_page_{tournament.id}", dedup_hours=6.0,
            )
            return
        if tournament.wiki_page_id is not None:
            logger.warning(
                "Correcting wiki_page_id for %s: %s → %s (wrong page was stored)",
                tournament.wiki_page_title, tournament.wiki_page_id, parsed.wiki_page_id,
            )
        tournament.wiki_page_id = parsed.wiki_page_id
    if parsed.resolved_title:
        # Guard against UNIQUE violation if another record already claims this resolved title.
        # This can happen when the discovery service uses a slightly different title variant
        # (e.g. "– Women's singles" vs "– Singles") for a tournament already in the DB.
        title_clash = await db.execute(
            select(Draw.id).where(
                Draw.wiki_page_title == parsed.resolved_title,
                Draw.id != tournament.id,
            )
        )
        if title_clash.scalar_one_or_none() is None:
            logger.info("Correcting wiki_page_title for %s: %r → %r",
                        tournament.name, tournament.wiki_page_title, parsed.resolved_title)
            tournament.wiki_page_title = parsed.resolved_title
        else:
            logger.warning(
                "Resolved title %r already owned by another record; "
                "keeping %r for tournament %d",
                parsed.resolved_title, tournament.wiki_page_title, tournament.id,
            )

    if parsed.draw_size:
        tournament.draw_size = parsed.draw_size
    if parsed.num_rounds:
        tournament.num_rounds = parsed.num_rounds
    tournament.last_scraped_at = datetime.now(timezone.utc)

    # Update location from infobox if not already set
    if parsed.city and not tournament.city:
        tournament.city = parsed.city
    if parsed.country and not tournament.country:
        tournament.country = parsed.country

    # Auto-populate schedule fields and closing_time from lookup table
    from app.services.tournament_schedule import apply_schedule, apply_closing_time
    apply_schedule(tournament)
    if apply_closing_time(tournament):
        logger.info(
            "Auto-set closing_time for %s %s: %s (tz=%s %02d:%02d local)",
            tournament.year, tournament.name, tournament.closing_time,
            tournament.venue_timezone, tournament.day1_start_hour or 0,
            tournament.day1_start_minute or 0,
        )

    # Authoritative dates from the tournament's own infobox (general Wikipedia page).
    # If the general page parse failed, snap whatever date we have to Monday —
    # schedule pages can include qualifying days which shift the date by 1-2 days.
    # Skip date updates once the tournament is active/completed: qualifying can
    # start a day before the Wikipedia-reported date, and Wikipedia lags real play.
    if tournament.status not in ("active", "completed"):
        if parsed.start_date:
            tournament.start_date = parsed.start_date
        elif tournament.start_date:
            tournament.start_date = snap_to_monday(tournament.start_date)
        if parsed.end_date:
            tournament.end_date = parsed.end_date

    # Record actual draw release dates when detected.
    # Only stamp draw_released_direct_at once the draw is substantially complete
    # (≥50% of non-Q/LL slots — generous threshold to avoid missing real draws).
    # A page with only a handful of seeded players is not a released draw.
    da_players = [p for p in parsed.players if p.name and p.entry_type not in ("Q", "LL")]
    # Q/LL placeholders (named or unnamed) occupy fixed slots that will never be
    # filled by DA players, so subtract them before applying the 85% threshold.
    q_ll_count = sum(1 for p in parsed.players if p.entry_type in ("Q", "LL"))
    effective_da_size = max(tournament.draw_size - q_ll_count, 0)
    draw_substantially_complete = (
        tournament.draw_size > 0 and len(da_players) >= effective_da_size * 0.50
    )
    # Don't stamp draws for tournaments that are more than 60 days out — Wikipedia
    # sometimes has complete draws for far-future events (e.g. Dec/Jan crossover tournaments)
    # and we don't want to notify months early.
    # Use start_date if available, fall back to end_date (which is always more reliable
    # for year-crossover events like Auckland Dec 29 - Jan 5).
    ref_date = tournament.start_date or tournament.end_date
    days_until = (ref_date - date.today()).days if ref_date else 0
    too_far_future = ref_date is not None and days_until > 60

    # --- Publication signal: has the draw ceremony actually happened? ---------
    # Named UNSEEDED players holding bracket slots is the earliest honest
    # evidence. Seeded players alone are not: editors place seeds into their
    # slots as soon as the entry list is announced, days before Round-1 pairings
    # exist — the same false positive the 50% threshold above guards against.
    # An unseeded name can only come from a real draw.
    #
    # This is recorded separately from draw_released_direct_at because the two
    # answer different questions. draw_released_direct_at asks "is the page
    # complete enough to play from" (it gates picks and the release email, and
    # 50% is the right bar for that). bracket_first_seen asks "when was the draw
    # published", which is what next season's estimate must be built from.
    # Learning from the completeness threshold instead made every prediction a
    # measure of Wikipedia editor pace, and the daily scraper then only started
    # polling once that late prediction arrived — so the estimate could never
    # discover it was wrong.
    unseeded_named = [p for p in da_players if p.seed is None]
    bracket_published = len(unseeded_named) >= BRACKET_PUBLISHED_MIN_UNSEEDED
    if bracket_published and tournament.bracket_first_seen_at is None and not too_far_future:
        tournament.bracket_first_seen_at = date.today()
        if tournament.start_date:
            tournament.bracket_first_seen_days_before = (tournament.start_date - date.today()).days
        logger.info("Tournament %s: Bracket first seen on %s (%d unseeded players placed, %s days before start)",
                    tournament.wiki_page_title, date.today(), len(unseeded_named),
                    tournament.bracket_first_seen_days_before)
    elif not bracket_published and tournament.bracket_first_seen_at is not None \
            and tournament.status not in ("active", "completed"):
        # Signal retracted (page blanked, bad parse, vandalism) before play began —
        # drop the observation rather than feed a phantom date into the estimator.
        tournament.bracket_first_seen_at = None
        tournament.bracket_first_seen_days_before = None
        logger.info("Tournament %s: Clearing bracket-first-seen (%d unseeded players now present)",
                    tournament.wiki_page_title, len(unseeded_named))

    if parsed.has_direct_draw and draw_substantially_complete:
        if not tournament.draw_released_direct_at and not too_far_future:
            tournament.draw_released_direct_at = date.today()
            # First time we've observed a substantially-complete draw — start the
            # stability clock. The "draw released" email only fires once this has
            # held for a cooldown (_notify_pending_draw_releases in scheduler.py),
            # so a same-day revert (below) never results in an email having gone out.
            tournament.draw_release_detected_at = datetime.now(timezone.utc)
            if tournament.start_date:
                tournament.da_days_before = (tournament.start_date - date.today()).days
            logger.info("Tournament %s: Direct acceptance draw released on %s (%d players, %s days before start)",
                       tournament.wiki_page_title, date.today(), len(da_players),
                       tournament.da_days_before)
    elif tournament.draw_released_direct_at and not draw_substantially_complete \
            and tournament.status not in ("active", "completed"):
        # Draw was stamped prematurely (e.g. only seeds visible) — revert until complete.
        # da_days_before goes with it: the observation it recorded has been retracted,
        # and leaving it set means the next stamp silently overwrites it with a later,
        # smaller value, so every flicker drags this category's history downward.
        tournament.draw_released_direct_at = None
        tournament.draw_release_detected_at = None
        tournament.da_days_before = None
        logger.info("Tournament %s: Clearing premature draw release (%d/%d players present)",
                   tournament.wiki_page_title, len(da_players), tournament.draw_size)

    if parsed.has_qualifiers and not tournament.draw_released_qualifiers_at:
        tournament.draw_released_qualifiers_at = date.today()
        if tournament.start_date:
            tournament.qual_days_before = (tournament.start_date - date.today()).days
        logger.info("Tournament %s: Qualifiers added on %s (%s days before start)",
                   tournament.wiki_page_title, date.today(), tournament.qual_days_before)

    # If final match has a winner, tournament is completed regardless of current date
    if parsed.has_final_winner:
        if tournament.status != "completed" and tournament.start_date \
                and (tournament.start_date - date.today()).days > 30:
            # A finished bracket for an event supposedly >30 days away means the
            # stored dates point at the wrong edition (Dec/Jan season openers were
            # once stamped a year forward) — surface the contradiction.
            from app.services.system_log import app_log
            await app_log(
                "warning", "scraper",
                f"{tournament.name} {tournament.year} completed but start_date "
                f"{tournament.start_date} is >30 days in the future — dates likely wrong",
                {"draw_id": tournament.id, "start_date": str(tournament.start_date),
                 "wiki_page_title": tournament.wiki_page_title},
                dedup_key=f"future_completed_{tournament.id}", dedup_hours=168,
            )
        tournament.status = "completed"
        logger.info("Tournament %s marked as completed (final match has winner)", tournament.wiki_page_title)

    # Load existing players and matches indexed for upsert
    existing_players_res = await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == tournament.id)
    )
    existing_players: dict[int, DrawEntry] = {
        p.bracket_position: p for p in existing_players_res.scalars()
    }
    existing_matches_res = await db.execute(
        select(Match).where(Match.draw_id == tournament.id)
    )
    existing_matches: dict[tuple, Match] = {
        (m.round_number, m.match_number): m for m in existing_matches_res.scalars()
    }

    # Detect whether the player roster changed (additions, removals, or replacements).
    # Rankings are only re-fetched when the roster changes — not on every match-result sync.
    incoming_positions = {pe.bracket_position for pe in parsed.players}
    roster_changed = (
        incoming_positions != set(existing_players.keys())
        or any(
            pe.name != existing_players[pe.bracket_position].name
            for pe in parsed.players
            if pe.bracket_position in existing_players
        )
    )

    # Upsert players — update in place to preserve any FK references
    pos_to_player_id: dict[int, int] = {}
    seen_positions: set[int] = set()
    upserted_players: list[DrawEntry] = []
    for pe in parsed.players:
        seen_positions.add(pe.bracket_position)
        if pe.bracket_position in existing_players:
            player = existing_players[pe.bracket_position]
            if player.name != pe.name:
                # Name changed (withdrawal/replacement) — re-match on next
                # assign_rankings. The slug has to go with the id: left behind,
                # it points the H2H panel at the player who was replaced.
                player.te_player_id = None
                player.te_slug = None
            player.name = pe.name
            player.nationality = pe.nationality
            player.seed = pe.seed
            player.entry_type = pe.entry_type
        else:
            player = DrawEntry(
                draw_id=tournament.id,
                name=pe.name,
                nationality=pe.nationality,
                seed=pe.seed,
                entry_type=pe.entry_type,
                bracket_position=pe.bracket_position,
            )
            db.add(player)
            await db.flush()
        pos_to_player_id[pe.bracket_position] = player.id
        upserted_players.append(player)

    if roster_changed:
        try:
            ref_date = tournament.entry_ranking_week or tournament.start_date or date.today()
            await assign_rankings(upserted_players, tournament.gender, ref_date, db)
            logger.info("Roster change in %s — rankings assigned", tournament.name)
        except Exception as exc:
            logger.warning("Could not assign rankings for %s: %s", tournament.name, exc)

    # Delete players no longer in draw
    for pos, old_player in existing_players.items():
        if pos not in seen_positions:
            await db.delete(old_player)
    await db.flush()

    # Upsert matches — update in place to preserve prediction foreign keys
    seen_match_keys: set[tuple] = set()
    for mr in parsed.matches:
        p1_id = pos_to_player_id.get(mr.player1_position)
        p2_id = pos_to_player_id.get(mr.player2_position) if mr.player2_position else None
        w_id = pos_to_player_id.get(mr.winner_position) if mr.winner_position else None
        key = (mr.round_number, mr.match_number)
        seen_match_keys.add(key)
        if key in existing_matches:
            match = existing_matches[key]
            match.player1_id = p1_id
            match.player2_id = p2_id
            match.is_bye = mr.is_bye
            if w_id is not None:
                # Wikipedia has a result — always trust it (includes tiebreak scores)
                if match.winner_id != w_id:
                    # Only stamp completed_at if ESPN hasn't already recorded it;
                    # ESPN timestamps are more accurate (per-match, within 1 min).
                    if match.completed_at is None:
                        match.completed_at = datetime.now(timezone.utc)
                match.winner_id = w_id
                match.status = "completed"
                match.scores_json = mr.scores
                match.live_scores_json = None
            elif match.winner_id is None:
                # No result from either source — update scores/status normally
                match.completed_at = None
                match.scores_json = mr.scores
                match.status = "pending"
        else:
            match = Match(
                draw_id=tournament.id,
                round_number=mr.round_number,
                match_number=mr.match_number,
                player1_id=p1_id,
                player2_id=p2_id,
                winner_id=w_id,
                is_bye=mr.is_bye,
                scores_json=mr.scores,
                status="completed" if w_id else "pending",
                completed_at=datetime.now(timezone.utc) if w_id else None,
            )
            db.add(match)

    # Delete matches no longer in draw (and their orphaned predictions)
    from app.models.prediction import UserPrediction
    for key, old_match in existing_matches.items():
        if key not in seen_match_keys:
            orphaned = await db.execute(
                select(UserPrediction).where(UserPrediction.match_id == old_match.id)
            )
            for pred in orphaned.scalars():
                await db.delete(pred)
            await db.delete(old_match)

    # Auto-set tournament status
    from datetime import date as _date
    today = _date.today()
    total_matches = len(parsed.matches)
    completed = sum(1 for m in parsed.matches if m.winner_position is not None)

    # Byes resolve the instant the draw is released — no match is actually
    # played — so they must NOT count as "activity" or the tournament would
    # show active/started before a single real match has begun (any draw with
    # first-round byes for top seeds hits this immediately on release).
    real_completed = sum(1 for m in parsed.matches if m.winner_position is not None and not m.is_bye)

    # Snap start_date to today on first detected REAL match activity.
    # Qualifying rounds begin before the Wikipedia-reported main-draw start date,
    # so use the real play date rather than Wikipedia's potentially lagging value.
    # Guard: only snap after the main draw is released — otherwise qualifying activity
    # would prematurely move the start_date forward by a week or more.
    has_activity = real_completed > 0 or any(m.scores for m in parsed.matches if not m.is_bye)
    if (has_activity and tournament.start_date and today < tournament.start_date
            and tournament.draw_released_direct_at is not None):
        tournament.start_date = today

    started = tournament.start_date is None or tournament.start_date <= today
    if completed == total_matches and completed > 0:
        tournament.status = "completed"
    elif real_completed > 0 and started:
        tournament.status = "active"
    else:
        tournament.status = "upcoming"
