"""
Order-of-play schedule storage.

Three tables, and the split between them is deliberate:

* `schedule_documents` — one row per fetched PDF revision. Cheap, and it is what
  lets the whole schedule be re-derived when the parser improves (Grand Slam
  formats are still unsupported, so it will).
* `schedule_entries` — one row per match slot, UPDATED IN PLACE across
  revisions. Storing a fresh snapshot per revision would be mostly duplicate
  rows: five revisions of a sixty-match day is three hundred rows to record
  perhaps four real changes.
* `schedule_changes` — append-only record of what actually moved. This is where
  the value of revision history lives, and it is what a "your match moved to
  Stadium" notification would read.

The hard part is identity, not storage. On re-parse we must know a row is the
SAME slot as before, or every revision either duplicates or clobbers. Court and
order cannot be the key — inserting one match renumbers everything below it on
that court. The stable identity is the PAIRING: these two players, this day,
this tournament. It survives a court change, a time change and a reorder, which
are precisely the changes worth detecting. See `pairing_key`.
"""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ScheduleDocument(Base):
    """One fetched revision of one tournament's order of play."""

    __tablename__ = "schedule_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tournaments.id"), nullable=False, index=True)
    play_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(String, nullable=False)
    tour: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # ATP | WTA
    # Straight from the HTTP response, so a re-fetch can be skipped cheaply and
    # a revision can be tied back to the exact bytes it came from.
    http_last_modified: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    etag: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    revision_label: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "REVISED 2"
    parse_status: Mapped[str] = mapped_column(String, default="ok")   # ok|empty|not-an-oop|slam|error
    match_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ScheduleEntry(Base):
    """One match slot on one court on one day."""

    __tablename__ = "schedule_entries"
    __table_args__ = (UniqueConstraint("pairing_key", name="uq_schedule_pairing"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tournaments.id"), nullable=False, index=True)
    # Both nullable on purpose. Doubles and qualifying have no draw and no
    # bracket row — qualifying matches are not in `matches` at all (a 128 draw
    # stores rounds 1-7 only), and players who fail to qualify never reach
    # draw_entries. Those rows are still worth storing; they just render
    # without scores or player links.
    draw_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("draws.id"), nullable=True, index=True)
    match_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("matches.id"), nullable=True, index=True)

    play_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    tour: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Kept separate rather than inferred from round_label, because they are
    # filtered independently: singles qualifying is always shown, all doubles
    # defaults off. The sheet states both in its event code — "QS" is
    # qualifying singles, "MD" men's doubles.
    stage: Mapped[str] = mapped_column(String, default="main")          # main|qualifying
    discipline: Mapped[str] = mapped_column(String, default="singles")  # singles|doubles|mixed
    round_label: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # R32|QF|Q1|Q2

    court: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Position on that court for the day. First-class data, not a derived
    # convenience: 12% of slots carry no clock time at all ("Followed by"), so
    # order is the only thing that places them.
    court_order: Mapped[int] = mapped_column(Integer, default=0)

    start_type: Mapped[str] = mapped_column(String, default="tba")
    # fixed | not_before | followed_by | after_event | tba
    start_time_local: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Computed chain (see services/schedule.py). The sort key for the time view,
    # and the only field both views and any future notification agree on.
    expected_start_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True)
    expected_source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # printed | estimated | live | actual
    estimated_duration_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # "BOUZKOVA or JOVIC" — a qualifier or preceding match has not resolved. The
    # extra name is real information, not a parse error.
    is_tbd: Mapped[bool] = mapped_column(Boolean, default=False)

    # INTERNAL ONLY — never serialise these to a client. The sheet's score is a
    # snapshot from whenever that revision was published and can be hours stale;
    # ESPN is the only score a user is ever shown. These exist solely to anchor
    # the expected-start chain on courts ESPN does not cover (it skips doubles
    # and qualifying), where "this slot has a score" proves the court has moved
    # on. Deliberately absent from schemas/schedule.py.
    printed_score: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    printed_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(String, default="scheduled")
    # scheduled | live | completed — only ever set when confidently derivable.

    pairing_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_document_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("schedule_documents.id"), nullable=True)

    players: Mapped[list["ScheduleEntryPlayer"]] = relationship(
        "ScheduleEntryPlayer", back_populates="entry",
        cascade="all, delete-orphan", lazy="selectin")


class ScheduleEntryPlayer(Base):
    """One player in one slot. Two rows per side for doubles, one for singles.

    A child table rather than a JSON blob because the page's whole reason for
    existing is "when do MY picks play", which needs an indexed join from
    draw_entries. A blob cannot answer that.
    """

    __tablename__ = "schedule_entry_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_entry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schedule_entries.id"), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String, nullable=False)      # a | b
    position: Mapped[int] = mapped_column(Integer, default=1)      # 1 | 2
    raw_name: Mapped[str] = mapped_column(String, nullable=False)
    draw_entry_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("draw_entries.id"), nullable=True, index=True)

    entry: Mapped["ScheduleEntry"] = relationship("ScheduleEntry", back_populates="players")


class ScheduleChange(Base):
    """Append-only: what moved, when, and which revision moved it."""

    __tablename__ = "schedule_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_entry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schedule_entries.id"), nullable=False, index=True)
    document_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("schedule_documents.id"), nullable=True)
    field: Mapped[str] = mapped_column(String, nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
