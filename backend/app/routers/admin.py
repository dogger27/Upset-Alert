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


# Enough occurrences to see a pattern (is it hourly? did it stop?) without
# shipping all 65 rows of a stuck problem to the browser. count is always the
# true total, so a truncated list never misrepresents how often it fired.
MAX_OCCURRENCES_PER_GROUP = 25


@router.get("/logs")
async def get_logs(
    level: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(1000, le=5000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Log entries collapsed into one row per *problem*, newest activity first.

    Grouping uses alerts.log_fingerprint — the same function the email alerter
    groups on — so a problem the panel shows as one row is exactly a problem
    that earns one alert email. Reimplementing the normalisation here (in
    Python or in the browser) would let the two definitions drift, and then
    "why did I get 1 email for 65 rows?" would have no single answer.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    from app.services.alerts import log_fingerprint

    q = select(SystemLog).order_by(SystemLog.created_at.desc())
    if level:
        q = q.where(SystemLog.level == level)
    if category:
        q = q.where(SystemLog.category == category)
    q = q.limit(limit)

    result = await db.execute(q)
    logs = result.scalars().all()

    groups: dict[str, dict] = {}
    for log in logs:
        entry = {
            "id": log.id,
            "created_at": (log.created_at.isoformat() + "Z") if log.created_at else None,
            "message": log.message,
            "detail": log.detail_json,
        }
        fp = log_fingerprint(log.level, log.category, log.message)
        group = groups.get(fp)
        if group is None:
            groups[fp] = {
                "fingerprint": fp,
                "level": log.level,
                "category": log.category,
                # Rows arrive newest-first, so the group's headline message is
                # the most recent wording of a problem whose text can vary in
                # the parts the fingerprint normalises away.
                "message": log.message,
                "count": 1,
                "last_seen": entry["created_at"],
                "first_seen": entry["created_at"],
                "occurrences": [entry],
            }
        else:
            group["count"] += 1
            # Walking backwards in time, so every later row is older than the
            # last. A floor rather than the true first occurrence when `limit`
            # cuts the scan short — `truncated` tells the client when that is.
            group["first_seen"] = entry["created_at"]
            if len(group["occurrences"]) < MAX_OCCURRENCES_PER_GROUP:
                group["occurrences"].append(entry)

    return {
        "groups": sorted(groups.values(), key=lambda g: g["last_seen"] or "", reverse=True),
        "entry_count": len(logs),
        "truncated": len(logs) >= limit,
    }


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
    limit: int = Query(10000, le=10000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    q = select(TePlayer).order_by(TePlayer.last_name.nullslast(), TePlayer.first_name, TePlayer.name_norm)
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
            "first_name": p.first_name,
            "last_name": p.last_name,
            "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
            "nationality": p.nationality,
            "te_slug": p.te_slug,
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
            "elo_rank": snap.elo_rank,
            "points": snap.points,
            "player_id": player.id,
            "name_raw": player.name_raw,
            "name_display": player.name_display,
            "date_of_birth": player.date_of_birth.isoformat() if player.date_of_birth else None,
        }
        for snap, player in rows
    ]
