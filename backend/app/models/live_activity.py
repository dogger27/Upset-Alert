from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# STATES
#  active — running on someone's Lock Screen; we push updates to it.
#  ended  — we sent event:"end". Terminal, and the normal finish.
#  dead   — APNs told us the token is finished (ExpiredActivityToken) or the
#           reaper gave up. Terminal, and NOT an error: an activity the user
#           dismissed reaches here and that is simply what dismissal looks
#           like from the server's side.
STATE_ACTIVE = "active"
STATE_ENDED = "ended"
STATE_DEAD = "dead"


class LiveActivity(Base):
    """
    One Live Activity running on one device for one match.

    A different lifecycle from anything else in this codebase, and the
    differences are what the columns are for:

      * The push token is PER ACTIVITY, not per device, and it ROTATES —
        ActivityKit reissues it periodically and on system events. Identity is
        therefore (device_id, activity_id); push_token is mutable data, and
        deliberately not unique.

      * An activity has a hard ceiling of a few hours whatever we do, so a row
        here is short-lived by nature. The reaper ends anything untouched for
        8 hours; nothing is expected to live longer.

      * Nothing guarantees we are told when it ends. The client should call
        DELETE, and often will not — the app is killed, the phone dies, the
        user swipes it away. Every terminal path must therefore be reachable
        from the server alone.
    """

    __tablename__ = "live_activities"
    __table_args__ = (
        UniqueConstraint("device_id", "activity_id", name="uq_la_device_activity"),
        # The dispatcher's hot query: "which activities care about these
        # matches". Both shapes indexed because doubles and qualifying rows
        # have no bracket match and hang off the schedule entry instead.
        Index("ix_la_match_state", "match_id", "state"),
        Index("ix_la_entry_state", "schedule_entry_id", "state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("app_devices.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # DENORMALISED ON PURPOSE. The dispatcher runs on every score change and
    # needs the user id to splice in that user's own pick; making the hot path
    # a three-way join to reach it would be paying a join per push.
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # ActivityKit's own Activity.id, as the client reports it.
    activity_id: Mapped[str] = mapped_column(String, nullable=False)

    # Exactly one of these is set. Singles carry their score on the bracket
    # match; doubles and qualifying have no bracket row and carry it on the
    # schedule entry — the same split the rest of the app already lives with.
    match_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    schedule_entry_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    push_token: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, default=STATE_ACTIVE)
    started_by: Mapped[str] = mapped_column(String, nullable=False)  # client | push_to_start

    # THE MOST IMPORTANT COLUMN HERE.
    # ActivityKit decodes content-state into a Swift Codable struct. Change the
    # shape and every install that has not updated stops moving — SILENTLY,
    # because APNs still returns 200 for a payload the app cannot decode. With
    # a version recorded per activity the server can keep emitting v1 to v1
    # clients while v2 ships, instead of discovering the break from a user.
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Throttle bookkeeping. Written on state transitions and flushed
    # periodically — NEVER once per push. At fifty concurrent activities that
    # would be about one write a second against a single-writer SQLite that has
    # already had lock storms, and it would only show up during a final.
    last_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The aps.timestamp we last sent. ActivityKit DISCARDS an update whose
    # timestamp is not greater than the previous one, so with coalescing and
    # retries in play this has to be tracked rather than assumed from the clock.
    last_sent_timestamp: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_sent_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    high_priority_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # match_complete | no_result | stale | client | expired_token | runaway
    end_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
