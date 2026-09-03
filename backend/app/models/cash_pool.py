"""A league's cash pool for one draw.

A league can run a side pot on a draw: the members who paid in are the only
ones the league's standings and picks views for THAT draw show. It is a fact
about one (league, draw) pair — a league may run a pool on one Slam and not
the next — so it is keyed that way, not on the league.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LeagueCashPool(Base):
    __tablename__ = "league_cash_pools"
    __table_args__ = (UniqueConstraint("league_id", "draw_id", name="uq_league_cash_pool"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False, index=True)
    draw_id: Mapped[int] = mapped_column(ForeignKey("draws.id"), nullable=False, index=True)
    # Off keeps the paid list: an admin who switches the pool off and on again
    # should not have to tick everyone a second time.
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    members: Mapped[list["LeagueCashPoolMember"]] = relationship(
        "LeagueCashPoolMember", cascade="all, delete-orphan", lazy="selectin")


class LeagueCashPoolMember(Base):
    """One member who has paid into the pool."""
    __tablename__ = "league_cash_pool_members"
    __table_args__ = (UniqueConstraint("pool_id", "user_id", name="uq_league_cash_pool_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("league_cash_pools.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
