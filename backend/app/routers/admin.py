from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.database import get_db
from app.models.rankings import TePlayer, TeRankingsSnapshot
from app.models.system_log import SystemLog
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/logs")
async def get_logs(
    level: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(300, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    q = select(SystemLog).order_by(SystemLog.created_at.desc())
    if level:
        q = q.where(SystemLog.level == level)
    if category:
        q = q.where(SystemLog.category == category)
    q = q.limit(limit)

    result = await db.execute(q)
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "created_at": (log.created_at.isoformat() + "Z") if log.created_at else None,
            "level": log.level,
            "category": log.category,
            "message": log.message,
            "detail": log.detail_json,
        }
        for log in logs
    ]


@router.delete("/logs")
async def clear_logs(
    older_than_days: int = Query(30),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    if older_than_days == 0:
        result = await db.execute(delete(SystemLog))
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        result = await db.execute(delete(SystemLog).where(SystemLog.created_at < cutoff))
    await db.commit()
    return {"deleted": result.rowcount}


@router.get("/players")
async def get_players(
    gender: Optional[str] = Query(None, description="M or F"),
    search: Optional[str] = Query(None),
    limit: int = Query(500, le=2000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    q = select(TePlayer).order_by(TePlayer.elo.desc().nullslast(), TePlayer.name_norm)
    if gender:
        q = q.where(TePlayer.gender == gender)
    if search:
        term = f"%{search.lower()}%"
        q = q.where(TePlayer.name_norm.like(term))
    q = q.limit(limit)

    result = await db.execute(q)
    players = result.scalars().all()
    return [
        {
            "id": p.id,
            "gender": p.gender,
            "name_raw": p.name_raw,
            "name_norm": p.name_norm,
            "te_slug": p.te_slug,
            "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
            "elo": p.elo,
        }
        for p in players
    ]


@router.get("/rankings/weeks")
async def get_rankings_weeks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    result = await db.execute(
        select(TeRankingsSnapshot.week_date)
        .distinct()
        .order_by(TeRankingsSnapshot.week_date.desc())
        .limit(100)
    )
    weeks = result.scalars().all()
    return [w.isoformat() for w in weeks]


@router.get("/rankings")
async def get_rankings(
    week_date: str = Query(..., description="ISO date e.g. 2026-06-22"),
    gender: Optional[str] = Query(None, description="M or F"),
    limit: int = Query(5000, le=5000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    q = (
        select(TeRankingsSnapshot, TePlayer)
        .join(TePlayer, TePlayer.id == TeRankingsSnapshot.player_id)
        .where(TeRankingsSnapshot.week_date == week_date)
        .order_by(TeRankingsSnapshot.rank)
    )
    if gender:
        q = q.where(TePlayer.gender == gender)
    q = q.limit(limit)

    result = await db.execute(q)
    rows = result.all()
    return [
        {
            "rank": snap.rank,
            "elo_rank": player.elo_rank,
            "points": snap.points,
            "player_id": player.id,
            "name_raw": player.name_raw,
            "date_of_birth": player.date_of_birth.isoformat() if player.date_of_birth else None,
        }
        for snap, player in rows
    ]
