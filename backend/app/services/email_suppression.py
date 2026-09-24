"""Stop mailing addresses that bounce or report us as spam.

Deliverability is judged on the sending domain, and the two things that
damage it fastest at our volume (<100 mails a day) are repeated hard bounces
and mail to someone who pressed "Report spam". Resend records both events on
each email; sync() reads them back and records the address, and allowed()
is the check send_async applies before anything leaves.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

import resend
from sqlalchemy import select

from app.core.config import settings
from app.database import AsyncSessionLocal
from app.models.notification import EmailSuppression

logger = logging.getLogger(__name__)

# Resend's last_event values that mean "do not write again".
_EVENTS = ("bounced", "complained", "suppressed")
# How far back one pass reads. Hourly runs at our volume see ~5 mails an hour;
# 300 is days of headroom, so a missed run or two loses nothing.
_SCAN = 300


def _norm(addr: str) -> str:
    return (addr or "").strip().lower()


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    ts = ts.replace(" ", "T")
    if ts.endswith("+00"):  # Resend writes "…+00"; fromisoformat wants "+00:00"
        ts += ":00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _read_events() -> list[tuple[str, str, Optional[datetime]]]:
    """Blocking: page through Resend's recent sends, newest first."""
    resend.api_key = settings.resend_api_key
    found, after, seen = [], None, 0
    while seen < _SCAN:
        params: dict = {"limit": 100}
        if after:
            params["after"] = after
        page = resend.Emails.list(params)
        data = page.get("data") or []
        for e in data:
            seen += 1
            ev = e.get("last_event")
            if ev in _EVENTS:
                for addr in e.get("to") or []:
                    found.append((_norm(addr), ev, _parse(e.get("created_at"))))
        if not page.get("has_more") or not data:
            break
        after = data[-1]["id"]
    return found


# A complaint outranks a bounce outranks Resend's generic "suppressed": the
# stronger reason decides what may still be sent.
_RANK = {"suppressed": 0, "complained": 1, "bounced": 2}


async def sync() -> int:
    """Record newly bounced / complaining addresses. Returns how many."""
    if not settings.resend_api_key or settings.environment != "production":
        return 0
    from app.services.system_log import app_log
    try:
        events = await asyncio.to_thread(_read_events)
    except Exception as e:  # network or API — next hour tries again
        from app.services.http_errors import describe_exception
        logger.warning("Resend delivery log unreadable: %s", describe_exception(e))
        return 0
    best: dict[str, tuple[str, Optional[datetime]]] = {}
    for addr, ev, at in events:
        if addr and (addr not in best or _RANK[ev] > _RANK[best[addr][0]]):
            best[addr] = (ev, at)
    if not best:
        return 0
    added = []
    async with AsyncSessionLocal() as db:
        rows = {r.email: r for r in (await db.execute(
            select(EmailSuppression).where(EmailSuppression.email.in_(list(best))))).scalars()}
        for addr, (ev, at) in best.items():
            row = rows.get(addr)
            if row is None:
                db.add(EmailSuppression(email=addr, reason=ev, event_at=at))
                added.append((addr, ev))
            elif _RANK[ev] > _RANK.get(row.reason, 0):
                row.reason, row.event_at = ev, at
                added.append((addr, ev))
        await db.commit()
    for addr, ev in added:
        await app_log("info", "notifications",
                      f"Email suppressed ({ev}): {addr} — no further non-essential mail",
                      {"email": addr, "reason": ev})
    return len(added)


async def allowed(recipients: list[str], essential: bool) -> list[str]:
    """The recipients we may still write to.

    essential = the reader asked for this message just now (verification,
    password reset): only a hard bounce stops it, since the address cannot
    receive anything. Everything else also stops at a complaint.
    """
    wanted = [r for r in recipients if r]
    if not wanted:
        return wanted
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(EmailSuppression).where(
            EmailSuppression.email.in_([_norm(r) for r in wanted])))).scalars().all()
    blocked = {r.email for r in rows if r.reason == "bounced" or not essential}
    return [r for r in wanted if _norm(r) not in blocked]
