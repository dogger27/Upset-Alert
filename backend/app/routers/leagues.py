from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user, get_optional_user
from app.database import get_db
from app.models.league import League, LeagueMember
from app.models.prediction import UserPrediction
from app.models.tournament import Match, Tournament
from app.models.user import User
from app.schemas.league import (
    LeaderboardEntry,
    LeaderboardOut,
    LeagueCreate,
    LeagueTournamentOut,
    LeagueOut,
    LeagueUpdate,
)
from app.schemas.tournament import TournamentOut
from app.services.scoring import rank_users, score_user

router = APIRouter(prefix="/leagues", tags=["leagues"])


def _with_users(members) -> list:
    """Return member User objects for those where the user relationship is loaded."""
    return [m.user for m in members if hasattr(m, "user") and m.user is not None]


def _league_out(league: League, member_count: int = 0) -> LeagueOut:
    return LeagueOut(
        id=league.id,
        name=league.name,
        scoring_mode=league.scoring_mode,
        custom_points=league.custom_points,
        is_public=league.is_public,
        invite_code=league.invite_code,
        created_at=league.created_at,
        owner=league.owner,
        member_count=member_count,
        members=_with_users(league.members),
    )


@router.get("", response_model=list[LeagueOut])
async def list_leagues(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Return public leagues plus the current user's private leagues."""
    stmt = (
        select(League)
        .options(selectinload(League.owner), selectinload(League.members).selectinload(LeagueMember.user))
        .where(League.is_public == True)
    )
    if current_user:
        from sqlalchemy import or_
        stmt = (
            select(League)
            .options(selectinload(League.owner), selectinload(League.members).selectinload(LeagueMember.user))
            .join(LeagueMember, LeagueMember.league_id == League.id, isouter=True)
            .where(
                or_(
                    League.is_public == True,
                    League.owner_id == current_user.id,
                    LeagueMember.user_id == current_user.id,
                )
            )
            .distinct()
        )
    result = await db.execute(stmt)
    leagues = result.scalars().all()
    return [_league_out(lg, len(lg.members)) for lg in leagues]


@router.post("", response_model=LeagueOut, status_code=201)
async def create_league(
    body: LeagueCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.scoring_mode not in ("classic", "atp_wta", "upset_bonus", "custom"):
        raise HTTPException(400, "Invalid scoring_mode")
    if body.scoring_mode == "custom" and not body.custom_points:
        raise HTTPException(400, "custom_points required for custom scoring mode")

    league = League(
        name=body.name,
        owner_id=current_user.id,
        scoring_mode=body.scoring_mode,
        custom_points=body.custom_points,
        is_public=body.is_public,
    )
    db.add(league)
    await db.flush()

    # Owner is automatically a member
    db.add(LeagueMember(league_id=league.id, user_id=current_user.id))
    await db.commit()

    await db.refresh(league)
    result = await db.execute(
        select(League)
        .options(selectinload(League.owner), selectinload(League.members).selectinload(LeagueMember.user))
        .where(League.id == league.id)
    )
    league = result.scalar_one()
    return _league_out(league, len(league.members))


@router.get("/{league_id}", response_model=LeagueOut)
async def get_league(
    league_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    result = await db.execute(
        select(League)
        .options(selectinload(League.owner), selectinload(League.members).selectinload(LeagueMember.user))
        .where(League.id == league_id)
    )
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(404, "League not found")
    _check_access(league, current_user)
    return _league_out(league, len(league.members))


@router.put("/{league_id}", response_model=LeagueOut)
async def update_league(
    league_id: int,
    body: LeagueUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(League)
        .options(selectinload(League.owner), selectinload(League.members).selectinload(LeagueMember.user))
        .where(League.id == league_id)
    )
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(404, "League not found")
    if league.owner_id != current_user.id:
        raise HTTPException(403, "Only the league owner can update settings")

    if body.name is not None:
        league.name = body.name
    if body.scoring_mode is not None:
        league.scoring_mode = body.scoring_mode
    if body.custom_points is not None:
        league.custom_points = body.custom_points
    if body.is_public is not None:
        league.is_public = body.is_public

    await db.commit()
    await db.refresh(league)
    return _league_out(league, len(league.members))


@router.post("/{league_id}/join", status_code=204)
async def join_league(
    league_id: int,
    invite_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = await db.get(League, league_id)
    if not league:
        raise HTTPException(404, "League not found")
    if not league.is_public and league.invite_code != invite_code:
        raise HTTPException(403, "Invalid invite code")

    existing = await db.execute(
        select(LeagueMember).where(
            LeagueMember.league_id == league_id,
            LeagueMember.user_id == current_user.id,
        )
    )
    if existing.scalar_one_or_none():
        return  # already a member

    db.add(LeagueMember(league_id=league_id, user_id=current_user.id))
    await db.commit()


@router.get("/{league_id}/tournaments", response_model=list[LeagueTournamentOut])
async def league_tournaments(
    league_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Return tournaments where at least one league member has submitted picks, with pick counts."""
    result = await db.execute(
        select(League)
        .options(selectinload(League.members).selectinload(LeagueMember.user))
        .where(League.id == league_id)
    )
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(404, "League not found")
    _check_access(league, current_user)

    member_ids = [m.user_id for m in league.members]
    if not member_ids:
        return []

    # Count non-null picks per (user, tournament)
    picks_result = await db.execute(
        select(
            UserPrediction.tournament_id,
            UserPrediction.user_id,
            func.count().label("pick_count"),
        )
        .where(
            UserPrediction.user_id.in_(member_ids),
            UserPrediction.predicted_winner_id.isnot(None),
        )
        .group_by(UserPrediction.tournament_id, UserPrediction.user_id)
    )
    picks_rows = picks_result.all()

    # Find all relevant tournament IDs
    t_ids = list({r.tournament_id for r in picks_rows})
    if not t_ids:
        return []

    # Total non-bye matches per tournament
    totals_result = await db.execute(
        select(Match.tournament_id, func.count().label("total"))
        .where(Match.tournament_id.in_(t_ids), Match.is_bye == False)
        .group_by(Match.tournament_id)
    )
    total_by_t = {r.tournament_id: r.total for r in totals_result.all()}

    # Count members who have picks for ALL non-bye matches
    from collections import defaultdict
    fully_entered = defaultdict(int)
    for r in picks_rows:
        if r.pick_count >= total_by_t.get(r.tournament_id, 0) > 0:
            fully_entered[r.tournament_id] += 1

    out = []
    for t_id, picker_count in fully_entered.items():
        t = await db.get(Tournament, t_id)
        if t:
            t.status = t.computed_status
            out.append(LeagueTournamentOut(
                tournament=TournamentOut.model_validate(t),
                picker_count=picker_count,
            ))

    # Sort: active first, then open, upcoming, completed; within group by start_date desc
    _status_order = {"active": 0, "open": 1, "upcoming": 2, "completed": 3}
    from datetime import date as _date
    out.sort(key=lambda x: (
        _status_order.get(x.tournament.status, 9),
        -(x.tournament.start_date.toordinal() if x.tournament.start_date else 0),
    ))
    return out


@router.get("/{league_id}/leaderboard", response_model=LeaderboardOut)
async def leaderboard(
    league_id: int,
    tournament_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    result = await db.execute(
        select(League)
        .options(selectinload(League.owner), selectinload(League.members).selectinload(LeagueMember.user).selectinload(LeagueMember.user))
        .where(League.id == league_id)
    )
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(404, "League not found")
    _check_access(league, current_user)

    if tournament_id is None:
        # No tournament selected — return all members with zero scores (roster view)
        entries = [
            LeaderboardEntry(
                rank=i + 1,
                user=member.user,
                total_points=0,
                correct_count=0,
                champion_correct=False,
                finalist_correct=False,
            )
            for i, member in enumerate(league.members)
        ]
        return LeaderboardOut(league=_league_out(league, len(league.members)), entries=entries)

    tournament = await db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(404, "Tournament not found")

    completed_matches_result = await db.execute(
        select(Match)
        .options(
            selectinload(Match.player1),
            selectinload(Match.player2),
            selectinload(Match.winner),
        )
        .where(Match.tournament_id == tournament_id, Match.status == "completed")
    )
    completed_matches = completed_matches_result.scalars().all()

    # Total non-bye matches — a member must have a pick for every one to be entered
    total_matches_result = await db.execute(
        select(func.count())
        .where(Match.tournament_id == tournament_id, Match.is_bye == False)
    )
    total_matches = total_matches_result.scalar_one()

    # Only include members who have picks for ALL non-bye matches
    scores = []
    for member in league.members:
        preds_result = await db.execute(
            select(UserPrediction).where(
                UserPrediction.user_id == member.user_id,
                UserPrediction.tournament_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        preds = preds_result.scalars().all()
        if len(preds) < total_matches:
            continue
        score = score_user(member.user_id, preds, completed_matches, tournament, league)
        scores.append((member.user, score))

    ranked = rank_users([s for _, s in scores])
    user_map = {u.id: u for u, _ in scores}

    entries = [
        LeaderboardEntry(
            rank=rank_idx,
            user=user_map[score.user_id],
            total_points=score.total_points,
            correct_count=score.correct_count,
            champion_correct=score.champion_correct,
            finalist_correct=score.finalist_correct,
        )
        for rank_idx, score in enumerate(ranked, start=1)
    ]

    return LeaderboardOut(
        league=_league_out(league, len(league.members)),
        entries=entries,
    )


def _check_access(league: League, user: Optional[User]) -> None:
    if league.is_public:
        return
    if user is None:
        raise HTTPException(403, "Login required to view this private league")
    is_member = any(m.user_id == user.id for m in league.members)
    if not is_member and league.owner_id != user.id:
        raise HTTPException(403, "You are not a member of this league")
