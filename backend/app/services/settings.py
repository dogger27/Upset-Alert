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

# ── Which source owns a result ───────────────────────────────────────────────
#
# "1" = Sofascore writes winner_id / scores_json / started_at / completed_at.
# "0" = ESPN keeps them and Sofascore stays in its shadow columns.
# Absent  = defer to SOFASCORE_AUTHORITATIVE in the environment.
#
# Stored rather than left to the env var because the cutover is automatic (see
# services/sofa_cutover.py) and a decision the app makes about itself has to
# survive the next restart. An env var can only be changed by a deploy, which
# is exactly the human step the automation exists to remove — and the same step
# that would be needed at 3am to undo it.
SOFA_AUTHORITATIVE = "sofa_authoritative"

# ── Which way out to Sofascore ───────────────────────────────────────────────
#
# "direct" = straight from this host, which is free.
# "proxy"  = through the residential exit, which is metered and costs money.
#
# Stored for the same reason as the line above: the app decides this about
# itself. Sofascore banned the host's own IP on 2026-08-29 and it stayed banned
# for 26 hours; the proxy is what got us back. So proxy is the SAFE state and
# direct is the cheap one, and the app is allowed to try moving from safe to
# cheap on its own — but only rarely, and it must fall back the instant it is
# refused. Left in memory alone, a restart would forget a ban and go straight
# back to poking it.
SOFA_EGRESS = "sofa_egress"
SOFA_EGRESS_DIRECT = "direct"
SOFA_EGRESS_PROXY = "proxy"

# When the direct route was last refused. The probe will not touch it again
# until this is well behind us — retrying into a live ban is what extends it.
SOFA_DIRECT_BLOCKED_AT = "sofa_direct_blocked_at"

_DEFAULTS = {PICK_LOCK_MODE: LOCK_AT_DRAW_START}
_cache: dict[str, str] = {}

# The stored answer, resolved once at startup and again whenever it is written.
# None means "not loaded yet", which is NOT the same as "no", so reads before
# the first load fall back to the environment rather than silently answering
# false and letting a sweep write to the wrong columns.
_sofa_auth: Optional[bool] = None


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


# ── Sofascore authority ──────────────────────────────────────────────────────

async def load_sofa_authoritative(db) -> bool:
    """Resolve the stored answer into the process cache. Call at startup."""
    global _sofa_auth
    stored = await get_setting(db, SOFA_AUTHORITATIVE)
    if stored in ("0", "1"):
        _sofa_auth = stored == "1"
    else:
        from app.core.config import settings as env
        _sofa_auth = bool(env.sofascore_authoritative)
    return _sofa_auth


def sofa_authoritative() -> bool:
    """Does Sofascore own the real result columns right now?

    Synchronous on purpose. It is read inside per-match loops and inside the
    API's serialisation path, neither of which has a session to spare, and the
    value changes about once in the lifetime of the project.
    """
    if _sofa_auth is None:
        from app.core.config import settings as env
        return bool(env.sofascore_authoritative)
    return _sofa_auth


async def set_sofa_authoritative(db, value: bool) -> None:
    """Persist and take effect immediately. Caller commits."""
    global _sofa_auth
    await set_setting(db, SOFA_AUTHORITATIVE, "1" if value else "0")
    _sofa_auth = value
