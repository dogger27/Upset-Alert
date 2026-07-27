import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import delete, func, select, and_
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


@router.patch("/admin/users/{user_id}")
async def set_user_admin(
    user_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot change your own admin status")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_admin = bool(body.get("is_admin", False))
    await db.commit()
    return {"id": target.id, "is_admin": target.is_admin}


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: UserRegister, db: AsyncSession = Depends(get_db)):
    email = body.email.lower().strip()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    existing_username = await db.execute(select(User).where(User.username == body.username))
    if existing_username.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")
    user = User(
        email=email,
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
    result = await db.execute(select(User).where(User.email == form.username.lower().strip()))
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
    # Draw-release emails are one weekly digest covering every draw released
    # that week — a single on/off, not a per-tier selection.
    "draw_released",
    "round_standings",
    # No "tournament_end": Draw Completion is only offered once round emails are
    # switched off (the settings UI hides it otherwise, and enables it the moment
    # rounds go off). Seeding both would start every account in a state the UI
    # says cannot exist — and would silently suppress their final-round email.
    "league_member_joined",
]


async def _mark_verified(user: User, db: AsyncSession) -> bool:
    """
    Atomically claim first-time verification, add default notif prefs, and
    send welcome/admin emails. Returns False (no-op) if another concurrent
    call already claimed it.

    The claim is a single UPDATE...WHERE email_verified=False rather than a
    check-then-set on the loaded object, because /verify-email is a GET link
    with the token in the query string — exactly the shape email clients'
    security scanners and link-preview crawlers fetch automatically (see
    [[reference_round_complete_dedup]] for the same failure mode on the
    unsubscribe link). Two near-simultaneous fetches of that link (a scanner
    plus the user's own click, or a double form-submit on the code path)
    could otherwise both read email_verified=False before either commits,
    sending duplicate welcome/admin emails.
    """
    from sqlalchemy import update as sa_update
    from app.models.notification import NotificationPreference

    result = await db.execute(
        sa_update(User)
        .where(User.id == user.id, User.email_verified == False)
        .values(email_verified=True, verification_code=None, verification_code_expires=None)
    )
    if result.rowcount == 0:
        await db.rollback()
        return False
    for key in _DEFAULT_NOTIF_PREFS:
        db.add(NotificationPreference(user_id=user.id, pref_key=key))
    await db.commit()
    await email_service.send_welcome(user.email, user.username)
    await email_service.send_new_user_notification(user.email, user.username)
    return True


@router.get("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    email = verify_email_verification_token(token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    await _mark_verified(user, db)


@router.post("/verify-email-code", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email_code(body: dict, db: AsyncSession = Depends(get_db)):
    email = body.get("email", "").lower().strip()
    code = body.get("code", "").strip()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    invalid = HTTPException(status_code=400, detail="Invalid or expired code")
    if not user:
        raise invalid
    if user.email_verified:
        return  # already verified — treat as success so the user can proceed to login
    if not user.verification_code or user.verification_code != code:
        raise invalid
    expires = user.verification_code_expires
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if not expires or datetime.now(timezone.utc) > expires:
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


async def _global_draw_history(db: AsyncSession, user_id: int) -> list[dict]:
    """
    Draw History is scoped to the Global league only — a user's private
    leagues can come and go, but Global is the one constant every competitor
    is always in, so it's the only ranking that stays meaningful as a
    standalone per-tournament history entry.
    """
    from app.models.draw_history import TournamentResult
    from app.models.tournament import Draw, Match
    from app.models.prediction import UserPrediction
    from sqlalchemy import func

    res = await db.execute(
        select(TournamentResult)
        .where(
            TournamentResult.user_id == user_id,
            TournamentResult.league_id.is_(None),
        )
        .order_by(TournamentResult.draw_id.desc())
    )
    global_results = {r.draw_id: r for r in res.scalars().all()}
    tourn_ids = list(global_results.keys())
    if not tourn_ids:
        return []

    # Count total non-bye matches per tournament
    match_counts_res = await db.execute(
        select(Match.draw_id, func.count().label("total"))
        .where(Match.draw_id.in_(tourn_ids), Match.is_bye == False)
        .group_by(Match.draw_id)
    )
    total_matches = {row.draw_id: row.total for row in match_counts_res}

    # Count user's completed predictions per tournament
    pred_counts_res = await db.execute(
        select(UserPrediction.draw_id, func.count().label("total"))
        .where(
            UserPrediction.draw_id.in_(tourn_ids),
            UserPrediction.user_id == user_id,
            UserPrediction.predicted_winner_id.isnot(None),
        )
        .group_by(UserPrediction.draw_id)
    )
    user_preds = {row.draw_id: row.total for row in pred_counts_res}

    # Only include tournaments where user made all predictions
    competed_ids = {
        tid for tid in tourn_ids
        if user_preds.get(tid, 0) >= total_matches.get(tid, 1)
    }
    if not competed_ids:
        return []

    t_res = await db.execute(select(Draw).where(Draw.id.in_(competed_ids)))
    tournaments = {t.id: t for t in t_res.scalars().all()}

    entries = []
    for tid in tourn_ids:
        if tid not in competed_ids:
            continue
        t = tournaments.get(tid)
        if not t:
            continue
        r = global_results[tid]
        entries.append({
            "tournament_id": tid,
            "name": t.name,
            "year": t.year,
            "gender": t.gender,
            "surface": t.surface,
            "category": t.category,
            "start_date": t.start_date,
            "end_date": t.end_date,
            "total_matches": total_matches.get(tid, 0),
            "rank": r.rank,
            "total_participants": r.total_participants,
            "points": r.points,
            "correct_count": r.correct_count,
        })
    return entries


@router.get("/me/draw-history")
async def get_draw_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _global_draw_history(db, current_user.id)


@router.get("/users/draw-counts")
async def get_draw_counts(db: AsyncSession = Depends(get_db)):
    """Return competed draw counts for all users (draws where they fully entered picks)."""
    from app.models.draw_history import TournamentResult
    res = await db.execute(
        select(TournamentResult.user_id, func.count().label("draw_count"))
        .where(TournamentResult.league_id.is_(None))
        .group_by(TournamentResult.user_id)
    )
    return [{"user_id": r.user_id, "draw_count": r.draw_count} for r in res.all()]


@router.get("/users/{user_id}/draw-history")
async def get_user_draw_history(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_res = await db.execute(select(User).where(User.id == user_id))
    target = user_res.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    entries = await _global_draw_history(db, user_id)
    return {"username": target.username, "entries": entries}


@router.post("/admin/backfill-draw-history", status_code=200)
async def backfill_draw_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin-only: recompute and save TournamentResult rows for all completed tournaments."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admins only")

    from app.models.tournament import Draw, Match
    from app.models.prediction import UserPrediction
    from app.models.league import League
    from app.models.draw_history import TournamentResult
    from app.services.scoring import rank_users, score_user
    from app.services.notifications import _persist_tournament_results
    from sqlalchemy.orm import selectinload
    from collections import defaultdict

    t_res = await db.execute(
        select(Draw).where(Draw.status == "completed")
    )
    tournaments = t_res.scalars().all()

    lg_res = await db.execute(select(League).options(selectinload(League.members)))
    all_leagues = lg_res.scalars().all()

    saved = 0
    for tournament in tournaments:
        m_res = await db.execute(
            select(Match)
            .options(selectinload(Match.player1), selectinload(Match.player2), selectinload(Match.winner))
            .where(Match.draw_id == tournament.id, Match.status == "completed",
                   Match.is_bye == False)  # noqa: E712 — byes are not predictions
        )
        completed_matches = m_res.scalars().all()
        if not completed_matches:
            continue

        pred_res = await db.execute(
            select(UserPrediction).where(
                UserPrediction.draw_id == tournament.id,
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
