from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NotificationPreference(Base):
    """One row per enabled notification preference per user. Absence = disabled (opt-in)."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    pref_key: Mapped[str] = mapped_column(String, primary_key=True)
