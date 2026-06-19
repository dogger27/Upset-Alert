from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.tournament import Match, DrawEntry


class UserPrediction(Base):
    """
    A user's predicted winner for one match position in a draw.
    Shared across all leagues the user is in for this tournament —
    the same prediction set is scored against each league's point rules.
    """

    __tablename__ = "user_predictions"
    __table_args__ = (
        UniqueConstraint("user_id", "match_id", name="uq_user_match_prediction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), nullable=False, index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    predicted_winner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("draw_entries.id"), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship("User", back_populates="predictions")
    match: Mapped["Match"] = relationship("Match", foreign_keys=[match_id])
    predicted_winner: Mapped[Optional["DrawEntry"]] = relationship(
        "DrawEntry", foreign_keys=[predicted_winner_id]
    )
