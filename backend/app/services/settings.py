"""
Site-wide settings, read through one place so a missing row is never a caller's
problem.

Cached in-process because these are read on the hot path (every pick save, every
draw load) and change roughly never. The cache is per-process and the site runs
one container, so a write invalidating its own process is enough; a deploy
restarts everything anyway.
"""

import logging
from typing import Optional

from sqlalchemy import select

from app.models.setting import AppSetting

logger = logging.getLogger(__name__)

# ── Pick-lock mode ───────────────────────────────────────────────────────────
#
# How a draw decides that predictions can no longer be changed.
PICK_LOCK_MODE = "pick_lock_mode"

# The original rule: the whole bracket locks the moment the draw starts, on the
# evidence espn_monitor gathers (picks_locked_at) or the scheduled deadline.
LOCK_AT_DRAW_START = "draw_start"

# Each match freezes on its own as it goes in progress, and the bracket as a
# whole stays open until every first-round match is complete. Rounds 2+ are
# therefore locked from that same moment — they were never individually
# playable, they simply stop being editable along with everything else.
LOCK_PROGRESSIVE_R1 = "r1_progressive"

LOCK_MODES = (LOCK_AT_DRAW_START, LOCK_PROGRESSIVE_R1)

_DEFAULTS = {PICK_LOCK_MODE: LOCK_AT_DRAW_START}
_cache: dict[str, str] = {}


async def get_setting(db, key: str) -> str:
    """The stored value, or the documented default when nothing is stored."""
    if key in _cache:
        return _cache[key]
    row = (await db.execute(
        select(AppSetting.value).where(AppSetting.key == key)
    )).scalar_one_or_none()
    value = row if row is not None else _DEFAULTS.get(key, "")
    _cache[key] = value
    return value


async def set_setting(db, key: str, value: str) -> None:
    """Write a setting and drop the cached read. Caller commits."""
    existing = await db.get(AppSetting, key)
    if existing is None:
        db.add(AppSetting(key=key, value=value))
    else:
        existing.value = value
        from datetime import datetime, timezone
        existing.updated_at = datetime.now(timezone.utc)
    _cache.pop(key, None)


async def global_lock_mode(db) -> str:
    mode = await get_setting(db, PICK_LOCK_MODE)
    return mode if mode in LOCK_MODES else LOCK_AT_DRAW_START


async def resolve_draw_lock_mode(db, draw, commit: bool = True) -> str:
    """
    The mode this draw uses — stamping it if it has none yet.

    Stamped rather than inherited on every read, because a draw has to record
    the rules it was actually PLAYED under. Inheriting live would rewrite
    history the moment the site-wide default changed: a tournament finished
    months ago under one rule would start claiming it used the other.

    So the global setting is only ever a default for draws that have not been
    stamped, and an admin override on a single draw is just an early stamp.
    """
    current = getattr(draw, "pick_lock_mode", None)
    if current in LOCK_MODES:
        return current

    mode = await global_lock_mode(db)
    draw.pick_lock_mode = mode
    if commit:
        try:
            await db.commit()
        except Exception:
            # A read path stamping a value is a convenience, not the caller's
            # business — a failure here must not turn loading a draw into a 500.
            await db.rollback()
            logger.debug("Could not stamp lock mode on draw %s", getattr(draw, "id", "?"))
    return mode
