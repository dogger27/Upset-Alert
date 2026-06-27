from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TournamentResult(Base):
    """Final standing for one user in one group (global or league) for one tournament."""

    __tablename__ = "tournament_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    draw_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    league_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # NULL = global
    league_name: Mapped[str] = mapped_column(String, nullable=False)           # "Global" or league name
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    total_participants: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[float] = mapped_column(Float, nullable=False)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False)
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "draw_id", "league_id", name="uq_result_user_tourn_league"),
    )
