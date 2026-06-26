from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TePlayer(Base):
    """A player as known to Tennis Explorer — canonical raw + normalized name."""

    __tablename__ = "te_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gender: Mapped[str] = mapped_column(String(1), nullable=False)
    name_raw: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # "Sinner Jannik"
    name_norm: Mapped[str] = mapped_column(String, nullable=False)              # "sinner jannik"
    te_slug: Mapped[Optional[str]] = mapped_column(String, nullable=True)       # "sinner-jannik" (TE URL slug for H2H)
    name_display: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "Felix Auger Aliassime" from TE profile <title>
    first_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # "Felix" — derived from name_display vs name_raw
    last_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)    # "Auger Aliassime"
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # fetched from TE player page
    nationality: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # "Canada" — from TE profile "Country:" field

    snapshots: Mapped[list["TeRankingsSnapshot"]] = relationship(
        "TeRankingsSnapshot", back_populates="player", cascade="all, delete-orphan"
    )


class TeRankingsSnapshot(Base):
    """ATP ranking for one player in one week. Immutable once written."""

    __tablename__ = "te_rankings_snapshots"

    player_id: Mapped[int] = mapped_column(ForeignKey("te_players.id"), primary_key=True)
    week_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    elo: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    elo_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    player: Mapped["TePlayer"] = relationship("TePlayer", back_populates="snapshots")


Index("idx_te_snap_week", TeRankingsSnapshot.week_date)
