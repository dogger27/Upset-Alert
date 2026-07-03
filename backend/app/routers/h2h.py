from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.h2h import get_h2h, get_player_form, _estimate_round_date

router = APIRouter(prefix="/h2h", tags=["h2h"])


@router.get("")
async def head_to_head(
    p1: str = Query(..., description="Tennis Explorer slug for player 1"),
    p2: str = Query(..., description="Tennis Explorer slug for player 2"),
    db: AsyncSession = Depends(get_db),
):
    if not p1 or not p2 or p1 == p2:
        raise HTTPException(400, "p1 and p2 must be different player slugs")
    return await get_h2h(p1, p2, db)


@router.get("/form")
async def player_form(
    slug: str = Query(..., description="Tennis Explorer slug for the player"),
    before_draw_id: Optional[int] = Query(
        None, description="Draw ID of the match being viewed — restricts Form to results before it"
    ),
    before_round: Optional[int] = Query(
        None, description="Round number of the match being viewed, required alongside before_draw_id"
    ),
    db: AsyncSession = Depends(get_db),
):
    """Last 10 completed matches for a single player, sourced from our own draw data.
    Independent of the (possibly slow) TE mutual-record scrape so the frontend can
    show Form immediately without waiting on get_h2h.

    When before_draw_id/before_round are given (viewing a specific match inside a
    draw), Form is restricted to results before that match's estimated date —
    otherwise a historical draw's H2H popup would show each player's CURRENT form
    instead of their form leading up to that match.
    """
    before_date = None
    if before_draw_id is not None and before_round is not None:
        from app.models.tournament import Draw
        draw = await db.get(Draw, before_draw_id)
        if draw is not None:
            date_str = _estimate_round_date(draw, before_round)
            if date_str:
                from datetime import date as _date
                before_date = _date.fromisoformat(date_str)
    return await get_player_form(slug, db, before_date=before_date)
