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
