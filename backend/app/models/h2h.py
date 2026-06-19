from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class H2HCache(Base):
    """Cached head-to-head data from Tennis Explorer, keyed by canonical (sorted) slug pair."""

    __tablename__ = "h2h_cache"

    slug_a: Mapped[str] = mapped_column(String, primary_key=True)  # alphabetically first
    slug_b: Mapped[str] = mapped_column(String, primary_key=True)  # alphabetically second
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    data_json: Mapped[dict] = mapped_column(JSON, nullable=False)
