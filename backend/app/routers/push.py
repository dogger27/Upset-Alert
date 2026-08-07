from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.database import get_db
from app.models.push import PushSubscription
from app.models.user import User

router = APIRouter(prefix="/push", tags=["push"])


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionIn(BaseModel):
    endpoint: str
    keys: SubscriptionKeys


@router.get("/public-key")
async def get_public_key():
    """
    The VAPID application server key the browser needs to subscribe.

    Served rather than baked into the bundle so the key can be rotated without
    a frontend deploy, and so the client can tell "push isn't configured on this
    server" from "push failed" — an empty key means the former.
    """
    return {"public_key": settings.vapid_public_key}


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(
    body: SubscriptionIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Register this browser for push. Idempotent per endpoint.

    A browser re-subscribing hands back the same endpoint, so this updates in
    place instead of inserting — the endpoint is unique, and a second row would
    mean the same device gets every notification twice. The endpoint can also
    migrate between accounts (shared device, or a re-login), so user_id is
    rewritten too.
    """
    existing = (await db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )).scalar_one_or_none()

    ua = request.headers.get("user-agent")
    if existing is not None:
        existing.user_id = current_user.id
        existing.p256dh = body.keys.p256dh
        existing.auth = body.keys.auth
        existing.user_agent = ua
    else:
        db.add(PushSubscription(
            user_id=current_user.id,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
            user_agent=ua,
        ))
    await db.commit()


class UnsubscribeIn(BaseModel):
    endpoint: Optional[str] = None


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    body: UnsubscribeIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Drop this browser's channel, or every channel this user has."""
    q = delete(PushSubscription).where(PushSubscription.user_id == current_user.id)
    if body.endpoint:
        q = q.where(PushSubscription.endpoint == body.endpoint)
    await db.execute(q)
    await db.commit()


@router.get("/status")
async def push_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """How many devices this account currently has registered."""
    subs = (await db.execute(
        select(PushSubscription.endpoint, PushSubscription.user_agent)
        .where(PushSubscription.user_id == current_user.id)
    )).all()
    return {
        "configured": bool(settings.vapid_public_key),
        "device_count": len(subs),
    }
