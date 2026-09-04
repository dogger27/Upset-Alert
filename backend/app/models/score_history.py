from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MatchScoreSnapshot(Base):
    """One moment of a live match's score, appended each time the score CHANGES.

    Written by sofascore_live.poll_once on its content-change branch only — one
    row per point, never one per poll — and read back by the score-history
    endpoint so the draw page's popup can scrub through how a match unfolded.

    Deliberately transient: the retention job clears a draw's snapshots one day
    after the draw completes (the user's retention decision), so this table is
    a few megabytes during a tournament and near-empty between them. The final
    score is NOT here and never needs to be — matches.scores_json is the
    record; this is the journey.
    """

    __tablename__ = "match_score_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # none_as_null so an absent snapshot is SQL NULL, not the JSON text 'null'
    # — the same trap models/tournament.py documents on scores_json.
    snap: Mapped[dict] = mapped_column(JSON(none_as_null=True), nullable=False)

    __table_args__ = (
        Index("ix_score_snapshots_match_at", "match_id", "at"),
    )


class ScheduleScoreSnapshot(Base):
    """The same journey for a row with NO bracket match — qualifying singles
    and doubles, which live only as schedule_entries (see sofascore_doubles's
    module docstring for why the schedule row is their one record). Written by
    that sweep's content-change branch, read by the schedule popup's scrubber.
    Same retention spirit as MatchScoreSnapshot, keyed by the day instead of
    a draw: these rows have no draw to complete.

    Snapshots are stored in the SHEET's orientation (side 1 = side a) — the
    sweep flips Sofascore home/away to match the printed row, so the popup's
    orientation logic lines up on the side-a name.
    """

    __tablename__ = "schedule_score_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_entry_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    snap: Mapped[dict] = mapped_column(JSON(none_as_null=True), nullable=False)

    __table_args__ = (
        Index("ix_sched_score_snapshots_entry_at", "schedule_entry_id", "at"),
    )
