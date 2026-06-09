from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
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
    # upcoming / open / active / completed
    status: Mapped[str] = mapped_column(String, default="upcoming")
    last_scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    players: Mapped[list["Player"]] = relationship(
        "Player", back_populates="tournament", cascade="all, delete-orphan"
    )
    matches: Mapped[list["Match"]] = relationship(
        "Match", back_populates="tournament", cascade="all, delete-orphan"
    )

    @property
    def is_locked(self) -> bool:
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
        - open:      DA draw published, closing time not yet reached
        - active:    closing time passed, or scraper detected match results
        - completed: scraper detected final winner, or 14-day safety fallback
        """
        if self.status == "completed":
            return "completed"

        today = date.today()

        # 14-day safety fallback
        if self.start_date and (today - self.start_date).days > 14:
            return "completed"

        # Closing time passed → active
        close = self.closing_time
        if close:
            now = datetime.now(timezone.utc)
            c = close if close.tzinfo else close.replace(tzinfo=timezone.utc)
            if now >= c:
                return "active"

        # DA draw published → open, unless the start date has arrived and the
        # scraper already detected match results (closing_time not yet set)
        if self.draw_released_direct_at:
            if self.status == "active" and self.start_date and today >= self.start_date:
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
        return f"Round of {players_in_round}"


class Player(Base):
    """A player entry in a specific tournament draw."""

    __tablename__ = "players"

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

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="players")


class Match(Base):
    """A single match slot in the bracket."""

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)   # 1 = first round
    match_number: Mapped[int] = mapped_column(Integer, nullable=False)   # 1-indexed within round
    # Player IDs — R1 matches are populated by the scraper; later rounds fill in as results arrive
    player1_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id"), nullable=True)
    player2_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id"), nullable=True)
    winner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id"), nullable=True)
    is_bye: Mapped[bool] = mapped_column(Integer, default=False)
    # [[p1_s1, p1_s2, ...], [p2_s1, p2_s2, ...]] — set scores as strings
    scores_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # pending / completed
    status: Mapped[str] = mapped_column(String, default="pending")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="matches")
    player1: Mapped[Optional["Player"]] = relationship("Player", foreign_keys=[player1_id])
    player2: Mapped[Optional["Player"]] = relationship("Player", foreign_keys=[player2_id])
    winner: Mapped[Optional["Player"]] = relationship("Player", foreign_keys=[winner_id])
