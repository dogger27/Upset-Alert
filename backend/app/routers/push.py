from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
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

    # Reinstalling the app mints a brand-new endpoint while the old row lives
    # on, so the account quietly accumulates a duplicate and every notification
    # arrives twice. Delivery failure can't clean it up: Apple went on
    # ACCEPTING pushes for a channel whose app had been deleted, returning 200
    # rather than the 410 that prunes.
    #
    # So a device is identified by its user-agent, and re-registering replaces
    # whatever that device had before. The cost is two physically identical
    # devices on one account — same model, same OS build, therefore the same
    # user-agent string — where the second registration displaces the first.
    # That is rarer than reinstalling, and its failure mode (notifications on
    # one phone instead of two) is milder than guaranteed duplicates.
    if ua:
        await db.execute(
            delete(PushSubscription).where(
                PushSubscription.user_id == current_user.id,
                PushSubscription.user_agent == ua,
                PushSubscription.endpoint != body.endpoint,
            )
        )
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


async def _latest_content(db: AsyncSession, pref_key: str) -> dict:
    """
    Rebuild the most recent real notification of this type.

    Replaying actual data is the point: a generic "test" proves the pipe works
    but says nothing about what a draw-release notification will look like on a
    six-draw week. Falls back to a representative sample when the type has
    never fired, so the button still shows the shape rather than erroring.
    """
    from datetime import timedelta
    from app.models.tournament import Draw
    from app.services import push_content

    if pref_key == "draw_released":
        # The most recent SEND, not the most recent week. Week 30 went out as
        # four separate batches before one-per-week was enforced, so keying on
        # the week replayed six draws from four different notifications. Draws
        # announced together share a timestamp within minutes of each other,
        # so a short window around the newest one reconstructs that batch.
        newest = (await db.execute(
            select(Draw.draw_release_notified_at)
            .where(Draw.draw_release_notified_at.isnot(None))
            .order_by(Draw.draw_release_notified_at.desc())
            .limit(1)
        )).scalar()
        if newest:
            window_start = newest - timedelta(hours=1)
            draws = (await db.execute(
                select(Draw)
                .where(Draw.draw_release_notified_at >= window_start)
                .order_by(Draw.closing_time)
            )).scalars().all()
            if draws:
                start = min((d.start_date for d in draws if d.start_date), default=None)
                week_label = f"{start.strftime('%B')} {start.day}" if start else "this week"
                return push_content.draw_release(
                    [{"name": d.name, "gender": d.gender, "category": d.category}
                     for d in draws],
                    week_label,
                )

    if pref_key in ("round_standings", "tournament_end"):
        from app.models.notification import RoundCompleteNotification

        # Every draw in a digest is stamped by one UPDATE, so the batch is
        # exactly the rows sharing the newest digest_sent_at. Taking a single
        # row described a two-draw event as one draw — "R32 complete — Canadian
        # Open" listing only the ATP side.
        newest = (await db.execute(
            select(func.max(RoundCompleteNotification.digest_sent_at))
            .where(RoundCompleteNotification.digest_sent_at.isnot(None))
        )).scalar()
        if newest:
            rows = (await db.execute(
                select(RoundCompleteNotification.draw_id, RoundCompleteNotification.round_number)
                .where(RoundCompleteNotification.digest_sent_at == newest)
            )).all()
            draws = []
            round_no = None
            for draw_id, rnd in rows:
                d = await db.get(Draw, draw_id)
                if d:
                    draws.append(d)
                    round_no = rnd
            if draws:
                base = draws[0]
                names = {d.name for d in draws}
                where = base.name if len(names) == 1 else f"week of {base.start_date:%B %-d}" \
                    if base.start_date else base.name
                from app.services.notifications import _email_round_label
                return push_content.round_complete(
                    _email_round_label(base.round_name(round_no)),
                    where,
                    [{"name": d.name, "gender": d.gender, "category": d.category}
                     for d in draws],
                    pref_key == "tournament_end",
                )

    return push_content.sample(pref_key)


@router.post("/test/{pref_key}")
async def send_typed_test_push(
    pref_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replay this account's most recent notification of one type."""
    from app.services.push import push_enabled, send_push_to_users

    if not push_enabled():
        raise HTTPException(status_code=503, detail="Push is not configured on this server")

    devices = (await db.execute(
        select(func.count()).select_from(PushSubscription)
        .where(PushSubscription.user_id == current_user.id)
    )).scalar() or 0
    if devices == 0:
        raise HTTPException(
            status_code=400,
            detail="No devices registered — turn a Push notification on first",
        )

    content = await _latest_content(db, pref_key)
    # A distinct tag so a replay never collapses into, or replaces, the real
    # notification it is imitating.
    content = {**content, "tag": f"test-{pref_key}"}
    delivered = await send_push_to_users([current_user.id], **content)
    return {"devices": devices, "delivered": delivered, "title": content["title"]}


@router.post("/test")
async def send_test_push(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Send a test notification to the caller's own devices.

    Not admin-gated, because it can only ever reach the caller's own
    subscriptions — there is nothing to abuse, and gating it would stop the
    person who most needs it (someone setting up a new phone) from checking
    their own setup.

    Ignores the per-type push preferences on purpose: the question this answers
    is "can this device receive anything at all", which is a different question
    from "which notifications did I ask for".
    """
    from app.services.push import push_enabled, send_push_to_users

    if not push_enabled():
        raise HTTPException(status_code=503, detail="Push is not configured on this server")

    devices = (await db.execute(
        select(func.count())
        .select_from(PushSubscription)
        .where(PushSubscription.user_id == current_user.id)
    )).scalar() or 0
    if devices == 0:
        raise HTTPException(
            status_code=400,
            detail="No devices registered — enable a push notification first",
        )

    delivered = await send_push_to_users(
        [current_user.id],
        title="Upset Alert test",
        body="Push notifications are working on this device.",
        url="/",
        tag="upset-alert-test",
    )
    # delivered < devices means some channel is dead; send_push_to_users has
    # already pruned those rows, so the count is the honest post-cleanup number.
    return {"devices": devices, "delivered": delivered}


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
