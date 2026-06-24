from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Tournament(Base):
    """A single draw: e.g. 2025 French Open Men's Singles."""

    __tablename__ = "tournaments"
    __table_args__ = (UniqueConstraint("wiki_page_title", name="uq_tournament_wiki"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)          # "French Open"
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    gender: Mapped[str] = mapped_column(String(1), nullable=False)     # "M" or "F"
    surface: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "Grand Slam", "ATP 1000", etc.
    draw_size: Mapped[int] = mapped_column(Integer, nullable=False)    # 32, 64, or 128
    num_rounds: Mapped[int] = mapped_column(Integer, nullable=False)   # 5, 6, or 7
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    draw_release_direct: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # Expected Direct Acceptance date
    draw_release_qualifiers: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # Expected Qualifiers Added date
    draw_released_direct_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # Actual Direct Acceptance release date
    draw_released_qualifiers_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # Actual Qualifiers Added date
    da_days_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)    # start_date - draw_released_direct_at (days)
    qual_days_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # start_date - draw_released_qualifiers_at (days)
    city: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    wiki_page_title: Mapped[str] = mapped_column(String, nullable=False)
    wiki_page_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, unique=True)
    # Venue timezone (IANA string, e.g. "Europe/London") and local start time of
    # the first main-draw match on Day 1.  Used to auto-compute closing_time.
    venue_timezone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    day1_start_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    day1_start_minute: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # When the draw closes for predictions (= first main-draw match start time).
    # Populated once the exact schedule is known; NULL means predictions are not yet locked.
    closing_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set by the ESPN live monitor the moment a main-draw match is confirmed in progress.
    # Acts as an idempotency guard — once set, the monitor never fires again for this tournament.
    picks_locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # upcoming / open / active / completed
    status: Mapped[str] = mapped_column(String, default="upcoming")
    selections_unlocked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    draw_entries: Mapped[list["DrawEntry"]] = relationship(
        "DrawEntry", back_populates="tournament", cascade="all, delete-orphan"
    )
    matches: Mapped[list["Match"]] = relationship(
        "Match", back_populates="tournament", cascade="all, delete-orphan"
    )

    @property
    def is_locked(self) -> bool:
        if self.selections_unlocked:
            return False
        close = self.closing_time
        if close is None:
            return False
        now = datetime.now(timezone.utc)
        c = close if close.tzinfo else close.replace(tzinfo=timezone.utc)
        return now >= c

    @property
    def computed_status(self) -> str:
        """
        Status progression: upcoming → open → active → completed

        - upcoming:  no draw data yet
        - open:      draw published, closing time not yet reached
        - active:    matches underway (scraper confirmed) or safely past start date
        - completed: scraper detected final winner, or 14-day safety fallback
        """
        if self.status == "completed":
            if self.end_date and date.today() <= self.end_date:
                return "active"
            return "completed"

        today = date.today()
        now = datetime.now(timezone.utc)

        # 14-day safety fallback
        if self.start_date and (today - self.start_date).days > 14:
            return "completed"

        close = self.closing_time
        c = close.replace(tzinfo=timezone.utc) if (close and not close.tzinfo) else close

        # Closing time passed AND we are past the start date → active.
        # Do NOT fire this on the start date itself: wait for the scraper to
        # confirm results, so picks-locked-but-no-matches-yet doesn't show "Active".
        if c and now >= c and self.start_date and today > self.start_date:
            return "active"

        if self.draw_released_direct_at:
            if self.start_date and (self.start_date - today).days > 30:
                return "upcoming"

            if self.status == "active" and self.start_date and today >= self.start_date:
                if today > self.start_date:
                    # Past start date: always trust the scraper
                    return "active"
                if c is not None and now >= c:
                    # On start date: trust scraper only once picks are locked
                    return "active"

            # Fallback: draw released and we're past the start date
            if self.start_date and today > self.start_date:
                return "active"

            return "open"

        return "upcoming"

    def round_name(self, round_number: int) -> str:
        """Human-readable round name given the 1-indexed round number."""
        total = self.num_rounds
        rounds_from_end = total - round_number  # 0=Final, 1=SF, 2=QF, ...
        names = {0: "Final", 1: "Semifinals", 2: "Quarterfinals", 3: "Round of 16"}
        if rounds_from_end in names:
            return names[rounds_from_end]
        players_in_round = self.draw_size // (2 ** (round_number - 1))
        # Round up to the nearest power of 2 (e.g. 28 → 32)
        p = 1
        while p < players_in_round:
            p <<= 1
        return f"Round of {p}"


class DrawEntry(Base):
    """A player's entry in a specific tournament draw."""

    __tablename__ = "draw_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    nationality: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # WC / Q / LL / PR / None
    entry_type: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    # 1-indexed position in the full draw (1–128 for a 128-draw)
    bracket_position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Official ATP/WTA ranking at time of draw
    ranking: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Date of birth (populated from TE player pages when available)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Foreign key into te_players — set once on first resolution, never changes
    te_player_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="draw_entries")


class Match(Base):
    """A single match slot in the bracket."""

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)   # 1 = first round
    match_number: Mapped[int] = mapped_column(Integer, nullable=False)   # 1-indexed within round
    # Player IDs — R1 matches are populated by the scraper; later rounds fill in as results arrive
    player1_id: Mapped[Optional[int]] = mapped_column(ForeignKey("draw_entries.id"), nullable=True)
    player2_id: Mapped[Optional[int]] = mapped_column(ForeignKey("draw_entries.id"), nullable=True)
    winner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("draw_entries.id"), nullable=True)
    is_bye: Mapped[bool] = mapped_column(Integer, default=False)
    # [[p1_s1, p1_s2, ...], [p2_s1, p2_s2, ...]] — set scores as strings
    scores_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Live set/game scores from ESPN while match is in progress; cleared on completion.
    # Non-null ↔ match is currently in progress.
    live_scores_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 1 = player1 served first, 2 = player2; set once from ESPN possession + game parity
    served_first: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # pending / completed
    status: Mapped[str] = mapped_column(String, default="pending")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="matches")
    player1: Mapped[Optional["DrawEntry"]] = relationship("DrawEntry", foreign_keys=[player1_id])
    player2: Mapped[Optional["DrawEntry"]] = relationship("DrawEntry", foreign_keys=[player2_id])
    winner: Mapped[Optional["DrawEntry"]] = relationship("DrawEntry", foreign_keys=[winner_id])
