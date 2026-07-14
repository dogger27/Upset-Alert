from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NotificationPreference(Base):
    """One row per enabled notification preference per user. Absence = disabled (opt-in)."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    pref_key: Mapped[str] = mapped_column(String, primary_key=True)


class RoundCompleteNotification(Base):
    """
    Idempotency + audit record: one row per (draw, round) once round-standings
    emails have been sent. Prevents a re-triggered round-completion event
    (e.g. a match's winner getting cleared and re-set by a later scrape) from
    sending the same round-complete email batch twice.
    """

    __tablename__ = "round_complete_notifications"
    __table_args__ = (UniqueConstraint("draw_id", "round_number", name="uq_round_complete_draw_round"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draw_id: Mapped[int] = mapped_column(Integer, ForeignKey("draws.id", ondelete="CASCADE"), nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class MatchStartNotification(Base):
    """
    Idempotency + audit record: one row per draw once the "Play has started"
    email has been sent. draw_id is the primary key (not autoincrement) so the
    claiming INSERT relies on the primary-key uniqueness itself — two racing
    callers (e.g. a process restart racing an in-flight fire-and-forget send)
    can't both succeed.
    """

    __tablename__ = "match_start_notifications"

    draw_id: Mapped[int] = mapped_column(Integer, ForeignKey("draws.id", ondelete="CASCADE"), primary_key=True)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class DrawReleaseNotification(Base):
    """
    Idempotency + audit record: one row per draw once the "Draw released"
    email has been sent. See MatchStartNotification for why draw_id is the
    primary key. This is the hard guard behind scheduler.py's coarse
    draw_release_notified_at column check — that column decides WHEN to fire
    (after the stability cooldown), this table decides IF it's already fired.
    """

    __tablename__ = "draw_release_notifications"

    draw_id: Mapped[int] = mapped_column(Integer, ForeignKey("draws.id", ondelete="CASCADE"), primary_key=True)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class TournamentCompleteNotification(Base):
    """
    Idempotency + audit record: one row per draw once "final standings" emails
    (and the draw-history results persistence that rides along with them) have
    been sent. Same role as DrawReleaseNotification, backstopping the coarse
    Draw.completion_notified_at column check against overlapping/racing
    callers (notify_tournament_complete can be triggered by the same
    process-restart race as match-start — see _refresh_active_tournaments's
    force_refresh=True call at startup).
    """

    __tablename__ = "tournament_complete_notifications"

    draw_id: Mapped[int] = mapped_column(Integer, ForeignKey("draws.id", ondelete="CASCADE"), primary_key=True)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
