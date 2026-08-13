from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_user
from app.database import get_db
from app.models.prediction import UserPrediction
from app.models.tournament import Match, Draw
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
        select(Match.draw_id, func.count().label("total"))
        .where(Match.is_bye == False)
        .group_by(Match.draw_id)
    )
    total_by_t = {r.draw_id: r.total for r in totals_result}

    picks_result = await db.execute(
        select(UserPrediction.draw_id, func.count().label("pick_count"))
        .where(
            UserPrediction.user_id == current_user.id,
            UserPrediction.predicted_winner_id.isnot(None),
        )
        .group_by(UserPrediction.draw_id)
    )
    picks_by_t = {r.draw_id: r.pick_count for r in picks_result}

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

    # Someone else's bracket is not readable until the first round is done —
    # while picks are still changeable it is a bracket to copy. Your own is
    # always yours, and an admin can see any (they can already edit them).
    if current_user is None or (uid != current_user.id and not current_user.is_admin):
        from app.services.locking import predictions_visible
        draw = await db.get(Draw, tournament_id)
        if draw is not None and not await predictions_visible(db, draw):
            raise HTTPException(
                403, "Other players' picks are hidden until the first round is complete"
            )

    result = await db.execute(
        select(UserPrediction).where(
            UserPrediction.user_id == uid,
            UserPrediction.draw_id == tournament_id,
        )
    )
    return result.scalars().all()


@router.put("/{tournament_id}", response_model=list[PredictionOut])
async def save_predictions(
    tournament_id: int,
    body: PredictionSet,
    user_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id is not None and user_id != current_user.id:
        if not current_user.is_admin:
            raise HTTPException(403, "Only admins may edit another user's predictions")
    uid = user_id if user_id is not None else current_user.id

    tournament = await db.get(Draw, tournament_id)
    if not tournament:
        raise HTTPException(404, "Tournament not found")
    # Locking is resolved in one place for all three consumers — this write, the
    # draw endpoint that tells the client what to grey out, and the client
    # itself. They disagreeing is the failure that matters: a bracket that looks
    # editable and 403s, or one that looks locked while the server takes it.
    from app.services.locking import draw_lock_state, rejected_changes
    lock = await draw_lock_state(db, tournament)
    if lock.draw_locked:
        raise HTTPException(403, f"Predictions are locked — {lock.reason}")

    # Validate that all match IDs belong to this tournament
    match_ids = list(body.picks.keys())
    if match_ids:
        result = await db.execute(
            select(Match.id).where(
                Match.id.in_(match_ids),
                Match.draw_id == tournament_id,
            )
        )
        valid_ids = set(result.scalars().all())
        invalid = set(match_ids) - valid_ids
        if invalid:
            raise HTTPException(400, f"Unknown match IDs: {invalid}")

    # Under progressive locking the bracket is open but individual matches are
    # not. Compared against what is stored, so an unchanged pick on a match now
    # in play still saves — the client posts its whole set every time, and
    # refusing the request outright would make the bracket unsavable the moment
    # any one match started.
    if lock.locked_match_ids:
        stored = {
            p.match_id: p.predicted_winner_id
            for p in (await db.execute(
                select(UserPrediction).where(
                    UserPrediction.user_id == uid,
                    UserPrediction.draw_id == tournament_id,
                )
            )).scalars().all()
        }
        refused = rejected_changes(lock, body.picks, stored)
        if refused:
            raise HTTPException(
                403,
                f"{len(refused)} pick(s) could not be changed — those matches are under way",
            )

    # Upsert predictions; null winner_id means the pick was cleared
    for match_id, winner_id in body.picks.items():
        existing = await db.execute(
            select(UserPrediction).where(
                UserPrediction.user_id == uid,
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
                user_id=uid,
                draw_id=tournament_id,
                match_id=match_id,
                predicted_winner_id=winner_id,
            )
            db.add(pred)

    await db.commit()

    result = await db.execute(
        select(UserPrediction).where(
            UserPrediction.user_id == uid,
            UserPrediction.draw_id == tournament_id,
        )
    )
    return result.scalars().all()
