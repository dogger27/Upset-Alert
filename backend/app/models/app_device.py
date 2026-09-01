from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppDevice(Base):
    """
    One installation of the native app, for one account.

    NOT a sibling of PushSubscription. That table's identity is the Web Push
    endpoint URL, and it de-dups devices by User-Agent string — a hack its own
    docstring admits cannot be cleaned up, because Apple returns 200 for a
    channel belonging to a deleted app, so delivery failure never prunes it.
    Native has no User-Agent and needs a real device identity.

    IDENTITY IS `install_id`, MINTED BY THE CLIENT AND HELD IN THE KEYCHAIN.
    A UUID the client generates on first launch and this side treats as
    opaque. Keychain rather than app storage is the whole point: keychain items
    survive app deletion on iOS, so install_id outlives the reinstall that
    mints a brand-new device token. That makes "same phone, reinstalled" a row
    UPDATE instead of a duplicate — which is strictly better than the web path
    manages today.

    Deliberately not IDFV: it is Apple-specific where this table has to serve
    Android too, and it RESETS when the user deletes every app from the vendor,
    which is exactly the reinstall case we are trying to survive.

    A phone with two accounts signed in over time is two rows. Only one is
    signed in at a time, and `device_token` is globally unique so the token
    follows the account it currently belongs to rather than being claimed by
    both.
    """

    __tablename__ = "app_devices"
    __table_args__ = (
        # Re-registration from the same install updates in place.
        UniqueConstraint("user_id", "install_id", name="uq_app_devices_user_install"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Opaque to us. Never parsed, never derived from — see the class docstring.
    install_id: Mapped[str] = mapped_column(String, nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)  # ios | android

    # WHICH APNs HOST THIS TOKEN IS VALID ON, and it is a property of the BUILD,
    # not of the account or the server. Xcode and development builds get
    # sandbox tokens; TestFlight and the App Store get production ones. The
    # client tells us; we never infer it. Getting this wrong is the single most
    # common APNs misconfiguration and it presents as a silent non-delivery.
    apns_env: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Null until the user grants notification permission — a device row is
    # worth having before then, so the app can be recognised across launches.
    # Uniqueness is enforced by a PARTIAL index (see database.py), because
    # SQLite treats every NULL as distinct but a plain UNIQUE would still be
    # the wrong statement of intent here.
    device_token: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    bundle_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Diagnostics. Worth storing because "it stopped working on my phone" is
    # otherwise unanswerable, which is the state the Web Push table is in.
    app_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    build: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    os_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    device_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    locale: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    time_zone: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # SOFT DELETE, NOT A ROW DELETE. Apple tells us a token is dead
    # (Unregistered / BadDeviceToken) but the install may well come back — and
    # when it does, the install_id key means the next registration simply
    # clears this and the row heals itself. It also leaves an audit trail for
    # "my phone stopped getting these", which the Web Push table cannot answer
    # at all. Rows disabled for more than 90 days are pruned by the nightly job.
    disabled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disabled_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class PushToStartToken(Base):
    """
    iOS 17.2+ push-to-start token: lets the SERVER begin a Live Activity that
    the user never opened the app to start.

    Its own table rather than a column on AppDevice, because ActivityKit issues
    one token per Attributes TYPE per install. Today there is one type (a
    match); a second — a draw closing, a round digest — is entirely plausible,
    and a table now costs nothing where a column plus a backfill later would.
    """

    __tablename__ = "push_to_start_tokens"
    __table_args__ = (
        UniqueConstraint("device_id", "attributes_type", name="uq_pts_device_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("app_devices.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # The Swift ActivityAttributes type name, e.g. "MatchActivityAttributes".
    attributes_type: Mapped[str] = mapped_column(String, nullable=False)
    token: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
