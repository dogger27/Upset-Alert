from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PushSubscription(Base):
    """
    One browser's Web Push channel for a user.

    The row's existence IS the opt-in — deliberately not a
    notification_preferences key, because PUT /auth/me/notifications deletes
    every pref row for the user and re-inserts only what the UI sent, so a push
    key absent from that payload would be silently switched off every time
    someone saved their email settings.

    A user has one row per browser/device they enabled push on, so the same
    account can be subscribed on a phone and a laptop independently. endpoint is
    unique because it is the push service's own identifier for that channel;
    re-subscribing the same browser returns the same endpoint and must update
    the existing row rather than accumulate duplicates.
    """

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Browser-supplied encryption material; opaque to us, passed to pywebpush.
    p256dh: Mapped[str] = mapped_column(String, nullable=False)
    auth: Mapped[str] = mapped_column(String, nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # Bumped on every successful send; a channel that has never worked and is
    # weeks old is a good candidate for pruning if this table ever grows.
    last_success_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
