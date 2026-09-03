from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user, get_optional_user
from app.database import get_db
from app.models.league import League, LeagueMember
from app.models.cash_pool import LeagueCashPool, LeagueCashPoolMember
from app.services.system_log import app_log
from app.models.prediction import UserPrediction
from app.models.tournament import DrawEntry, Match, Draw
from app.models.user import User
from app.schemas.league import (
    LeaderboardEntry,
    LeaderboardOut,
    LeagueCreate,
    LeagueMemberOut,
    LeagueTournamentOut,
    LeagueOut,
    LeagueUpdate,
    CashPoolIn, CashPoolOut,
)
from app.schemas.tournament import TournamentOut
from app.services.scoring import rank_users, score_user
from app.services.upsets import has_upset_pick

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
            full_name=m.user.full_name,
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


async def _can_manage(db, league, user) -> bool:
    """Who runs a league: its owner, any member it made admin, or a site
    admin. One answer for update and delete — the settings panel is one
    surface, and a person who can reach it can use all of it."""
    if league.owner_id == user.id or user.is_admin:
        return True
    m = (await db.execute(
        select(LeagueMember).where(LeagueMember.league_id == league.id,
                                   LeagueMember.user_id == user.id))).scalar_one_or_none()
    return bool(m and m.is_admin)


async def _pool_of(db, league_id: int, draw_id: int) -> Optional[LeagueCashPool]:
    return (await db.execute(
        select(LeagueCashPool).where(LeagueCashPool.league_id == league_id,
                                     LeagueCashPool.draw_id == draw_id))).scalar_one_or_none()


async def _pool_visible(db, league_id: int, draw_id: int) -> Optional[set[int]]:
    """WHO THE LEAGUE'S VIEWS OF THIS DRAW SHOW. None means everyone — no pool,
    or a pool switched off. A set means only these members: the ones who paid
    in. Everyone else is invisible in this draw for this league, and only
    here — the members list and the global standings are not the league's
    view of a draw."""
    pool = await _pool_of(db, league_id, draw_id)
    if pool is None or not pool.enabled:
        return None
    return {m.user_id for m in pool.members}


def _pool_out(pool: Optional[LeagueCashPool], draw_id: int) -> CashPoolOut:
    if pool is None:
        return CashPoolOut(draw_id=draw_id)
    return CashPoolOut(draw_id=pool.draw_id, enabled=bool(pool.enabled),
                       paid_user_ids=sorted(m.user_id for m in pool.members))


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
    if not await _can_manage(db, league, current_user):
        raise HTTPException(403, "Only a league admin can delete this league")
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
    if not await _can_manage(db, league, current_user):
        raise HTTPException(403, "Only a league admin can update settings")

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
    from app.services.email import send_member_joined
    invite_code = invite_code.strip().upper()
    result = await db.execute(
        select(League).options(selectinload(League.owner)).where(League.invite_code == invite_code)
    )
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

    if league.owner_id != current_user.id:
        from app.models.notification import NotificationPreference
        pref = await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == league.owner_id,
                NotificationPreference.pref_key == "league_member_joined",
            )
        )
        if pref.scalar_one_or_none():
            await send_member_joined(
                owner_email=league.owner.email,
                owner_username=league.owner.username,
                league_name=league.name,
                league_id=league.id,
                new_username=current_user.username,
                new_full_name=current_user.full_name,
            )

        # Push is opted into separately from the email, so it is checked on its
        # own rather than nested under the email preference above.
        try:
            from app.services.push import send_push_to_users, users_with_push
            if league.owner_id in await users_with_push("league_member_joined"):
                # Built by push_content, not inline. This call site had its own
                # copy of the wording, which made push_content.league_join dead
                # code and left the "send me a test" button unable to reproduce
                # the notification it claims to preview.
                from app.services import push_content
                await send_push_to_users(
                    [league.owner_id],
                    **push_content.league_join(
                        current_user.username, league.name, league.id
                    ),
                )
        except Exception:
            import logging
            logging.getLogger(__name__).warning("League-join push failed", exc_info=True)


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
    if not current_user.is_admin and (not caller or not caller.is_admin):
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
    if not current_user.is_admin and (not caller or not caller.is_admin):
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
            UserPrediction.draw_id,
            UserPrediction.user_id,
            func.count().label("pick_count"),
        )
        .where(
            UserPrediction.user_id.in_(member_ids),
            UserPrediction.predicted_winner_id.isnot(None),
        )
        .group_by(UserPrediction.draw_id, UserPrediction.user_id)
    )
    picks_rows = picks_result.all()

    # Find all relevant tournament IDs
    t_ids = list({r.draw_id for r in picks_rows})
    if not t_ids:
        return []

    # The league's cash pools, one query: a draw with one switched on counts
    # only its paid members as entered, and the tile says so.
    pools = {p.draw_id: p for p in (await db.execute(
        select(LeagueCashPool).where(LeagueCashPool.league_id == league.id,
                                     LeagueCashPool.draw_id.in_(t_ids)))).scalars().all()}

    # Count members competing in each draw — one pick is enough to be entered.
    from collections import defaultdict
    entered = defaultdict(int)
    for r in picks_rows:
        if r.pick_count > 0:
            pool = pools.get(r.draw_id)
            if pool is not None and pool.enabled and r.user_id not in {m.user_id for m in pool.members}:
                continue
            entered[r.draw_id] += 1

    out = []
    for t_id, picker_count in entered.items():
        t = await db.get(Draw, t_id)
        if t:
            t.status = t.computed_status
            pool = pools.get(t_id)
            out.append(LeagueTournamentOut(
                tournament=TournamentOut.model_validate(t),
                picker_count=picker_count,
                cash_pool_enabled=bool(pool and pool.enabled),
                cash_pool_paid_ids=sorted(m.user_id for m in pool.members) if pool else [],
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
            )
            for i, member in enumerate(league.members)
        ]
        return LeaderboardOut(league=_league_out(league, len(league.members)), entries=entries, total_matches=0)

    tournament = await db.get(Draw, tournament_id)
    if not tournament:
        raise HTTPException(404, "Tournament not found")

    completed_matches_result = await db.execute(
        select(Match)
        .options(
            selectinload(Match.player1),
            selectinload(Match.player2),
            selectinload(Match.winner),
        )
        # is_bye excluded: a bye has no contest to predict, and scoring it awards
        # free points to any stray pick sitting on that row.
        .where(Match.draw_id == tournament_id, Match.status == "completed",
               Match.is_bye == False)  # noqa: E712
    )
    completed_matches = completed_matches_result.scalars().all()

    # Total non-bye matches in the draw — reported to the frontend as the
    # denominator for progress, not as an entry requirement.
    total_matches_result = await db.execute(
        select(func.count())
        .where(Match.draw_id == tournament_id, Match.is_bye == False)
    )
    total_matches = total_matches_result.scalar_one()

    # All matches (not just completed) + draw entries — needed to determine
    # whether a member's picks include at least one upset (a member must pick
    # at least one to count as "participating"), which requires resolving
    # every round's entrants, not just ones already decided.
    all_matches_result = await db.execute(
        select(Match).where(Match.draw_id == tournament_id)
    )
    all_matches = all_matches_result.scalars().all()
    all_entries_result = await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == tournament_id)
    )
    all_entries = all_entries_result.scalars().all()

    # Members with at least one pick are included and ranked together. A
    # partial bracket is still a competing entry — it simply forfeits points on
    # the matches left unpicked. The only bar to competing is picking zero
    # upsets (has_upset_pick below). Members with zero picks are excluded.
    # So is anyone outside the draw's cash pool, when the league runs one.
    visible = await _pool_visible(db, league.id, tournament_id)
    scores = []
    has_upset_map: dict[int, bool] = {}
    for member in league.members:
        if visible is not None and member.user_id not in visible:
            continue
        preds_result = await db.execute(
            select(UserPrediction).where(
                UserPrediction.user_id == member.user_id,
                UserPrediction.draw_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        preds = preds_result.scalars().all()
        if len(preds) == 0:
            continue
        scores.append((member.user, score_user(member.user_id, preds, completed_matches, tournament, league)))
        has_upset_map[member.user_id] = has_upset_pick(preds, all_matches, all_entries)

    ranked = rank_users([s for _, s in scores], tournament.num_rounds)
    user_map = {u.id: u for u, _ in scores}

    entries = [
        LeaderboardEntry(
            rank=rank_idx,
            user=user_map[score.user_id],
            total_points=score.total_points,
            correct_count=score.correct_count,
            has_upset_pick=has_upset_map[score.user_id],
        )
        for rank_idx, score in enumerate(ranked, start=1)
    ]

    def _is_upset(match) -> bool:
        if match.winner_id is None or match.is_bye:
            return False
        winner = match.player1 if match.winner_id == match.player1_id else match.player2
        loser = match.player2 if match.winner_id == match.player1_id else match.player1
        if winner is None or loser is None:
            return False
        # Seeded players always rank above unseeded (mirrors frontend computeDrawRanks)
        if loser.seed is not None and winner.seed is None:
            return True   # unseeded beats seeded
        if winner.seed is not None and loser.seed is None:
            return False  # seeded beats unseeded
        if winner.seed is not None and loser.seed is not None:
            return winner.seed > loser.seed
        # Both unseeded: compare ATP/WTA rankings
        if winner.ranking is None or loser.ranking is None:
            return False
        return winner.ranking > loser.ranking

    upset_count = sum(1 for m in completed_matches if _is_upset(m))
    completed_matches_count = len([m for m in completed_matches if not m.is_bye])

    return LeaderboardOut(
        league=_league_out(league, len(league.members)),
        entries=entries,
        total_matches=total_matches,
        upset_count=upset_count,
        completed_matches_count=completed_matches_count,
    )


@router.get("/{league_id}/grand-slam-totals")
async def grand_slam_totals(
    league_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Total Grand Slam pick points this year per member, split by ATP/WTA."""
    from datetime import date
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

    year = date.today().year
    gs_result = await db.execute(
        select(Draw).where(Draw.year == year, Draw.category.ilike('%grand slam%'))
    )
    gs_draws = gs_result.scalars().all()

    member_ids = [m.user_id for m in league.members]
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

        for user_id in member_ids:
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
            "user_id": mem.user_id,
            "username": mem.user.username,
            "full_name": mem.user.full_name,
            "atp_points": int(atp[mem.user_id]),
            "wta_points": int(wta[mem.user_id]),
        }
        for mem in league.members
    ]
    entries.sort(key=lambda x: -(x["atp_points"] + x["wta_points"]))
    return {"year": year, "members": entries}


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

    timeline_ids = {m.id for m in completed_matches}
    user_predictions: dict = {}
    entries = []
    # A cash pool on this draw hides everyone who did not pay in.
    visible = await _pool_visible(db, league.id, tournament_id)
    for member in league.members:
        if visible is not None and member.user_id not in visible:
            continue
        preds_result = await db.execute(
            select(UserPrediction).where(
                UserPrediction.user_id == member.user_id,
                UserPrediction.draw_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        preds = preds_result.scalars().all()
        if not preds:
            continue

        pred_by_match = {p.match_id: p.predicted_winner_id for p in preds}
        user_predictions[str(member.user_id)] = {str(k): v for k, v in pred_by_match.items() if k in timeline_ids}
        by_round: dict = defaultdict(float)
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
            "user_id": member.user_id,
            "username": member.user.username,
            "full_name": member.user.full_name,
            "round_points": pts_list,
            "total": sum(pts_list),
            "correct_count": correct_count,
        })

    # Primary: total points desc. Tiebreaker: points in latest rounds first (Final → SF → QF → …)
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


@router.get("/{league_id}/cash-pools", response_model=list[CashPoolOut])
async def cash_pools(
    league_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Every cash pool this league has ever configured, one per draw."""
    league = await db.get(League, league_id)
    if not league:
        raise HTTPException(404, "League not found")
    _check_access(league, current_user)
    pools = (await db.execute(
        select(LeagueCashPool).where(LeagueCashPool.league_id == league_id))).scalars().all()
    return [_pool_out(p, p.draw_id) for p in pools]


@router.put("/{league_id}/cash-pools/{draw_id}", response_model=CashPoolOut)
async def set_cash_pool(
    league_id: int,
    draw_id: int,
    body: CashPoolIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Switch the league's cash pool on this draw on or off and say who paid.
    League owner, league admin or site admin — the same people who run the
    league's settings."""
    result = await db.execute(
        select(League).options(selectinload(League.members)).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(404, "League not found")
    if not await _can_manage(db, league, current_user):
        raise HTTPException(403, "Only a league admin can manage the cash pool")
    if not await db.get(Draw, draw_id):
        raise HTTPException(404, "Draw not found")
    member_ids = {m.user_id for m in league.members}
    paid = sorted({int(u) for u in body.paid_user_ids} & member_ids)

    # Explicit statements, not the relationship: assigning `pool.members` on a
    # row this session just created lazy-loads the old collection first, and
    # a lazy load inside an async session is a MissingGreenlet — see
    # feedback_sqlalchemy_async_rollback.
    pool = await _pool_of(db, league_id, draw_id)
    if pool is None:
        pool = LeagueCashPool(league_id=league_id, draw_id=draw_id, enabled=False)
        db.add(pool)
        await db.flush()
        before = (False, [])
    else:
        before = (bool(pool.enabled), sorted(m.user_id for m in pool.members))
    pool.enabled = bool(body.enabled)
    pool.updated_by = current_user.id
    await db.execute(delete(LeagueCashPoolMember).where(LeagueCashPoolMember.pool_id == pool.id))
    db.add_all([LeagueCashPoolMember(pool_id=pool.id, user_id=u) for u in paid])
    await db.commit()
    db.expunge_all()
    pool = await _pool_of(db, league_id, draw_id)   # fresh, members eagerly loaded
    if before != (pool.enabled, paid):
        await app_log("info", "leagues",
                      f"cash pool league={league_id} draw={draw_id} "
                      f"{'ON' if pool.enabled else 'off'} paid={len(paid)}/{len(member_ids)} "
                      f"by user {current_user.id}")
    return _pool_out(pool, draw_id)


@router.post("/{league_id}/share-email")
async def share_league_by_email(
    league_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Invite people by email. For each address:
    - Existing user not in league → add to league + send "you've been added" email
    - Existing user already in league → skip
    - No account → send "create account + invite code" email
    """
    from app.services.email import send_league_added_existing, send_league_invite_new_user
    from app.services.system_log import app_log

    result = await db.execute(
        select(League)
        .options(selectinload(League.members))
        .where(League.id == league_id)
    )
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(404, "League not found")

    caller_member = next((m for m in league.members if m.user_id == current_user.id), None)
    is_owner = league.owner_id == current_user.id
    if not caller_member and not is_owner:
        raise HTTPException(403, "You are not a member of this league")
    if not is_owner and not league.allow_member_invites:
        raise HTTPException(403, "Only the league owner can invite members")

    raw = body.get("emails", "")
    emails = [e.strip().lower() for e in raw.replace(",", "\n").splitlines() if e.strip()]
    if not emails:
        raise HTTPException(400, "No email addresses provided")

    member_ids = {m.user_id for m in league.members}
    results = []

    for email in emails:
        user_res = await db.execute(select(User).where(User.email == email))
        found = user_res.scalar_one_or_none()

        if found:
            if found.id in member_ids:
                results.append({"email": email, "status": "already_member", "username": found.username})
                continue
            db.add(LeagueMember(league_id=league_id, user_id=found.id))
            await db.flush()
            member_ids.add(found.id)
            await send_league_added_existing(
                to_email=email,
                username=found.username,
                added_by_username=current_user.username,
                league_name=league.name,
                league_id=league_id,
            )
            results.append({"email": email, "status": "added", "username": found.username})
        else:
            await send_league_invite_new_user(
                to_email=email,
                invited_by_username=current_user.username,
                league_name=league.name,
                invite_code=league.invite_code,
            )
            results.append({"email": email, "status": "invited"})

    await db.commit()
    await app_log(
        "info", "leagues",
        f"{current_user.username} shared '{league.name}' to {len(emails)} email(s)",
        {"league_id": league_id, "results": results},
    )
    return {"results": results}


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
