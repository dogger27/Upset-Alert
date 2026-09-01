"""
The native app's own surface: device registration and Live Activity lifecycle.

A SEPARATE ROUTER FROM /push, deliberately. Every payload under /push is Web
Push shaped — endpoint URLs and ECDH key material — and both the frontend and
the rate limiter key on that prefix. Keeping the native side at /app means
either can change without dragging the other along, and it makes "which client
is this" answerable from the access log.

Nothing here sends anything. Registration and lifecycle are recorded; the
dispatcher that turns a score change into a push is a separate concern and a
separate file, for the same reason push_content.py is separate from push.py:
what it says and when it is sent are different questions.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.database import get_db
from app.models.app_device import AppDevice, PushToStartToken
from app.models.live_activity import (
    STATE_ACTIVE, STATE_ENDED, LiveActivity,
)
from app.models.tournament import Match
from app.models.schedule import ScheduleEntry
from app.models.user import User

router = APIRouter(prefix="/app", tags=["app"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Config ──────────────────────────────────────────────────────────────────

@router.get("/config")
async def app_config():
    """
    What this server supports, so the client can tell "not configured here"
    from "failed" — the same job GET /push/public-key does for the web.

    content_state_version is the contract number for the Live Activity payload.
    ActivityKit decodes content-state into a Swift Codable and a mismatch fails
    SILENTLY (APNs still returns 200), so the client checks this at launch and
    can refuse to start an activity it would not be able to decode.
    """
    return {
        "live_activities": bool(
            settings.live_activity_enabled and settings.apns_bundle_id
        ),
        "bundle_id": settings.apns_bundle_id,
        "content_state_version": 1,
        # How long the client should let an activity look current before it
        # greys itself out. Mirrors renderable_point()'s freshness window on
        # the server, so both sides age a score out at the same moment.
        "update_hint_seconds": 45,
    }


# ── Devices ─────────────────────────────────────────────────────────────────

class DeviceIn(BaseModel):
    install_id: str = Field(min_length=8, max_length=128)
    platform: str = Field(pattern="^(ios|android)$")
    device_token: Optional[str] = Field(default=None, max_length=256)
    apns_env: Optional[str] = Field(default=None, pattern="^(sandbox|production)$")
    bundle_id: Optional[str] = None
    app_version: Optional[str] = None
    build: Optional[str] = None
    os_version: Optional[str] = None
    device_model: Optional[str] = None
    locale: Optional[str] = None
    time_zone: Optional[str] = None


@router.post("/devices")
async def register_device(
    body: DeviceIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Register or refresh this installation. Idempotent on (user, install_id).

    ONE ENDPOINT, NOT TWO. The client knows the install id and the device token
    at the same moment; splitting them creates a window where a token arrives
    with no device to attach it to, and the ordering is then the client's
    problem rather than ours.

    A token can migrate between accounts — one phone, two people, or a re-login
    — so it is stolen from whichever row currently holds it rather than being
    allowed to exist twice. The partial unique index would reject the duplicate
    anyway; doing it explicitly means the loser is left in a coherent state
    (token cleared) instead of the write simply failing.
    """
    now = _now()

    device = (await db.execute(
        select(AppDevice).where(
            AppDevice.user_id == current_user.id,
            AppDevice.install_id == body.install_id,
        )
    )).scalar_one_or_none()

    if device is None:
        device = AppDevice(
            user_id=current_user.id,
            install_id=body.install_id,
            platform=body.platform,
            created_at=now,
        )
        db.add(device)

    if body.device_token:
        # Take the token off any other row holding it, including one belonging
        # to a different account.
        await db.execute(
            update(AppDevice)
            .where(AppDevice.device_token == body.device_token)
            .values(device_token=None)
        )

    device.platform = body.platform
    device.device_token = body.device_token or device.device_token
    device.apns_env = body.apns_env or device.apns_env or settings.apns_default_env
    device.bundle_id = body.bundle_id or device.bundle_id
    device.app_version = body.app_version
    device.build = body.build
    device.os_version = body.os_version
    device.device_model = body.device_model
    device.locale = body.locale
    device.time_zone = body.time_zone
    device.last_seen_at = now
    # A device that comes back is not disabled any more, whatever Apple said
    # about its old token. This is what makes the soft delete self-healing.
    device.disabled_at = None
    device.disabled_reason = None

    await db.commit()
    await db.refresh(device)

    return {
        "device_id": device.id,
        "live_activities": bool(
            settings.live_activity_enabled and settings.apns_bundle_id
        ),
    }


class PushToStartIn(BaseModel):
    install_id: str
    attributes_type: str = Field(max_length=128)
    token: str = Field(max_length=256)


@router.post("/devices/push-to-start", status_code=status.HTTP_204_NO_CONTENT)
async def register_push_to_start(
    body: PushToStartIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Store the iOS 17.2+ push-to-start token, which lets the server begin an
    activity the user never opened the app to start.

    One token per Attributes type per install, and it is reissued periodically,
    so this is an upsert rather than an insert.
    """
    device = await _device_for(db, current_user.id, body.install_id)
    row = (await db.execute(
        select(PushToStartToken).where(
            PushToStartToken.device_id == device.id,
            PushToStartToken.attributes_type == body.attributes_type,
        )
    )).scalar_one_or_none()

    if row is None:
        db.add(PushToStartToken(
            device_id=device.id,
            attributes_type=body.attributes_type,
            token=body.token,
            updated_at=_now(),
        ))
    else:
        row.token = body.token
        row.updated_at = _now()

    await db.commit()


@router.delete("/devices/{install_id}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_device(
    install_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Sign-out. Disables the device and ends everything it was running.

    The token is cleared rather than the row deleted: the install may well come
    back, and when it does the (user, install_id) key heals it in place. Its
    activities are marked ended here because nothing else would — the app is on
    its way out and will not be calling DELETE for each one.
    """
    device = (await db.execute(
        select(AppDevice).where(
            AppDevice.user_id == current_user.id,
            AppDevice.install_id == install_id,
        )
    )).scalar_one_or_none()
    if device is None:
        return

    now = _now()
    device.device_token = None
    device.disabled_at = now
    device.disabled_reason = "signed_out"
    await db.execute(
        update(LiveActivity)
        .where(LiveActivity.device_id == device.id,
               LiveActivity.state == STATE_ACTIVE)
        .values(state=STATE_ENDED, ended_at=now, end_reason="client", updated_at=now)
    )
    await db.commit()


# ── Live Activities ─────────────────────────────────────────────────────────

class ActivityIn(BaseModel):
    install_id: str
    activity_id: str = Field(max_length=128)
    push_token: str = Field(max_length=256)
    match_id: Optional[int] = None
    schedule_entry_id: Optional[int] = None
    content_version: int = 1
    started_by: str = Field(default="client", pattern="^(client|push_to_start)$")


@router.post("/live-activities")
async def start_activity(
    body: ActivityIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Record an activity the client has started, or refresh its push token.

    ACTIVITYKIT REISSUES THE TOKEN MID-ACTIVITY, so the client posts here again
    every time `pushTokenUpdates` yields. Identity is (device, activity_id) and
    the token is mutable data — the old one is dead the instant a new one
    arrives, so this must update rather than insert.

    Refuses a match that is already finished with 409 rather than accepting a
    row that can never be updated. The client can then end the activity it just
    created instead of leaving a dead one on the Lock Screen.
    """
    if (body.match_id is None) == (body.schedule_entry_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "exactly one of match_id or schedule_entry_id is required",
        )

    device = await _device_for(db, current_user.id, body.install_id)
    await _assert_still_live(db, body.match_id, body.schedule_entry_id)

    now = _now()
    row = (await db.execute(
        select(LiveActivity).where(
            LiveActivity.device_id == device.id,
            LiveActivity.activity_id == body.activity_id,
        )
    )).scalar_one_or_none()

    if row is None:
        row = LiveActivity(
            device_id=device.id,
            user_id=current_user.id,
            activity_id=body.activity_id,
            match_id=body.match_id,
            schedule_entry_id=body.schedule_entry_id,
            push_token=body.push_token,
            state=STATE_ACTIVE,
            started_by=body.started_by,
            content_version=body.content_version,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.push_token = body.push_token
        row.content_version = body.content_version
        # A token refresh on an activity we had given up on means it is alive.
        row.state = STATE_ACTIVE
        row.ended_at = None
        row.end_reason = None
        row.updated_at = now

    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "update_hint_seconds": 45}


@router.delete("/live-activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def end_activity(
    activity_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The user dismissed it, or the client is tidying up after itself."""
    now = _now()
    await db.execute(
        update(LiveActivity)
        .where(LiveActivity.user_id == current_user.id,
               LiveActivity.activity_id == activity_id,
               LiveActivity.state == STATE_ACTIVE)
        .values(state=STATE_ENDED, ended_at=now, end_reason="client", updated_at=now)
    )
    await db.commit()


@router.get("/live-activities")
async def list_activities(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    What the server believes is running, for reconciliation at launch.

    THE ENDPOINT EVERYONE SKIPS, AND THE ONLY THING THAT STOPS PERMANENT DRIFT.
    Neither side is reliable alone: the client is killed without calling
    DELETE, and the server cannot see a user swiping an activity away. At
    launch the client diffs ActivityKit's running set against this and posts or
    deletes the difference. Without it the two disagree a little more every
    week and nothing ever puts them back.
    """
    rows = (await db.execute(
        select(LiveActivity)
        .where(LiveActivity.user_id == current_user.id,
               LiveActivity.state == STATE_ACTIVE)
        .order_by(LiveActivity.created_at)
    )).scalars().all()
    return {
        "activities": [
            {
                "activity_id": r.activity_id,
                "match_id": r.match_id,
                "schedule_entry_id": r.schedule_entry_id,
                "content_version": r.content_version,
                "state": r.state,
            }
            for r in rows
        ]
    }


# ── Which match to offer ────────────────────────────────────────────────────

# The draw's tier, as a weight. A slam quarter-final and a 250 first round are
# not the same event, and this is the same ranking scoring already uses — read
# from Draw.scoring_tier rather than a second table of category strings.
_TIER_WEIGHT = {"GS": 1.0, "1000": 0.7, "500": 0.45, "250": 0.3}


@router.get("/live-activities/offer")
async def offer(
    match_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The live match most worth putting on this user's Lock Screen.

    THE HARD PART IS THAT EVERYTHING QUALIFIES. This is a full-bracket game, so
    a user has a pick in every live match; on the first Monday of a slam that is
    thirty at once against one Lock Screen. Existence is not a filter, so the
    ranking is — see live_relevance for what it weighs and why.

    Returns {"match": null} rather than a weak suggestion. A prompt for a match
    someone does not care about teaches them to dismiss prompts.

    With ?match_id it validates the client's own choice instead of imposing
    ours: the user tapped a specific match, and the only questions left are
    whether it is live and what to say about it.
    """
    from app.models.prediction import UserPrediction
    from app.models.tournament import Draw, DrawEntry
    from app.services.live_relevance import rank_live_matches
    from app.services.sofascore_live import live_point_for

    live = (await db.execute(
        select(Match).where(Match.sofa_live_json.isnot(None),
                            Match.winner_id.is_(None))
    )).scalars().all()
    if match_id is not None:
        live = [m for m in live if m.id == match_id]
        if not live:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                {"detail": "match_not_live"})
    if not live:
        return {"match": None}

    draw_ids = {m.draw_id for m in live}

    # ONE ROUND TRIP PER TABLE, not per draw. A user in eight active draws on a
    # slam Monday would otherwise be twenty-four queries for a suggestion.
    preds = (await db.execute(
        select(UserPrediction).where(UserPrediction.user_id == current_user.id,
                                     UserPrediction.draw_id.in_(draw_ids))
    )).scalars().all()
    if not preds:
        return {"match": None}

    entered = {p.draw_id for p in preds}
    draws = {d.id: d for d in (await db.execute(
        select(Draw).where(Draw.id.in_(entered)))).scalars().all()}
    all_matches = (await db.execute(
        select(Match).where(Match.draw_id.in_(entered)))).scalars().all()
    entries = (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id.in_(entered)))).scalars().all()

    by_draw_matches, by_draw_entries, by_draw_preds = {}, {}, {}
    for m in all_matches:
        by_draw_matches.setdefault(m.draw_id, []).append(m)
    for e in entries:
        by_draw_entries.setdefault(e.draw_id, []).append(e)
    for p in preds:
        by_draw_preds.setdefault(p.draw_id, []).append(p)

    ranked = []
    for did, draw in draws.items():
        mine = [m for m in live if m.draw_id == did]
        if not mine:
            continue
        ranked += rank_live_matches(
            mine,
            predictions=by_draw_preds.get(did, []),
            all_matches=by_draw_matches.get(did, []),
            entries=by_draw_entries.get(did, []),
            points={m.id: live_point_for(m) for m in mine},
            num_rounds=draw.num_rounds or 1,
            tier_weight=_TIER_WEIGHT.get(draw.scoring_tier, 0.3),
        )
    if not ranked:
        return {"match": None}

    ranked.sort(key=lambda r: -r["score"])
    best, rest = ranked[0], ranked[1:4]
    by_id = {m.id: m for m in live}

    def describe(row):
        m = by_id[row["match_id"]]
        d = draws.get(m.draw_id)
        return {
            "match_id": m.id,
            "draw_id": m.draw_id,
            "event": getattr(d, "name", None),
            "round_number": m.round_number,
            "score": row["score"],
            "reason": row["reason"],
        }

    return {"match": describe(best),
            "reason": best["reason"],
            "score": best["score"],
            # So the user can pick a different one rather than being told.
            "alternatives": [describe(r) for r in rest]}


# ── helpers ─────────────────────────────────────────────────────────────────

async def _device_for(db: AsyncSession, user_id: int, install_id: str) -> AppDevice:
    device = (await db.execute(
        select(AppDevice).where(
            AppDevice.user_id == user_id,
            AppDevice.install_id == install_id,
        )
    )).scalar_one_or_none()
    if device is None:
        # The client is meant to register the device first. Saying so beats
        # silently creating a half-populated row it will never refresh.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "unknown install_id — POST /app/devices first",
        )
    return device


async def _assert_still_live(
    db: AsyncSession, match_id: Optional[int], entry_id: Optional[int]
) -> None:
    """409 on a match that is already over, so the client can clean up.

    Not 422: the request was well formed and was true a moment ago. The
    distinction matters because the client's reaction differs — a 422 is a bug
    to report, a 409 is an activity to end.
    """
    if match_id is not None:
        m = await db.get(Match, match_id)
        if m is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown match")
        if m.winner_id is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"detail": "match_not_live", "state": "completed"},
            )
    else:
        e = await db.get(ScheduleEntry, entry_id)
        if e is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown schedule entry")
        if e.winner_side:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"detail": "match_not_live", "state": "completed"},
            )
