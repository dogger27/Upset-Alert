from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.h2h import get_h2h

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
