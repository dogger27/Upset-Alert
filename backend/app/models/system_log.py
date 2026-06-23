from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    level: Mapped[str] = mapped_column(String, nullable=False)     # "warning" | "error"
    category: Mapped[str] = mapped_column(String, nullable=False)  # "rankings" | "espn" | ...
    message: Mapped[str] = mapped_column(String, nullable=False)
    detail_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
