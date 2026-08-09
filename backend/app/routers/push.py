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


async def _latest_content(db: AsyncSession, pref_key: str, user_id: int) -> dict:
    """
    Rebuild the most recent real notification of this type.

    Replaying actual data is the point: a generic "test" proves the pipe works
    but says nothing about what a draw-release notification will look like on a
    six-draw week. Falls back to a representative sample when the type has
    never fired, so the button still shows the shape rather than erroring.

    user_id scopes the types that are personal by construction. A draw release
    or a round digest is the same message for everyone, so the newest one is the
    honest replay; a standout pick is a statement about the caller's own bracket
    and replaying somebody else's would describe the type wrongly.
    """
    from datetime import timedelta
    from app.models.prediction import UserPrediction
    from app.models.tournament import Draw, DrawEntry
    from app.services import push_content
    from app.services.email import _tournament_label

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

    if pref_key in ("draw_changed", "qualifiers_added"):
        from app.models.notification import DrawChangeEvent
        from app.services.notifications import _round1_matchups

        # Scoped to the kind being replayed, since the two types now come from
        # the same table: replaying the newest row regardless of kind would show
        # a qualifier list under "Draw change" whenever a qualifier went in last.
        kind = "filled" if pref_key == "qualifiers_added" else "replaced"
        # Every event in a batch is stamped by one UPDATE, so the batch is
        # exactly the rows sharing the newest notified_at.
        newest = (await db.execute(
            select(func.max(DrawChangeEvent.notified_at))
            .where(DrawChangeEvent.notified_at.isnot(None),
                   DrawChangeEvent.kind == kind)
        )).scalar()
        if newest:
            events = (await db.execute(
                select(DrawChangeEvent)
                .where(DrawChangeEvent.notified_at == newest,
                       DrawChangeEvent.kind == kind)
                .order_by(DrawChangeEvent.draw_id, DrawChangeEvent.bracket_position)
            )).scalars().all()
            by_draw: dict[int, list] = {}
            for e in events:
                by_draw.setdefault(e.draw_id, []).append(e)
            sections: dict[int, dict] = {}
            for draw_id, evs in by_draw.items():
                d = await db.get(Draw, draw_id)
                if not d:
                    continue
                opponents = await _round1_matchups(
                    db, draw_id, {e.entry_id for e in evs if e.entry_id}
                )
                sections[d.id] = {
                    "id": d.id, "name": d.name, "gender": d.gender,
                    "category": d.category,
                    "changes": [{
                        "kind": e.kind, "old_name": e.old_name, "new_name": e.new_name,
                        "old_entry_type": e.old_entry_type,
                        "new_entry_type": e.new_entry_type,
                        "bracket_position": e.bracket_position,
                        "opponent": opponents.get(e.entry_id, (None, "", False))[0],
                        "opponent_status": opponents.get(e.entry_id, (None, "", False))[1],
                        "opponent_bye": opponents.get(e.entry_id, (None, "", False))[2],
                    } for e in evs],
                }
            if sections:
                # Replayed with the "affects your picks" line on: the caller is
                # looking at this to see what the real thing looks like, and that
                # line is the part of it worth checking renders.
                builder = (push_content.qualifiers_added if kind == "filled"
                           else push_content.draw_change)
                return builder(
                    list(sections.values()), True, max(e.id for e in events),
                )

        if kind == "filled":
            # No draw has announced its qualifiers yet, so rebuild the message
            # from the most recent draw that HAS a qualifying field. The invented
            # sample said "3 qualifiers added" for an ATP 1000, which is not a
            # number that event can produce — a 1000 takes twelve and a Slam
            # sixteen — so the one thing the test button exists to show, whether
            # a full field is readable on a lock screen, was exactly what it hid.
            recent = (await db.execute(
                select(Draw)
                .join(DrawEntry, DrawEntry.draw_id == Draw.id)
                .where(DrawEntry.entry_type == "Q",
                       func.trim(func.coalesce(DrawEntry.name, "")) != "")
                .group_by(Draw.id)
                .order_by(Draw.start_date.desc())
                .limit(1)
            )).scalars().first()
            if recent:
                quals = (await db.execute(
                    select(DrawEntry)
                    .where(DrawEntry.draw_id == recent.id, DrawEntry.entry_type == "Q")
                    .order_by(DrawEntry.bracket_position)
                )).scalars().all()
                quals = [q for q in quals if (q.name or "").strip()]
                if quals:
                    opponents = await _round1_matchups(db, recent.id, {q.id for q in quals})
                    return push_content.qualifiers_added([{
                        "id": recent.id, "name": recent.name, "gender": recent.gender,
                        "category": recent.category,
                        "changes": [{
                            "kind": "filled", "new_name": q.name,
                            "new_entry_type": q.entry_type,
                            "bracket_position": q.bracket_position,
                            "opponent": opponents.get(q.id, (None, "", False))[0],
                            "opponent_status": opponents.get(q.id, (None, "", False))[1],
                            "opponent_bye": opponents.get(q.id, (None, "", False))[2],
                        } for q in quals],
                    }], True, 0)

    if pref_key == "standout_pick":
        from app.models.notification import StandoutPickNotification
        from app.models.tournament import Match
        from app.services.notifications import (
            STANDOUT_MAX_SHARE, STANDOUT_MIN_PREDICTIONS, _email_round_label,
        )
        from app.services.email import _tier_badge

        # The caller's OWN most recent standout, not the site's: this replays a
        # notification that is personal by construction, and showing someone
        # another competitor's minority call would misrepresent the type
        # entirely. Falls through to the sample when they have never had one.
        #
        # The share conditions are not decoration. Every match that had already
        # finished when this feature shipped carries a placeholder row —
        # notified, zero counts, never actually sent (see the ledger-guarded
        # backfill in database.py). Matching on notified_at alone replayed one of
        # those as "You called it — Sinner def. Kecmanović … 0 of 0 got it",
        # which is neither true nor a standout. Only a row that genuinely
        # qualified can stand in for a real notification.
        row = (await db.execute(
            select(StandoutPickNotification, Match)
            .join(Match, Match.id == StandoutPickNotification.match_id)
            .join(
                UserPrediction,
                (UserPrediction.match_id == StandoutPickNotification.match_id)
                & (UserPrediction.predicted_winner_id == Match.winner_id)
                & (UserPrediction.user_id == user_id),
            )
            .where(
                StandoutPickNotification.notified_at.isnot(None),
                StandoutPickNotification.correct_count > 0,
                StandoutPickNotification.prediction_count >= STANDOUT_MIN_PREDICTIONS,
                StandoutPickNotification.correct_count
                < StandoutPickNotification.participant_count * STANDOUT_MAX_SHARE,
            )
            .order_by(StandoutPickNotification.notified_at.desc())
            .limit(1)
        )).first()
        if row:
            spn, match = row
            draw = await db.get(Draw, spn.draw_id)
            winner = await db.get(DrawEntry, match.winner_id)
            loser_id = match.player2_id if match.winner_id == match.player1_id else match.player1_id
            loser = await db.get(DrawEntry, loser_id) if loser_id else None
            if draw and winner and loser:
                from app.services.notifications import _match_score_str
                return push_content.standout_pick([{
                    "match_id": match.id,
                    "draw_id": draw.id,
                    "draw_name": draw.name,
                    "gender": draw.gender,
                    "category": draw.category,
                    "label": _tournament_label(draw.name, draw.category or "", draw.gender or "M"),
                    "tier": _tier_badge(draw.category or "", draw.gender),
                    "round_name": _email_round_label(draw.round_name(match.round_number)),
                    "winner": winner.name,
                    "loser": loser.name,
                    "score": _match_score_str(match),
                    "correct_count": spn.correct_count,
                    "participant_count": spn.participant_count,
                }])

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

    content = await _latest_content(db, pref_key, current_user.id)
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
