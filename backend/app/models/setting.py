from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppSetting(Base):
    """
    A single site-wide setting, keyed by name.

    A key/value table rather than a one-row settings table with a column per
    option: settings arrive one at a time, and a new column means a migration
    plus a model change plus a schema change for something that is, at bottom,
    one string. Reads go through app.services.settings, which caches and applies
    the default, so nothing outside that module ever handles a missing row.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
