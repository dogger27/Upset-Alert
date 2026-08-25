"""
Retrying a write that lost its snapshot.

"database is locked" from a write path is almost never the timeout it reads
like. There is already a 30s busy_timeout and it does not apply to this case:
a pass that READS rows and then UPDATES them starts its transaction as a
reader and has to upgrade. If any other writer commits in between, SQLite
fails the upgrade IMMEDIATELY rather than waiting, because the snapshot the
reads were made against is gone.

Waiting longer therefore cannot fix it — only re-reading can, which is why
every attempt here gets a FRESH SESSION rather than reusing one. Reusing the
session was the bug that made an earlier version of this retry useless: the
second attempt inherited the first's failed transaction and came back as
PendingRollbackError, which is not an OperationalError and escaped the except.
"""

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

from sqlalchemy.exc import OperationalError, PendingRollbackError

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

T = TypeVar("T")

ATTEMPTS = 4


async def with_write_retry(work: Callable[..., Awaitable[T]], *,
                           attempts: int = ATTEMPTS, what: str = "") -> T:
    """Run `work(db)` under a fresh session, retrying lost-snapshot failures.

    Re-raises anything that is not a lock, and re-raises the lock itself once
    the attempts are spent — the caller decides whether that is worth an alert.
    Backoff is 0.25s doubling, so four attempts span ~1.75s: long enough to
    outlast a competing write, short enough to stay inside a poll tick.
    """
    for attempt in range(attempts):
        try:
            async with AsyncSessionLocal() as db:
                return await work(db)
        except (OperationalError, PendingRollbackError) as exc:
            # PendingRollbackError is a lock wearing a different class: the
            # flush hit "database is locked", the session poisoned itself, and
            # the NEXT query in the same attempt raised the wrapper — which an
            # OperationalError-only except let straight through (EventStream,
            # Udvardy row, 2026-08-24). The message still names the lock, and
            # the fresh session the next attempt takes is precisely the cure
            # the wrapper is demanding.
            if "locked" not in str(exc).lower() or attempt == attempts - 1:
                raise
            logger.info("write locked%s, retry %d/%d",
                        f" ({what})" if what else "", attempt + 1, attempts - 1)
            await asyncio.sleep(0.25 * 2 ** attempt)
    raise AssertionError("unreachable")
