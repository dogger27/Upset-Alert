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
    LeagueMemberOut,
    LeagueTournamentOut,
    LeagueOut,
    LeagueUpdate,
)
from app.schemas.tournament import TournamentOut
from app.services.scoring import rank_users, score_user

router = APIRouter(prefix="/leagues", tags=["leagues"])


def _with_users(members) -> list:
    """Return LeagueMemberOut objects including is_admin flag."""
    out = []
    for m in members:
        if not (hasattr(m, "user") and m.user is not None):
            continue
        out.append(LeagueMemberOut(
            id=m.user.id,
            username=m.user.username,
            display_name=m.user.display_name,
            email=m.user.email,
            is_admin=bool(m.is_admin),
        ))
    return out


def _league_out(league: League, member_count: int = 0) -> LeagueOut:
    return LeagueOut(
        id=league.id,
        name=league.name,
        scoring_mode=league.scoring_mode,
        custom_points=league.custom_points,
        is_public=league.is_public,
        show_real_name=league.show_real_name,
        allow_member_invites=league.allow_member_invites,
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
    """Return public leagues plus the current user's private leagues. Admins see all leagues."""
    if current_user and current_user.is_admin:
        stmt = (
            select(League)
            .options(selectinload(League.owner), selectinload(League.members).selectinload(LeagueMember.user))
        )
    elif current_user:
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
    else:
        stmt = (
            select(League)
            .options(selectinload(League.owner), selectinload(League.members).selectinload(LeagueMember.user))
            .where(League.is_public == True)
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
    league = League(
        name=body.name,
        owner_id=current_user.id,
        scoring_mode="classic",
        is_public=body.is_public,
        show_real_name=body.show_real_name,
        allow_member_invites=body.allow_member_invites,
    )
    db.add(league)
    await db.flush()

    # Owner is automatically a member and admin
    db.add(LeagueMember(league_id=league.id, user_id=current_user.id, is_admin=True))
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


@router.delete("/{league_id}", status_code=204)
async def delete_league(
    league_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = await db.get(League, league_id)
    if not league:
        raise HTTPException(404, "League not found")
    if league.owner_id != current_user.id:
        raise HTTPException(403, "Only the league owner can delete this league")
    await db.delete(league)
    await db.commit()


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
    if body.is_public is not None:
        league.is_public = body.is_public
    if body.show_real_name is not None:
        league.show_real_name = body.show_real_name
    if body.allow_member_invites is not None:
        league.allow_member_invites = body.allow_member_invites

    await db.commit()
    await db.refresh(league)
    return _league_out(league, len(league.members))


@router.post("/join", status_code=204)
async def join_league_by_code(
    invite_code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(League).where(League.invite_code == invite_code))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(404, "Invalid invite code")

    existing = await db.execute(
        select(LeagueMember).where(
            LeagueMember.league_id == league.id,
            LeagueMember.user_id == current_user.id,
        )
    )
    if existing.scalar_one_or_none():
        return  # already a member

    db.add(LeagueMember(league_id=league.id, user_id=current_user.id))
    await db.commit()


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


@router.put("/{league_id}/members/{user_id}/admin", status_code=204)
async def set_member_admin(
    league_id: int,
    user_id: int,
    is_admin: bool,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(League)
        .options(selectinload(League.members))
        .where(League.id == league_id)
    )
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(404, "League not found")

    caller = next((m for m in league.members if m.user_id == current_user.id), None)
    if not caller or not caller.is_admin:
        raise HTTPException(403, "Only admins can change admin status")

    if user_id == league.owner_id:
        raise HTTPException(400, "Cannot change the league owner's admin status")

    target = next((m for m in league.members if m.user_id == user_id), None)
    if not target:
        raise HTTPException(404, "Member not found")

    target.is_admin = is_admin
    await db.commit()


@router.delete("/{league_id}/members/{user_id}", status_code=204)
async def remove_member(
    league_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(League)
        .options(selectinload(League.members))
        .where(League.id == league_id)
    )
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(404, "League not found")

    caller = next((m for m in league.members if m.user_id == current_user.id), None)
    if not caller or not caller.is_admin:
        raise HTTPException(403, "Only admins can remove members")

    if user_id == league.owner_id:
        raise HTTPException(400, "Cannot remove the league owner")

    target = next((m for m in league.members if m.user_id == user_id), None)
    if not target:
        raise HTTPException(404, "Member not found")

    await db.delete(target)
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
        .options(selectinload(League.owner), selectinload(League.members).selectinload(LeagueMember.user))
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

    # Only include members who have submitted a complete bracket
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


@router.get("/{league_id}/round-scores")
async def round_scores(
    league_id: int,
    tournament_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Per-round point breakdown for each league member in a tournament."""
    from collections import defaultdict
    from app.services.scoring import _points_table

    result = await db.execute(
        select(League)
        .options(selectinload(League.members).selectinload(LeagueMember.user))
        .where(League.id == league_id)
    )
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(404, "League not found")
    _check_access(league, current_user)

    tournament = await db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(404, "Tournament not found")

    pts_table = _points_table(tournament)

    completed_matches_result = await db.execute(
        select(Match).where(
            Match.tournament_id == tournament_id,
            Match.status == "completed",
            Match.is_bye == False,
        )
    )
    completed_matches = completed_matches_result.scalars().all()

    entries = []
    for member in league.members:
        preds_result = await db.execute(
            select(UserPrediction).where(
                UserPrediction.user_id == member.user_id,
                UserPrediction.tournament_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        preds = preds_result.scalars().all()
        if not preds:
            continue

        pred_by_match = {p.match_id: p.predicted_winner_id for p in preds}
        by_round: dict = defaultdict(float)

        for match in completed_matches:
            if match.winner_id is None:
                continue
            if pred_by_match.get(match.id) != match.winner_id:
                continue
            by_round[match.round_number] += pts_table.get(match.round_number, 0)

        pts_list = [by_round.get(r, 0) for r in range(1, 8)]
        entries.append({
            "user_id": member.user_id,
            "username": member.user.username,
            "full_name": member.user.full_name,
            "round_points": pts_list,
            "total": sum(pts_list),
        })

    entries.sort(key=lambda x: -x["total"])
    return entries


def _check_access(league: League, user: Optional[User]) -> None:
    if league.is_public:
        return
    if user is None:
        raise HTTPException(403, "Login required to view this private league")
    if user.is_admin:
        return
    is_member = any(m.user_id == user.id for m in league.members)
    if not is_member and league.owner_id != user.id:
        raise HTTPException(403, "You are not a member of this league")
