"""
Email alerting on system_logs errors and warnings.

Digest-style and deliberately quiet. Every scan gathers the error/warning rows
of the last ALERT_LOOKBACK_HOURS, groups them into *signatures* (same problem,
many occurrences), and emails only the signatures not already under an alert:

- **Recurrence gate** — a signature that has been alerted is not alerted again
  for ALERT_RECURRENCE_HOURS (24h). Its repeats in between are counted and
  reported the next time it does qualify ("47 times since the last alert"), so
  a stuck problem still gets a daily nudge without a message per occurrence.
- **Daily cap** — at most ALERT_MAX_PER_DAY digests per calendar day, in the
  local zone below, spaced at least ALERT_MIN_GAP_HOURS apart. The gap stops
  three unrelated morning failures from spending the whole day's budget before
  lunch.
- **Nothing is dropped.** A signature held back by the cap or the gap is simply
  left un-alerted, so the next digest with budget picks it up. The scan derives
  everything from system_logs plus alert_signatures each time — there is no
  cursor to lose, and a restart mid-alert re-sends rather than swallows.

Why signatures and not log rows: the 30 days before this was written held 209
error rows but only 8 distinct problems, one of them logged 65 times. Alerting
per row would have been 209 emails for 8 things worth knowing.
"""

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.core.config import settings
from app.database import AsyncSessionLocal
from app.models.alert import AlertEmail, AlertSignature
from app.models.system_log import SystemLog

logger = logging.getLogger(__name__)

ALERT_TO = "pdwiens@gmail.com"
ALERT_LEVELS = ("error", "warning")
# The alerter's own log rows are written under this category and excluded from
# every scan. Without that, one failed alert email logs an error, which the
# next scan sees as a new problem, which sends an alert, which fails...
ALERT_CATEGORY = "alerts"

ALERT_LOOKBACK_HOURS = 48.0
ALERT_RECURRENCE_HOURS = 24.0
# A signature quiet for longer than this is not re-alerted when its 24h gate
# expires. Without it, one straggler row logged a minute after an alert sat
# in the lookback window and re-armed the whole alert a day later — for a
# problem whose own email said "nothing since". Quiet means resolved or
# already-handled; only a problem still producing rows is worth a re-send.
ALERT_QUIET_HOURS = 6.0
ALERT_MAX_PER_DAY = 3
ALERT_MIN_GAP_HOURS = 4.0
ALERT_MAX_ISSUES_PER_EMAIL = 20
# The day the cap is counted against, and the zone every timestamp in the email
# is rendered in. UTC would roll the budget over at 5pm local, mid-evening.
ALERT_TZ = ZoneInfo("America/Los_Angeles")

_DIGITS = re.compile(r"\d+")
_WHITESPACE = re.compile(r"\s+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def log_fingerprint(level: str, category: str, message: str) -> str:
    """
    Stable id for "the same problem", derived from the message with its
    variable parts blanked.

    Public because the admin Logs panel groups on it too (routers/admin.py):
    what the panel shows as one collapsed problem and what earns one alert
    email are the same thing by construction, so the two can't drift apart as
    the normalisation rules change.

    Numbers and email addresses are what get normalised away, and that is
    deliberate: it collapses the year/id/count/recipient that differ between
    occurrences of one problem ("Page not found: 2026 Cincinnati Open ...")
    while keeping the parts that distinguish genuinely different problems — the
    Men's and Women's Cincinnati draws stay two signatures, because that is two
    titles to go and fix.

    Addresses matter as much as digits here. "Email send failed: … → a@b.com"
    fingerprinted per recipient, so a mailer that was down for one send to four
    people read as four separate problems: four rows in the panel, four of the
    twenty slots in a digest, and four entries competing for a three-a-day
    budget. It is one broken mailer. Normalising the address says so.
    """
    normalised = _EMAIL.sub("<email>", message)
    normalised = _DIGITS.sub("#", normalised)
    normalised = _WHITESPACE.sub(" ", normalised).strip()
    raw = f"{level}|{category}|{normalised}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands back naive datetimes; every stored value is UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _day_start(now: datetime) -> datetime:
    """Midnight ALERT_TZ preceding `now`, as UTC — the daily budget boundary."""
    local_midnight = now.astimezone(ALERT_TZ).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return local_midnight.astimezone(timezone.utc)


async def scan_and_alert() -> None:
    """
    One pass: gather → group → filter → send. Safe to call on any cadence and
    at startup; it is idempotent apart from the emails it decides to send.
    """
    if not settings.resend_api_key or settings.environment != "production":
        return  # Same guard as email.send_async — dev must never page anyone.

    now = datetime.now(timezone.utc)
    lookback_start = now - timedelta(hours=ALERT_LOOKBACK_HOURS)

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(SystemLog)
                .where(
                    SystemLog.level.in_(ALERT_LEVELS),
                    SystemLog.category != ALERT_CATEGORY,
                    # oop_verify has its own per-event email channel
                    # (email.send_oop_status) — routing it through the digest
                    # too would double every needs-attention message. Its send
                    # FAILURES log under other categories and still digest.
                    SystemLog.category != "oop_verify",
                    SystemLog.created_at >= lookback_start,
                )
                .order_by(SystemLog.created_at)
            )
        ).scalars().all()
        if not rows:
            return

        # Group first, then look up state — the number of distinct signatures is
        # tiny next to the number of rows.
        grouped: dict[str, list[SystemLog]] = {}
        for row in rows:
            grouped.setdefault(
                log_fingerprint(row.level, row.category, row.message), []
            ).append(row)

        known = {
            sig.fingerprint: sig
            for sig in (
                await db.execute(
                    select(AlertSignature).where(
                        AlertSignature.fingerprint.in_(list(grouped))
                    )
                )
            ).scalars().all()
        }

        pending = []
        for fingerprint, occurrences in grouped.items():
            sig = known.get(fingerprint)
            last_alerted = _as_utc(sig.last_alerted_at) if sig else None
            if last_alerted and (now - last_alerted) < timedelta(hours=ALERT_RECURRENCE_HOURS):
                continue  # Under an active alert — count it, don't re-send.

            # Count only what has happened since the last alert, so a recurring
            # problem reports "since I last told you" rather than a running
            # total that keeps climbing across every alert.
            since = max(last_alerted, lookback_start) if last_alerted else lookback_start
            fresh = [o for o in occurrences if _as_utc(o.created_at) > since]
            if not fresh:
                continue  # Already-alerted problem with nothing new in the window.
            newest = _as_utc(fresh[-1].created_at)
            if newest and (now - newest) > timedelta(hours=ALERT_QUIET_HOURS):
                continue  # The tail of an alerted incident, long gone quiet.

            latest = fresh[-1]
            pending.append({
                "fingerprint": fingerprint,
                "level": latest.level,
                "category": latest.category,
                "message": latest.message,
                "detail": latest.detail_json or {},
                "count": len(fresh),
                "first_seen": _as_utc(fresh[0].created_at),
                "last_seen": _as_utc(latest.created_at),
                "is_recurrence": last_alerted is not None,
                "last_alerted": last_alerted,
                "previous_alerts": sig.alert_count if sig else 0,
            })

        if not pending:
            return

        # --- budget ----------------------------------------------------------
        day_start = _day_start(now)
        sent_today = (
            await db.execute(
                select(func.count())
                .select_from(AlertEmail)
                .where(AlertEmail.sent_at >= day_start)
            )
        ).scalar() or 0
        if sent_today >= ALERT_MAX_PER_DAY:
            logger.info(
                "Alert digest held: daily cap reached (%d/%d), %d issue(s) waiting",
                sent_today, ALERT_MAX_PER_DAY, len(pending),
            )
            return

        # Fetch the row rather than func.max(sent_at): selecting the mapped
        # column guarantees the DateTime result processor runs, so this is a
        # datetime and not the raw SQLite string the arithmetic below would
        # choke on.
        last_sent = _as_utc(
            (await db.execute(
                select(AlertEmail.sent_at).order_by(AlertEmail.sent_at.desc()).limit(1)
            )).scalar()
        )
        if last_sent and (now - last_sent) < timedelta(hours=ALERT_MIN_GAP_HOURS):
            logger.info(
                "Alert digest held: within %.1fh of the last one, %d issue(s) waiting",
                ALERT_MIN_GAP_HOURS, len(pending),
            )
            return

        # Errors before warnings, then loudest first — the digest is read top-down.
        pending.sort(key=lambda i: (i["level"] != "error", -i["count"]))
        remaining_today = ALERT_MAX_PER_DAY - sent_today - 1

        # One event can produce dozens of distinct signatures at once — a
        # rankings refresh logs an unmatched-player warning per player, and each
        # name fingerprints separately. Cap the email and carry the rest: the
        # overflow is left un-alerted, so it goes out in the next digest rather
        # than being marked sent behind a 24h gate it was never shown through.
        overflow = len(pending) - ALERT_MAX_ISSUES_PER_EMAIL
        if overflow > 0:
            pending = pending[:ALERT_MAX_ISSUES_PER_EMAIL]

        from app.services.email import send_system_alert_digest

        delivered = await send_system_alert_digest(
            ALERT_TO, pending, remaining_today=remaining_today,
            held_back=max(0, overflow), tz=ALERT_TZ,
        )
        if not delivered:
            # Leave every signature un-alerted and the budget unspent: the next
            # scan retries the same digest rather than losing it.
            logger.error("Alert digest send failed — %d issue(s) held for retry", len(pending))
            return

        for item in pending:
            sig = known.get(item["fingerprint"])
            if sig:
                sig.last_alerted_at = now
                sig.sample_message = item["message"]
                sig.level = item["level"]
                sig.alert_count += 1
            else:
                db.add(AlertSignature(
                    fingerprint=item["fingerprint"],
                    level=item["level"],
                    category=item["category"],
                    sample_message=item["message"],
                    first_alerted_at=now,
                    last_alerted_at=now,
                    alert_count=1,
                ))
        db.add(AlertEmail(
            sent_at=now,
            issue_count=len(pending),
            error_count=sum(1 for i in pending if i["level"] == "error"),
            warning_count=sum(1 for i in pending if i["level"] == "warning"),
            fingerprints="\n".join(i["fingerprint"] for i in pending),
        ))
        await db.commit()

    logger.info("Alert digest sent: %d issue(s), %d left today", len(pending), remaining_today)
    await _log_alert(
        "info",
        f"System alert digest sent: {len(pending)} issue(s)",
        {"issues": [{"level": i["level"], "category": i["category"],
                     "message": i["message"], "count": i["count"]} for i in pending],
         "remaining_today": remaining_today},
    )


async def _log_alert(level: str, message: str, detail: Optional[dict] = None) -> None:
    """
    Write the alerter's own audit trail, always under ALERT_CATEGORY so that
    scan_and_alert's own output can never become input to the next scan.
    """
    from app.services.system_log import app_log

    await app_log(level, ALERT_CATEGORY, message, detail)
