import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import delete, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.security import (
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    hash_password,
    verify_email_verification_token,
    verify_password,
    verify_password_reset_token,
)
from app.database import get_db
from app.models.user import User
from app.schemas.user import ChangePassword, Token, UserAdminOut, UserOut, UserPublicOut, UserRegister, UserUpdate
from app.services import email as email_service
from app.services.system_log import app_log

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/users", response_model=list[UserPublicOut])
async def list_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.display_name))
    return result.scalars().all()


@router.get("/admin/users", response_model=list[UserAdminOut])
async def admin_list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    result = await db.execute(
        select(User)
        .where(User.email_verified == True)
        .order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "display_name": u.display_name,
            "email_verified": u.email_verified,
            "is_admin": u.is_admin,
            "created_at": u.created_at.strftime("%Y-%m-%d") if u.created_at else None,
        }
        for u in users
    ]


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: UserRegister, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    existing_username = await db.execute(select(User).where(User.username == body.username))
    if existing_username.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")
    user = User(
        email=body.email,
        username=body.username,
        full_name=body.full_name,
        display_name=body.full_name,
        password_hash=hash_password(body.password),
    )
    code = f"{secrets.randbelow(1000000):06d}"
    user.verification_code = code
    user.verification_code_expires = datetime.now(timezone.utc) + timedelta(hours=24)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_email_verification_token(user.email)
    await email_service.send_verification(user.email, user.username, token, code)
    return user


@router.post("/login", response_model=Token)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == form.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Please verify your email address before logging in")
    token = create_access_token(str(user.id))
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.username is not None and body.username != current_user.username:
        conflict = await db.execute(select(User).where(User.username == body.username))
        if conflict.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Username already taken")
        current_user.username = body.username
    if body.full_name is not None:
        current_user.full_name = body.full_name
        current_user.display_name = body.full_name
    await db.commit()
    await db.refresh(current_user)
    return current_user


_DEFAULT_NOTIF_PREFS = [
    "draw_open:Grand Slam:M",
    "draw_open:Grand Slam:F",
    "tournament_end",
]


async def _mark_verified(user: User, db: AsyncSession) -> None:
    """Set email_verified and clear the code, then send welcome email."""
    from app.models.notification import NotificationPreference
    user.email_verified = True
    user.verification_code = None
    user.verification_code_expires = None
    for key in _DEFAULT_NOTIF_PREFS:
        db.add(NotificationPreference(user_id=user.id, pref_key=key))
    await db.commit()
    await email_service.send_welcome(user.email, user.username)
    await email_service.send_new_user_notification(user.email, user.username)


@router.get("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    email = verify_email_verification_token(token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    if not user.email_verified:
        await _mark_verified(user, db)


@router.post("/verify-email-code", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email_code(body: dict, db: AsyncSession = Depends(get_db)):
    email = body.get("email", "").lower().strip()
    code = body.get("code", "").strip()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    invalid = HTTPException(status_code=400, detail="Invalid or expired code")
    if not user or user.email_verified:
        raise invalid
    if not user.verification_code or user.verification_code != code:
        raise invalid
    if not user.verification_code_expires or datetime.now(timezone.utc) > user.verification_code_expires:
        raise invalid
    await _mark_verified(user, db)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(body: dict, db: AsyncSession = Depends(get_db)):
    email = body.get("email", "").lower().strip()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        token = create_password_reset_token(user.email)
        await email_service.send_password_reset(user.email, token)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(body: dict, db: AsyncSession = Depends(get_db)):
    token = body.get("token", "")
    new_password = body.get("password", "")
    email = verify_password_reset_token(token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user.password_hash = hash_password(new_password)
    await db.commit()


@router.get("/me/notifications")
async def get_notification_prefs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.league import League, LeagueMember
    from app.models.notification import NotificationPreference

    keys_result = await db.execute(
        select(NotificationPreference.pref_key).where(
            NotificationPreference.user_id == current_user.id
        )
    )
    enabled_keys = [r[0] for r in keys_result.all()]

    leagues_result = await db.execute(
        select(League)
        .join(LeagueMember, LeagueMember.league_id == League.id)
        .where(LeagueMember.user_id == current_user.id)
        .order_by(League.name)
    )
    leagues = [{"id": lg.id, "name": lg.name} for lg in leagues_result.scalars().all()]

    return {"enabled_keys": enabled_keys, "leagues": leagues}


@router.put("/me/notifications", status_code=status.HTTP_204_NO_CONTENT)
async def put_notification_prefs(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.notification import NotificationPreference

    enabled_keys: list[str] = body.get("enabled_keys", [])

    await db.execute(
        delete(NotificationPreference).where(
            NotificationPreference.user_id == current_user.id
        )
    )
    for key in set(enabled_keys):
        db.add(NotificationPreference(user_id=current_user.id, pref_key=key))
    await db.commit()


@router.get("/me/draw-history")
async def get_draw_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.draw_history import TournamentResult
    from app.models.tournament import Tournament, Match
    from app.models.prediction import UserPrediction
    from sqlalchemy import func

    res = await db.execute(
        select(TournamentResult)
        .where(TournamentResult.user_id == current_user.id)
        .order_by(TournamentResult.tournament_id.desc(), TournamentResult.league_id.nullsfirst())
    )
    rows = res.scalars().all()

    # Group by tournament
    tourn_ids = list(dict.fromkeys(r.tournament_id for r in rows))
    if not tourn_ids:
        return []

    # Count total non-bye matches per tournament
    match_counts_res = await db.execute(
        select(Match.tournament_id, func.count().label("total"))
        .where(Match.tournament_id.in_(tourn_ids), Match.is_bye == False)
        .group_by(Match.tournament_id)
    )
    total_matches = {row.tournament_id: row.total for row in match_counts_res}

    # Count user's completed predictions per tournament
    pred_counts_res = await db.execute(
        select(UserPrediction.tournament_id, func.count().label("total"))
        .where(
            UserPrediction.tournament_id.in_(tourn_ids),
            UserPrediction.user_id == current_user.id,
            UserPrediction.predicted_winner_id.isnot(None),
        )
        .group_by(UserPrediction.tournament_id)
    )
    user_preds = {row.tournament_id: row.total for row in pred_counts_res}

    # Only include tournaments where user made all predictions
    competed_ids = {
        tid for tid in tourn_ids
        if user_preds.get(tid, 0) >= total_matches.get(tid, 1)
    }

    t_res = await db.execute(
        select(Tournament).where(Tournament.id.in_(competed_ids))
    )
    tournaments = {t.id: t for t in t_res.scalars().all()}

    by_tourn: dict[int, list] = {}
    for r in rows:
        if r.tournament_id not in competed_ids:
            continue
        by_tourn.setdefault(r.tournament_id, []).append({
            "league_id": r.league_id,
            "league_name": r.league_name,
            "rank": r.rank,
            "total_participants": r.total_participants,
            "points": r.points,
            "correct_count": r.correct_count,
        })

    result = []
    for tid in tourn_ids:
        if tid not in competed_ids:
            continue
        t = tournaments.get(tid)
        if not t:
            continue
        result.append({
            "tournament_id": tid,
            "name": t.name,
            "year": t.year,
            "gender": t.gender,
            "surface": t.surface,
            "category": t.category,
            "results": by_tourn[tid],
        })
    return result


@router.post("/admin/backfill-draw-history", status_code=200)
async def backfill_draw_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin-only: recompute and save TournamentResult rows for all completed tournaments."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admins only")

    from app.models.tournament import Tournament, Match
    from app.models.prediction import UserPrediction
    from app.models.league import League
    from app.models.draw_history import TournamentResult
    from app.services.scoring import rank_users, score_user
    from app.services.notifications import _persist_tournament_results
    from sqlalchemy.orm import selectinload
    from collections import defaultdict

    t_res = await db.execute(
        select(Tournament).where(Tournament.status == "completed")
    )
    tournaments = t_res.scalars().all()

    lg_res = await db.execute(select(League).options(selectinload(League.members)))
    all_leagues = lg_res.scalars().all()

    saved = 0
    for tournament in tournaments:
        m_res = await db.execute(
            select(Match)
            .options(selectinload(Match.player1), selectinload(Match.player2), selectinload(Match.winner))
            .where(Match.tournament_id == tournament.id, Match.status == "completed")
        )
        completed_matches = m_res.scalars().all()
        if not completed_matches:
            continue

        pred_res = await db.execute(
            select(UserPrediction).where(
                UserPrediction.tournament_id == tournament.id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        all_preds = pred_res.scalars().all()
        preds_by_user: dict = defaultdict(list)
        for p in all_preds:
            preds_by_user[p.user_id].append(p)

        if not preds_by_user:
            continue

        await _persist_tournament_results(
            db, tournament.id, set(preds_by_user.keys()),
            preds_by_user, completed_matches, tournament, all_leagues,
        )
        saved += 1

    await app_log("info", "admin", f"Draw history backfill complete: {saved} tournament(s) processed")
    return {"tournaments_processed": saved}


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePassword,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    current_user.password_hash = hash_password(body.new_password)
    await db.commit()
