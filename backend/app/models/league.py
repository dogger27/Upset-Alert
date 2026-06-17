import random
import secrets
import string
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


SCORING_MODES = ("classic", "atp_wta", "upset_bonus", "custom")


class League(Base):
    """
    A group of users who compete across tournaments.
    Scoring mode is per-league; predictions are per (user, tournament).
    The leaderboard for a group is filtered to members who made picks for a given tournament.
    """

    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # classic / atp_wta / upset_bonus / custom
    scoring_mode: Mapped[str] = mapped_column(String, default="classic")
    # For "custom" mode: {round_number (str): points (int)}
    custom_points: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    show_real_name: Mapped[bool] = mapped_column(Boolean, default=False)
    # Random 5-char uppercase alphanumeric invite code
    invite_code: Mapped[str] = mapped_column(
        String, unique=True,
        default=lambda: ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    )
    allow_member_invites: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    owner: Mapped["User"] = relationship("User", back_populates="owned_leagues")
    members: Mapped[list["LeagueMember"]] = relationship(
        "LeagueMember", back_populates="league", cascade="all, delete-orphan"
    )


class LeagueMember(Base):
    __tablename__ = "league_members"
    __table_args__ = (UniqueConstraint("league_id", "user_id", name="uq_league_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    league: Mapped["League"] = relationship("League", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="memberships")
