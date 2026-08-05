from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AlertSignature(Base):
    """
    Alert state for one distinct *problem* (not one log row).

    system_logs records every occurrence — the same broken Wikipedia title
    logged 65 times in three days is 65 rows but one problem. A signature is
    the grouping key for that problem (see alerts._fingerprint), and
    last_alerted_at is the recurrence gate: while it is younger than
    ALERT_RECURRENCE_HOURS the problem's repeats are counted, not emailed.

    Persisted rather than held in memory because the gate has to outlive a
    deploy — app_log's own in-process dedup cache resets on every restart,
    which is exactly why those 65 occurrences reached the table in the first
    place.
    """

    __tablename__ = "alert_signatures"

    fingerprint: Mapped[str] = mapped_column(String, primary_key=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    # Most recent raw message for this signature — what the email actually
    # shows. The fingerprint is a hash, so without this there'd be no way to
    # tell from the table which problem a row refers to.
    sample_message: Mapped[str] = mapped_column(Text, nullable=False)
    first_alerted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_alerted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    alert_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AlertEmail(Base):
    """
    One row per alert digest actually delivered.

    Doubles as the daily-budget ledger: "emails sent today" is a COUNT over
    this table, so the cap survives process restarts. An in-memory counter
    would reset on every deploy, and a deploy is precisely when a burst of new
    errors is most likely — the cap would be at its weakest exactly when it
    matters most.
    """

    __tablename__ = "alert_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Newline-joined fingerprints included in this digest — lets you answer
    # "why did I get this email?" from the table alone.
    fingerprints: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
