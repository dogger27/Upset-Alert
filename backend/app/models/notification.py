from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NotificationPreference(Base):
    """One row per enabled notification preference per user. Absence = disabled."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    pref_key: Mapped[str] = mapped_column(String, primary_key=True)


class NotificationOptOut(Base):
    """
    One row per notification type a user has explicitly switched OFF.

    Notifications default to ON, so an absent preference row is ambiguous on its
    own: it means either "never chosen" or "deliberately declined", and the
    enrolment pass in database.py has to tell those apart. Recording the refusal
    is what lets it enrol everyone into every type — including types added later
    — without ever re-subscribing someone who said no.

    A separate table rather than a flag on NotificationPreference: every query
    that decides who receives something reads "a row exists for this key", and
    keeping that true means none of the delivery paths had to change to support
    this.

    Written by BOTH ways of declining — the settings grid and the one-click
    unsubscribe link in an email footer. The unsubscribe case is the one that
    matters most: without a record, the next enrolment pass would quietly put
    them back on the list they just left.
    """

    __tablename__ = "notification_opt_outs"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    pref_key: Mapped[str] = mapped_column(String, primary_key=True)
    opted_out_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class RoundCompleteNotification(Base):
    """
    Idempotency + audit record: one row per (draw, round) once round-standings
    emails have been sent. Prevents a re-triggered round-completion event
    (e.g. a match's winner getting cleared and re-set by a later scrape) from
    sending the same round-complete email batch twice.
    """

    __tablename__ = "round_complete_notifications"
    __table_args__ = (UniqueConstraint("draw_id", "round_number", name="uq_round_complete_draw_round"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draw_id: Mapped[int] = mapped_column(Integer, ForeignKey("draws.id", ondelete="CASCADE"), nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Now stamped when the round is DETECTED complete, which is also when the
    # unique constraint claims it. Emailing happens later, once the week's other
    # draws have reached the same round (see scheduler._notify_pending_round_digests).
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # Null while a detected round is still waiting for its week's digest to go
    # out. Backfilled to sent_at for every pre-existing row, so switching to the
    # digest can't re-send months of historical rounds.
    digest_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class MatchStartNotification(Base):
    """
    Idempotency + audit record: one row per draw once the "Play has started"
    email has been sent. draw_id is the primary key (not autoincrement) so the
    claiming INSERT relies on the primary-key uniqueness itself — two racing
    callers (e.g. a process restart racing an in-flight fire-and-forget send)
    can't both succeed.
    """

    __tablename__ = "match_start_notifications"

    draw_id: Mapped[int] = mapped_column(Integer, ForeignKey("draws.id", ondelete="CASCADE"), primary_key=True)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class DrawReleaseNotification(Base):
    """
    Idempotency + audit record: one row per draw once the "Draw released"
    email has been sent. See MatchStartNotification for why draw_id is the
    primary key. This is the hard guard behind scheduler.py's coarse
    draw_release_notified_at column check — that column decides WHEN to fire
    (after the stability cooldown), this table decides IF it's already fired.
    """

    __tablename__ = "draw_release_notifications"

    draw_id: Mapped[int] = mapped_column(Integer, ForeignKey("draws.id", ondelete="CASCADE"), primary_key=True)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class DrawChangeEvent(Base):
    """
    One player swap in a draw people are already competing in: a withdrawal
    filled by a lucky loser, or a qualifier finally placed into its slot.

    Recorded by _do_scrape at the moment the swap is applied, because that is
    the only place the OLD name still exists — the upsert overwrites DrawEntry
    in place (deliberately, so picks follow the slot; see
    [[reference_qualifier_pick_persistence]]), and one commit later there is
    nothing left to diff against.

    entry_id is the DrawEntry that was rewritten, and it is what makes the
    notification personal: a user whose prediction points at that same entry id
    picked the player who has just been replaced. Stored as a plain integer
    rather than a foreign key — a draw restructure can delete the row it names,
    and a dangling reference here should not block that delete or lose the
    audit record of a change that genuinely happened.

    notified_at is both the audit stamp and the claim: a batch is claimed with
    a conditional UPDATE ... WHERE notified_at IS NULL before anything is sent,
    so two overlapping dispatch runs cannot both send it.
    """

    __tablename__ = "draw_change_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draw_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("draws.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    bracket_position: Mapped[int] = mapped_column(Integer, nullable=False)
    # "replaced" — a named player gave way to another; "filled" — an empty
    # placeholder slot (almost always a Q) got its player.
    kind: Mapped[str] = mapped_column(String, nullable=False)
    old_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    new_name: Mapped[str] = mapped_column(String, nullable=False)
    old_entry_type: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    new_entry_type: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    old_seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class QualifiersAddedNotification(Base):
    """
    Idempotency + audit record: one row per draw once the "qualifiers are in"
    message has been sent. draw_id is the primary key, so the claiming INSERT is
    itself the guard — see MatchStartNotification for the same reasoning.

    This one is stricter than the other claim tables and deliberately so. Draw
    changes are a running commentary: every withdrawal is news, so a draw sends
    as many as it has. Qualifiers are a single event — the qualifying draw
    finishes and sixteen slots fill at once — so a draw gets exactly ONE such
    message, ever. Later Q-slot movement (a lucky loser taking a qualifier's
    place) is a replacement and reaches people through draw_changed instead.

    Without this the 20-minute settle window alone decided, and a qualifying
    draw transcribed in two sittings produced two notifications for one event.
    """

    __tablename__ = "qualifiers_added_notifications"

    draw_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("draws.id", ondelete="CASCADE"), primary_key=True
    )
    qualifier_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class StandoutPickNotification(Base):
    """
    Idempotency + audit record: one row per completed match once it has been
    measured against the field, i.e. "how many of this draw's competitors called
    it right".

    match_id is the primary key (not autoincrement) so recording the
    measurement IS the claim — the sweep that finds finished matches runs every
    few minutes and must never re-measure, or a match would notify twice.

    The counts are frozen here rather than recomputed at send time. A draw's
    participant pool grows while picks are open and can grow again through the
    admin pick-for-others path, so "fewer than half the field saw this coming"
    has to mean the field as it stood when the match finished. It also makes the
    row self-explaining months later, when the picks behind it have scrolled out
    of anyone's memory.
    """

    __tablename__ = "standout_pick_notifications"

    match_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    draw_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("draws.id", ondelete="CASCADE"), nullable=False, index=True
    )
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    participant_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # How many competitors actually had a pick on THIS match — a different
    # number from participant_count, which counts everyone entered in the draw
    # whether or not they got as far as this fixture. It exists to gate the
    # notification: "you saw what the field missed" is not a claim worth making
    # when the field that expressed a view was a handful of people. The
    # displayed denominator stays participant_count, matching what
    # match_predictors means by "correct".
    prediction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    # Null until the batch goes out. Set on EVERY measured match, including the
    # ones the field mostly got right — those are recorded so they are never
    # re-measured, and stamped so the pending sweep stays small.
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TournamentCompleteNotification(Base):
    """
    Idempotency + audit record: one row per draw once "final standings" emails
    (and the draw-history results persistence that rides along with them) have
    been sent. Same role as DrawReleaseNotification, backstopping the coarse
    Draw.completion_notified_at column check against overlapping/racing
    callers (notify_tournament_complete can be triggered by the same
    process-restart race as match-start — see _refresh_active_tournaments's
    force_refresh=True call at startup).
    """

    __tablename__ = "tournament_complete_notifications"

    draw_id: Mapped[int] = mapped_column(Integer, ForeignKey("draws.id", ondelete="CASCADE"), primary_key=True)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
