from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.database import get_db
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
