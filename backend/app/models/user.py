from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.league import League, LeagueMember
    from app.models.prediction import UserPrediction


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Synthetic accounts (e.g. "Highest_Rank") that auto-generate predictions.
    # Never created via /auth/register, so it never picks up notification
    # preferences — the existing opt-in joins in notifications.py already
    # exclude it without needing an explicit filter.
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_code: Mapped[Optional[str]] = mapped_column(String(6), nullable=True)
    verification_code_expires: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # IANA zone id ("America/Vancouver"), captured silently from the browser on
    # load — never asked for. Used only to render deadlines in outgoing email,
    # where the reader's browser isn't present to do it; the site itself reads
    # the zone directly and ignores this. An IANA id rather than an offset so
    # DST resolves itself. Null until a user next opens the site, so every
    # consumer must fall back to UTC.
    timezone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # 'light' or 'dark'. On the account rather than the device so the choice
    # follows the person across desktop, mobile browser and the installed app.
    # NULL means never chosen, which reads as light — the site's default.
    theme: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # 'venue' or 'user' — which clock the order of play renders in. On the
    # account rather than the device so it follows a reader between phone and
    # desktop, the same reasoning as theme.
    schedule_tz: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Last time this account was seen running the INSTALLED app on a phone or
    # tablet — reported by the client, because nothing about a PWA install is
    # visible to the server otherwise. A push subscription used to be the only
    # device signal we had, which under-counts badly: installing the app and
    # enabling notifications are separate acts, and iOS installs are invisible
    # to push detection entirely. Null until the user next opens the app, so
    # this can never be backfilled for an install that already happened.
    mobile_app_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    owned_leagues: Mapped[list["League"]] = relationship("League", back_populates="owner")
    memberships: Mapped[list["LeagueMember"]] = relationship("LeagueMember", back_populates="user")
    predictions: Mapped[list["UserPrediction"]] = relationship("UserPrediction", back_populates="user")
