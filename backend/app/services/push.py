"""
Web Push delivery.

Sends to every stored subscription for the given users and prunes the channels
the push service tells us are dead. Deliberately quiet about transient failures
for the same reason the rest of the app is (see http_errors): a push service
being briefly unreachable is not something anyone can act on, and this runs
behind an email that already went out.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import delete, select, update

from app.core.config import settings
from app.database import AsyncSessionLocal
from app.models.push import PushSubscription

logger = logging.getLogger(__name__)

# Push services return these when the subscription is permanently gone — the
# user cleared site data, uninstalled the app, or the channel expired. Anything
# else (429, 5xx, a timeout) is transient and the row stays.
_DEAD_STATUSES = {404, 410}

# Web Push payloads are capped (4KB is the practical floor across services), and
# a notification body longer than a phrase is truncated by the OS anyway.
_MAX_BODY = 180


def push_enabled() -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def _send_one(sub_info: dict, payload: str) -> Optional[int]:
    """
    Blocking send. Returns the HTTP status on failure, None on success.

    Runs in a worker thread — pywebpush is synchronous and would otherwise stall
    the event loop for every subscription in the batch.
    """
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=sub_info,
            data=payload,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            timeout=10,
        )
        return None
    except WebPushException as exc:
        return getattr(exc.response, "status_code", None) or -1
    except Exception:
        return -1


async def send_push_to_users(
    user_ids: Iterable[int],
    *,
    title: str,
    body: str,
    url: str = "/",
    tag: Optional[str] = None,
) -> int:
    """
    Fan out one notification to every subscription owned by user_ids.

    Returns the number of successful deliveries. Never raises: this is a
    secondary channel behind email, and a push outage must not abort the caller
    or leave a batch half-claimed.
    """
    if not push_enabled():
        return 0
    user_ids = list(user_ids)
    if not user_ids:
        return 0

    payload = json.dumps({
        "title": title,
        "body": body[:_MAX_BODY],
        "url": url,
        "tag": tag or "upset-alert",
    })

    async with AsyncSessionLocal() as db:
        subs = (await db.execute(
            select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))
        )).scalars().all()
        # Read into plain tuples before any await that could rollback — the
        # session is reused below for the prune/stamp writes.
        targets = [
            (s.id, s.endpoint, {
                "endpoint": s.endpoint,
                "keys": {"p256dh": s.p256dh, "auth": s.auth},
            })
            for s in subs
        ]

    if not targets:
        return 0

    results = await asyncio.gather(*[
        asyncio.to_thread(_send_one, info, payload) for _, _, info in targets
    ])

    dead_ids = [sid for (sid, _, _), st in zip(targets, results) if st in _DEAD_STATUSES]
    ok_ids = [sid for (sid, _, _), st in zip(targets, results) if st is None]

    async with AsyncSessionLocal() as db:
        if dead_ids:
            await db.execute(
                delete(PushSubscription).where(PushSubscription.id.in_(dead_ids))
            )
        if ok_ids:
            await db.execute(
                update(PushSubscription)
                .where(PushSubscription.id.in_(ok_ids))
                .values(last_success_at=datetime.now(timezone.utc))
            )
        await db.commit()

    failed = len(targets) - len(ok_ids)
    if failed:
        logger.info(
            "Push: %d/%d delivered, %d pruned as gone, %d transient",
            len(ok_ids), len(targets), len(dead_ids), failed - len(dead_ids),
        )
    return len(ok_ids)
