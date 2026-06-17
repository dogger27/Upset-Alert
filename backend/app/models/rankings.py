from datetime import date

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

    snapshots: Mapped[list["TeRankingsSnapshot"]] = relationship(
        "TeRankingsSnapshot", back_populates="player", cascade="all, delete-orphan"
    )


class TeRankingsSnapshot(Base):
    """ATP ranking for one player in one week. Immutable once written."""

    __tablename__ = "te_rankings_snapshots"

    player_id: Mapped[int] = mapped_column(ForeignKey("te_players.id"), primary_key=True)
    week_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    player: Mapped["TePlayer"] = relationship("TePlayer", back_populates="snapshots")


Index("idx_te_snap_week", TeRankingsSnapshot.week_date)
