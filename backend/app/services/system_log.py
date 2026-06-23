"""
Structured in-DB logging for silent failures and degraded operation.

app_log() writes a row to system_logs — visible in the Admin panel.
Use dedup_key to suppress repeated identical entries (default: 1 hour TTL).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_dedup_cache: dict[str, datetime] = {}
_DEDUP_TTL = timedelta(hours=1)


async def app_log(
    level: str,
    category: str,
    message: str,
    detail: Optional[dict] = None,
    dedup_key: Optional[str] = None,
    dedup_hours: float = 1.0,
) -> None:
    """
    Write a structured log entry to system_logs.

    level:      "warning" or "error"
    category:   "rankings" | "espn" | "h2h" | "scheduler" | "notifications" |
                "discovery" | "scraper"
    dedup_key:  If set, suppress duplicate entries within dedup_hours.
    """
    if dedup_key:
        now = datetime.now(timezone.utc)
        last = _dedup_cache.get(dedup_key)
        if last and (now - last) < timedelta(hours=dedup_hours):
            return
        _dedup_cache[dedup_key] = now

    from app.database import AsyncSessionLocal
    from app.models.system_log import SystemLog

    try:
        async with AsyncSessionLocal() as db:
            entry = SystemLog(
                level=level,
                category=category,
                message=message,
                detail_json=detail or {},
            )
            db.add(entry)
            await db.commit()
    except Exception as exc:
        logger.error("Failed to write system log: %s", exc)
