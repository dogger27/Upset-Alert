import asyncio
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
    """Save a bracket, retrying if SQLite hands the writer to somebody else.

    A save reads the user's picks and then writes them, so its transaction
    starts as a reader and has to upgrade. If any background job commits in
    between — and several run on their own timers — SQLite fails the upgrade
    IMMEDIATELY rather than waiting, because the snapshot the reads were made
    against is gone. busy_timeout does not cover that case; only re-reading
    does.

    The user saw it as "Failed to save: Unknown error", which is a 500 with no
    detail. Nothing was wrong with the bracket and nothing needed deciding — it
    simply had to be tried again, which is what a person does by clicking a
    second time. This does it for them.

    Each retry gets a FRESH session, for the same reason the retry is needed at
    all: the failed one still holds the snapshot that is no longer usable. And
    if it really cannot get through, it says so instead of returning a bare 500.
    """
    from sqlalchemy.exc import OperationalError
    from app.database import AsyncSessionLocal

    last = None
    for attempt in range(4):
        try:
            if attempt == 0:
                return await _save_predictions_once(
                    tournament_id, body, user_id, db, current_user)
            async with AsyncSessionLocal() as fresh:
                return await _save_predictions_once(
                    tournament_id, body, user_id, fresh, current_user)
        except OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            last = exc
            await asyncio.sleep(0.15 * 2 ** attempt)
    raise HTTPException(
        503,
        "The draw is busy being updated — your picks were not saved. "
        "Please try again in a moment.",
    ) from last


async def _save_predictions_once(tournament_id, body, user_id, db, current_user):
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
    from app.services.highest_rank_bot import fill_missing_picks
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

    # JOINING A DRAW THAT IS ALREADY UNDER WAY.
    #
    # Under match-by-match locking the bracket stays open through the first
    # round, so a user can enter a draw whose early matches have been played —
    # and those are precisely the ones they may not pick. Without this they
    # score nothing on them, nor on anything downstream of them, which is most
    # of a bracket: the entry is unwinnable from the moment it is made and
    # nothing on screen says why.
    #
    # So every locked match they have no pick for is set to the better-ranked
    # player, the same projection the Highest_Rank account plays, carried up the
    # tree to the final exactly as the lock itself propagates.
    #
    # BEFORE the refusal check below, deliberately. These become stored picks,
    # so a client that posts the same value for a locked match now agrees with
    # what is stored and is allowed through, where a moment earlier it would
    # have been a "change" to a locked match and refused. A client posting a
    # DIFFERENT winner there is still refused, which is the rule working.
    if lock.locked_match_ids:
        if await fill_missing_picks(db, tournament, uid, lock.locked_match_ids):
            await db.commit()

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

    # Upsert predictions; null winner_id means the pick was cleared.
    #
    # READ ONCE, NOT ONCE PER MATCH. This used to SELECT inside the loop, and
    # each of those triggered an autoflush of everything already changed — so
    # saving a 128-draw meant 127 round trips interleaved with 127 flushes, all
    # inside one write transaction. On a busy database that is a long time to
    # hold the writer, and it is where a user's save actually died:
    #   OperationalError on PUT /predictions/120 ... database is locked
    #   [SQL: UPDATE user_predictions SET predicted_winner_id=? WHERE id=?]
    # One query up front, then plain attribute changes, and the flush happens
    # once at commit.
    existing_preds = {
        p.match_id: p
        for p in (await db.execute(
            select(UserPrediction).where(
                UserPrediction.user_id == uid,
                UserPrediction.draw_id == tournament_id,
            )
        )).scalars().all()
    }
    for match_id, winner_id in body.picks.items():
        pred = existing_preds.get(match_id)
        if winner_id is None:
            if pred:
                await db.delete(pred)
                existing_preds.pop(match_id, None)
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
            existing_preds[match_id] = pred

    # AND NOW NOTHING IS LEFT BLANK. Every match this user still has no pick for
    # takes the better-ranked player. After their own picks are applied, not
    # before, so the projection is built around what they just chose: an upset
    # in the first round carries through, and the player they knocked out does
    # not come back in the second holding their pick.
    await db.flush()
    await fill_missing_picks(db, tournament, uid)

    await db.commit()

    result = await db.execute(
        select(UserPrediction).where(
            UserPrediction.user_id == uid,
            UserPrediction.draw_id == tournament_id,
        )
    )
    return result.scalars().all()
