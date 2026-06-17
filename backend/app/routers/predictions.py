from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_user
from app.database import get_db
from app.models.prediction import UserPrediction
from app.models.tournament import Match, Tournament
from app.models.user import User
from app.schemas.prediction import PredictionOut, PredictionSet

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("/entry-status", response_model=dict[int, str])
async def get_entry_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns {tournament_id: 'complete' | 'partial'} for tournaments with at least one pick."""
    totals_result = await db.execute(
        select(Match.tournament_id, func.count().label("total"))
        .where(Match.is_bye == False)
        .group_by(Match.tournament_id)
    )
    total_by_t = {r.tournament_id: r.total for r in totals_result}

    picks_result = await db.execute(
        select(UserPrediction.tournament_id, func.count().label("pick_count"))
        .where(
            UserPrediction.user_id == current_user.id,
            UserPrediction.predicted_winner_id.isnot(None),
        )
        .group_by(UserPrediction.tournament_id)
    )
    picks_by_t = {r.tournament_id: r.pick_count for r in picks_result}

    result = {}
    for t_id, total in total_by_t.items():
        count = picks_by_t.get(t_id, 0)
        if count == 0:
            continue
        result[t_id] = "complete" if count >= total else "partial"
    return result


@router.get("/{tournament_id}", response_model=list[PredictionOut])
async def get_predictions(
    tournament_id: int,
    user_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    uid = user_id if user_id is not None else (current_user.id if current_user else None)
    if uid is None:
        raise HTTPException(401, "Not authenticated")
    result = await db.execute(
        select(UserPrediction).where(
            UserPrediction.user_id == uid,
            UserPrediction.tournament_id == tournament_id,
        )
    )
    return result.scalars().all()


@router.put("/{tournament_id}", response_model=list[PredictionOut])
async def save_predictions(
    tournament_id: int,
    body: PredictionSet,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tournament = await db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(404, "Tournament not found")
    if tournament.is_locked:
        raise HTTPException(403, "Predictions are locked — the tournament has started")

    # Validate that all match IDs belong to this tournament
    match_ids = list(body.picks.keys())
    if match_ids:
        result = await db.execute(
            select(Match.id).where(
                Match.id.in_(match_ids),
                Match.tournament_id == tournament_id,
            )
        )
        valid_ids = set(result.scalars().all())
        invalid = set(match_ids) - valid_ids
        if invalid:
            raise HTTPException(400, f"Unknown match IDs: {invalid}")

    # Upsert predictions; null winner_id means the pick was cleared
    for match_id, winner_id in body.picks.items():
        existing = await db.execute(
            select(UserPrediction).where(
                UserPrediction.user_id == current_user.id,
                UserPrediction.match_id == match_id,
            )
        )
        pred = existing.scalar_one_or_none()
        if winner_id is None:
            if pred:
                await db.delete(pred)
        elif pred:
            pred.predicted_winner_id = winner_id
        else:
            pred = UserPrediction(
                user_id=current_user.id,
                tournament_id=tournament_id,
                match_id=match_id,
                predicted_winner_id=winner_id,
            )
            db.add(pred)

    await db.commit()

    result = await db.execute(
        select(UserPrediction).where(
            UserPrediction.user_id == current_user.id,
            UserPrediction.tournament_id == tournament_id,
        )
    )
    return result.scalars().all()
