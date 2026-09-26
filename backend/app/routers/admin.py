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


# ---------------------------------------------------------------------------
# Site settings
# ---------------------------------------------------------------------------

@router.get("/settings")
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every site-wide setting, with the counts an admin needs to change one
    safely — how many draws currently use each locking rule."""
    if not current_user.is_admin:
        raise HTTPException(403, "Admin only")
    from sqlalchemy import func as _func
    from app.models.tournament import Draw
    from app.services.settings import LOCK_MODES, global_lock_mode

    counts = dict((await db.execute(
        select(Draw.pick_lock_mode, _func.count()).group_by(Draw.pick_lock_mode)
    )).all())
    return {
        "pick_lock_mode": await global_lock_mode(db),
        "lock_modes": list(LOCK_MODES),
        "draws_by_mode": {k or "unset": v for k, v in counts.items()},
    }


@router.put("/settings/pick-lock-mode", status_code=204)
async def set_pick_lock_mode(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Change the site-wide default.

    Only ever the DEFAULT for draws not yet stamped. Draws already carrying a
    mode keep it, which is the point: a tournament that finished under one rule
    must not start claiming it used the other. Switching the site over therefore
    takes effect on draws that have not started, and an admin who wants an
    in-flight draw moved changes that draw directly.
    """
    if not current_user.is_admin:
        raise HTTPException(403, "Admin only")
    from app.services.settings import LOCK_MODES, PICK_LOCK_MODE, set_setting
    from app.services.system_log import app_log

    mode = (body or {}).get("mode")
    if mode not in LOCK_MODES:
        raise HTTPException(400, f"mode must be one of {list(LOCK_MODES)}")
    await set_setting(db, PICK_LOCK_MODE, mode)
    await db.commit()
    await app_log("info", "admin",
                  f"Site-wide pick-lock mode set to {mode!r} by {current_user.username}",
                  {"mode": mode, "user_id": current_user.id})


@router.put("/draws/{draw_id}/pick-lock-mode", status_code=204)
async def set_draw_pick_lock_mode(
    draw_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Override one draw's locking rule, or clear it back to the site default."""
    if not current_user.is_admin:
        raise HTTPException(403, "Admin only")
    from app.models.tournament import Draw
    from app.services.settings import LOCK_MODES, resolve_draw_lock_mode
    from app.services.system_log import app_log

    draw = await db.get(Draw, draw_id)
    if draw is None:
        raise HTTPException(404, "Draw not found")

    mode = (body or {}).get("mode")
    if mode is not None and mode not in LOCK_MODES:
        raise HTTPException(400, f"mode must be one of {list(LOCK_MODES)} or null")

    # Only before a ball is struck. Once play begins the mode stops being a
    # setting and becomes the record of how the draw is being played: people
    # have already picked under one rule, and switching would move the
    # goalposts under them — a draw locked match-by-match would suddenly be
    # wholly locked, or a locked one would reopen mid-tournament.
    #
    # computed_status, not the stored status column: 'open' means released and
    # not yet started, which is exactly the last moment this is still a choice.
    if draw.computed_status not in ("upcoming", "open"):
        raise HTTPException(
            409,
            f"This draw is {draw.computed_status} — its locking rule can only be "
            f"changed before it starts",
        )

    was = draw.pick_lock_mode
    draw.pick_lock_mode = mode
    await db.commit()
    if mode is None:
        # Cleared, so it re-stamps from the current site default immediately —
        # a draw is never left without a recorded rule.
        mode = await resolve_draw_lock_mode(db, draw)
    await app_log("info", "admin",
                  f"Pick-lock mode for draw {draw_id} ({draw.year} {draw.name} "
                  f"{draw.gender}): {was!r} -> {mode!r} by {current_user.username}",
                  {"draw_id": draw_id, "from": was, "to": mode, "user_id": current_user.id})


# ── The betting market, on demand ────────────────────────────────────────────
# A yardstick for the rating model (services/history/odds.py), read only by
# scripts/fit_own_elo.py --market. It is not fetched nightly any more: refresh
# it from here before a retune.

async def _odds_last_refresh(db) -> Optional[dict]:
    row = (await db.execute(
        select(SystemLog.created_at, SystemLog.level, SystemLog.message)
        .where(SystemLog.message.like("market odds:%"))
        .order_by(SystemLog.id.desc()).limit(1))).first()
    return {"at": row[0].isoformat() if row[0] else None, "level": row[1], "message": row[2]} if row else None


@router.get("/sofascore-requests")
async def sofascore_requests(
    minutes: int = 60, recent: int = 50,
    current_user: User = Depends(get_current_user),
):
    """Every request we have sent Sofascore (services/sofa_ledger): the
    window's totals by caller, path and status, and the latest raw rows."""
    if not current_user.is_admin:
        raise HTTPException(403, "Admin only")
    import asyncio
    from datetime import datetime, timedelta, timezone
    from app.services import sofa_ledger
    from app.services import sofascore
    minutes = max(1, min(minutes, 60 * 24 * 7))
    rows = await asyncio.to_thread(
        sofa_ledger._read_since, datetime.now(timezone.utc) - timedelta(minutes=minutes))
    bucket = sofa_ledger.bucket_minutes(minutes)
    last = await asyncio.to_thread(sofa_ledger.last_outcomes)
    snaps = await asyncio.to_thread(sofa_ledger.snapshots)
    # The charts' data (admin Sofascore tab, web and app): buckets, the
    # budgets they are drawn against, and whether we are blocked right now.
    return {"summary": sofa_ledger.summary(minutes, rows),
            "series": sofa_ledger.series(rows, minutes, bucket),
            "bucket_minutes": bucket,
            "budgets": {"hourly": sofa_ledger.HOURLY_WARN,
                        "callers": sofa_ledger.CALLER_WARN,
                        "caller_default": sofa_ledger.CALLER_WARN_DEFAULT},
            "breaker": {"blocked_for_s": round(sofascore.blocked_for())},
            "last": last,
            "snapshots": snaps,
            "recent": rows[-max(0, min(recent, 1000)):]}


@router.get("/market-odds")
async def market_odds_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """What the odds store holds, and when it was last refreshed."""
    if not current_user.is_admin:
        raise HTTPException(403, "Admin only")
    from app.services.history import db as hdb, odds
    held = await hdb.run(odds.status)
    return {**held, "last_refresh": await _odds_last_refresh(db)}


@router.post("/market-odds/refresh")
async def market_odds_refresh(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch the window the model is validated on — this season and the two
    before it — store it, and link it to the record. A past season already
    held is not re-read, so a routine refresh is two requests."""
    if not current_user.is_admin:
        raise HTTPException(403, "Admin only")
    from datetime import date as _date
    from app.services.history import db as hdb, odds
    year = _date.today().year
    out = await odds.sync_async([year - 2, year - 1, year])
    held = await hdb.run(odds.status)
    return {
        "read": sum(s["rows"] for s in out["seasons"]),
        "sources": out.get("sources") or [],
        **held,
        "last_refresh": await _odds_last_refresh(db),
    }
