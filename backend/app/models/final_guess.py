"""A user's two guesses about the singles final — the tiebreak (owner, 2026-09-18).

Asked when a user enters a draw: how many aces the champion will hit in the
final, and how many minutes it will last. Once the final is played, ties on
points are broken by whoever came closest on aces, then on minutes (see
scoring.tiebreak_key). One row per user per draw, editable until the picks
lock; a walkover final is 0 aces and 0 minutes, which is why 0 is a valid
answer and the slider's floor.
"""
from datetime import datetime, timezone

from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DrawFinalGuess(Base):
    __tablename__ = "draw_final_guesses"
    __table_args__ = (UniqueConstraint("user_id", "draw_id", name="uq_final_guess_user_draw"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    draw_id: Mapped[int] = mapped_column(ForeignKey("draws.id"), nullable=False, index=True)
    # NULLABLE, unlike the other two: this question was added on 2026-09-19
    # and every guess stored before it has no answer here. Null means "never
    # answered", which holds the default exactly as an untouched slider does.
    final_sets: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    final_aces: Mapped[int] = mapped_column(Integer, nullable=False)
    final_duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc),
                                                 onupdate=lambda: datetime.now(timezone.utc))
