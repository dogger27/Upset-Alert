from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# How many days before start_date a picks-lock can legitimately happen. One
# venue far enough east of UTC can genuinely start play the UTC evening before;
# nothing legitimately starts earlier. Lives here rather than in espn_monitor so
# the monitor (which stamps picks_locked_at) and computed_status (which trusts
# it) read the same number — they were separate, drifted to 3 vs 1, and 2026
# Canadian Open locked three days early off another tournament's live match.
LOCK_LEAD_DAYS = 1


class DrawCategory(Base):
    """
    Reference table for each draw tier (Grand Slam, ATP 1000, etc.).
    Drives the entry-ranking-week formula and other tier-level defaults.
    """

    __tablename__ = "draw_categories"

    name: Mapped[str] = mapped_column(String, primary_key=True)   # "Grand Slam", "ATP 1000", …
    entry_days_before: Mapped[int] = mapped_column(Integer, nullable=False)       # main-draw entry cutoff: 42 (GS) or 28
    qual_entry_days_before: Mapped[int] = mapped_column(Integer, nullable=False)  # qualifying cutoff: 28 (GS) or 21
    seed_days_before: Mapped[int] = mapped_column(Integer, nullable=False)        # seeding snapshot: 28 (GS) or 14
    default_draw_size: Mapped[int] = mapped_column(Integer, nullable=False)       # kept for backwards compat; see variants
    alt_draw_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # kept for backwards compat; see variants
    sort_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)         # 0=GS, 1=1000, 2=500, 3=250
    scoring_tier: Mapped[Optional[str]] = mapped_column(String, nullable=True)        # "GS" / "1000" / "500" / "250"
    unique_per_slot: Mapped[bool] = mapped_column(Integer, nullable=False, default=False)
    one_per_slot: Mapped[bool] = mapped_column(Integer, nullable=False, default=False)
    default_da_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    default_qual_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wikipedia_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    variants: Mapped[list["DrawCategoryVariant"]] = relationship(
        "DrawCategoryVariant", back_populates="category", lazy="select"
    )


class DrawCategoryVariant(Base):
    """
    A specific draw-size configuration within a category.

    Most categories have a standard variant and one or two exceptions:
      ATP 1000:  96-draw (standard) or 56-draw (Paris, Monte-Carlo)
      ATP 500:   32-draw (standard) or 48-draw (Washington)
      ATP 250:   28-draw (standard), 32-draw, or 48-draw (Winston-Salem)
      WTA 1000:  96-draw (standard) or 56-draw (Qatar, Dubai, Wuhan)
      WTA 500:   28-draw (standard), 30-draw (Adelaide), 32-draw, or 48-draw
      WTA 250:   32-draw (uniform)
      Grand Slam: 128-draw, one named variant per Slam for its logo
    """

    __tablename__ = "draw_category_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_name: Mapped[str] = mapped_column(String, ForeignKey("draw_categories.name"), nullable=False)
    draw_size: Mapped[int] = mapped_column(Integer, nullable=False)
    num_byes: Mapped[int] = mapped_column(Integer, nullable=False)   # 2^num_rounds − draw_size
    num_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    logo_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_default: Mapped[bool] = mapped_column(Integer, nullable=False, default=False)
    label: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    category: Mapped["DrawCategory"] = relationship("DrawCategory", back_populates="variants")


class Tournament(Base):
    """
    A real-world tennis event edition, e.g. 'Eastbourne International 2026'.
    Groups all draws (M singles, F singles) for the same event and year.
    """

    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    city: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    surface: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    draws: Mapped[list["Draw"]] = relationship("Draw", back_populates="tournament")


class Draw(Base):
    """A single gender's draw within a tournament, e.g. 2026 Eastbourne ATP250 Men's Singles."""

    __tablename__ = "draws"
    __table_args__ = (UniqueConstraint("wiki_page_title", name="uq_draw_wiki"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tournaments.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)          # "French Open"
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    gender: Mapped[str] = mapped_column(String(1), nullable=False)     # "M" or "F"
    surface: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "Grand Slam", "ATP 1000", etc.
    draw_size: Mapped[int] = mapped_column(Integer, nullable=False)
    num_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    week: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    draw_release_direct: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    draw_release_qualifiers: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    draw_released_direct_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    draw_released_qualifiers_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Full timestamp of when draw_released_direct_at was FIRST stamped (cleared if the
    # stamp is later reverted as premature). Used to require the release to stay stable
    # for a cooldown before emailing — a scrape-to-scrape flicker never fires an email.
    draw_release_detected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set once the "draw released" email has actually been sent for this draw. Centralizes
    # idempotency across every code path that can trigger a scrape (scheduler, season-page
    # edits, EventStreams, manual admin refresh) so the email fires exactly once.
    draw_release_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    da_days_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    qual_days_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # When the bracket was FIRST observed on Wikipedia, evidenced by named
    # UNSEEDED players holding bracket slots (see tournaments.py). This is a
    # different measurement from da_days_before, which records when the page
    # reached "substantially complete" (50% of non-Q/LL slots) and therefore
    # trails actual publication by however long an editor takes to finish
    # transcribing the draw. Predictions learn from THIS field — measuring our
    # own completeness threshold and then feeding it back into the estimate is
    # what pinned ATP/WTA 250 release dates at start-minus-one-day.
    bracket_first_seen_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    bracket_first_seen_days_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    wiki_page_title: Mapped[str] = mapped_column(String, nullable=False)
    wiki_page_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, unique=True)
    venue_timezone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # The venue's assumed day-1 start, from tournament_schedule's curated lookup
    # table. An assumption until first_match_* below observes the real thing.
    day1_start_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    day1_start_minute: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # When day 1's first MAIN-DRAW match was scheduled to start, taken from
    # ESPN's published order of play (espn_monitor._refine_closing_time, which
    # is also where the placeholder/qualifying/wrong-week refusals live). UTC.
    #
    # Recorded so the curated table stops being the only source of a start hour.
    # The table holds one hand-researched guess per venue; this is what the
    # tournament actually did, and a season of it lets next year's edition — and
    # eventually a category — be estimated from evidence instead.
    first_match_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # The same instant as VENUE-LOCAL time of day, split into its parts. Stored
    # rather than derived because that is the form the estimate needs ("this
    # event starts at 11:00 local"), and deriving it later would need the
    # venue's timezone as it was then — the one field most likely to have been
    # corrected in between.
    first_match_local_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    first_match_local_minute: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    closing_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    picks_locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_ranking_week: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    seed_ranking_week: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    variant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("draw_category_variants.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, default="upcoming")
    selections_unlocked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tournament: Mapped[Optional["Tournament"]] = relationship("Tournament", back_populates="draws")
    variant: Mapped[Optional["DrawCategoryVariant"]] = relationship(
        "DrawCategoryVariant", lazy="joined", foreign_keys=[variant_id]
    )
    draw_entries: Mapped[list["DrawEntry"]] = relationship(
        "DrawEntry", back_populates="draw", cascade="all, delete-orphan"
    )
    matches: Mapped[list["Match"]] = relationship(
        "Match", back_populates="draw", cascade="all, delete-orphan"
    )

    @property
    def logo_path(self) -> Optional[str]:
        return self.variant.logo_path if self.variant else None

    @property
    def num_byes(self) -> int:
        return self.variant.num_byes if self.variant else 0

    @property
    def scoring_tier(self) -> str:
        cat = (self.category or "").upper()
        if "SLAM" in cat or "GRAND" in cat:
            return "GS"
        if "1000" in cat:
            return "1000"
        if "500" in cat:
            return "500"
        return "250"

    @property
    def is_locked(self) -> bool:
        """Picks close at the exact moment the draw stops being Open.

        Delegates to computed_status instead of comparing the clock to
        closing_time. closing_time is only a PREDICTION of day 1's first
        match (venue timezone + the schedule lookup table), and a wrong
        prediction closes picks while the courts are still empty — 2026 Los
        Cabos had no lookup entry, fell back to the Mexico default of 11:00
        America/Mexico_City, and locked eight hours before ESPN's first
        scheduled main-draw match.

        computed_status only reaches "active" on evidence: ESPN watching a
        main-draw match go live (picks_locked_at), the scraper recording a
        real result, or the day rolling past start_date. closing_time still
        feeds its day-after backstop, but can no longer lock anything early
        on the start date itself.
        """
        if self.selections_unlocked:
            return False
        return self.computed_status in ("active", "completed")

    @property
    def computed_status(self) -> str:
        today = date.today()

        # A draw that hasn't started yet can never be "active" or "completed",
        # no matter what got stamped on it (e.g. stale/garbled scraped results
        # from a bad start_date). Guard this before anything else below — but
        # it CAN be "open" once the draw has actually been released (a draw is
        # normally released days before the tournament starts; that's the
        # entire point of the "Open" bucket). Without this, any tournament
        # whose start_date is still in the future would be stuck showing
        # "upcoming"/"draw not yet released" even after the real draw is out,
        # right up until the exact calendar day it starts.
        if self.start_date and today < self.start_date:
            # ESPN already watched a main-draw match go live, which for a venue
            # far enough east of UTC can happen the UTC-evening before
            # start_date. Bounded to 1 day = espn_monitor._LOCK_LEAD_DAYS, which
            # is also the widest window in which the monitor will stamp
            # picks_locked_at at all — the two MUST stay equal, or a lock the
            # monitor considers legitimate reads as "upcoming" here (or worse, a
            # lock it should never have made turns a draw active days early, as
            # 2026 Canadian Open did off a Washington match).
            if self.picks_locked_at and (self.start_date - today).days <= LOCK_LEAD_DAYS:
                return "active"
            if self.draw_released_direct_at and (self.start_date - today).days <= 30:
                return "open"
            return "upcoming"

        if self.status == "completed":
            if self.end_date and today <= self.end_date:
                return "active"
            return "completed"
        now = datetime.now(timezone.utc)

        if self.start_date and (today - self.start_date).days > 14:
            return "completed"

        # picks_locked_at is stamped ONLY by espn_monitor._on_match_start, i.e.
        # ESPN reported a main-draw (never qualifying) match of this draw as in
        # progress. That is a direct observation that play has begun, unlike
        # closing_time, which is a *predicted* day-1 start and therefore can't
        # be trusted on the start date itself (see the close block below).
        # Without this, a draw whose first match is under way still reads "open"
        # all day, because the scraper only stamps status="active" once
        # Wikipedia publishes a completed non-bye result.
        if self.picks_locked_at:
            return "active"

        close = self.closing_time
        c = close.replace(tzinfo=timezone.utc) if (close and not close.tzinfo) else close

        if c and now >= c and self.start_date and today > self.start_date:
            return "active"

        if self.draw_released_direct_at:
            if self.start_date and (self.start_date - today).days > 30:
                return "upcoming"

            if self.status == "active" and self.start_date and today >= self.start_date:
                if today > self.start_date:
                    return "active"
                if c is not None and now >= c:
                    return "active"

            if self.start_date and today > self.start_date:
                return "active"

            return "open"

        return "upcoming"

    def round_name(self, round_number: int) -> str:
        total = self.num_rounds
        rounds_from_end = total - round_number
        names = {0: "Final", 1: "Semifinals", 2: "Quarterfinals", 3: "Round of 16"}
        if rounds_from_end in names:
            return names[rounds_from_end]
        players_in_round = self.draw_size // (2 ** (round_number - 1))
        p = 1
        while p < players_in_round:
            p <<= 1
        return f"Round of {p}"


class DrawEntry(Base):
    """A player's entry in a specific draw."""

    __tablename__ = "draw_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draw_id: Mapped[int] = mapped_column(ForeignKey("draws.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    nationality: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entry_type: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    bracket_position: Mapped[int] = mapped_column(Integer, nullable=False)
    ranking: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    te_player_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    te_slug: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    draw: Mapped["Draw"] = relationship("Draw", back_populates="draw_entries")


class Match(Base):
    """A single match slot in the bracket."""

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draw_id: Mapped[int] = mapped_column(ForeignKey("draws.id"), nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    match_number: Mapped[int] = mapped_column(Integer, nullable=False)
    player1_id: Mapped[Optional[int]] = mapped_column(ForeignKey("draw_entries.id"), nullable=True)
    player2_id: Mapped[Optional[int]] = mapped_column(ForeignKey("draw_entries.id"), nullable=True)
    winner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("draw_entries.id"), nullable=True)
    is_bye: Mapped[bool] = mapped_column(Integer, default=False)
    scores_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    live_scores_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    served_first: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    draw: Mapped["Draw"] = relationship("Draw", back_populates="matches")
    player1: Mapped[Optional["DrawEntry"]] = relationship("DrawEntry", foreign_keys=[player1_id])
    player2: Mapped[Optional["DrawEntry"]] = relationship("DrawEntry", foreign_keys=[player2_id])
    winner: Mapped[Optional["DrawEntry"]] = relationship("DrawEntry", foreign_keys=[winner_id])


# ---------------------------------------------------------------------------
# Backwards-compat aliases — remove once all call sites are updated
# ---------------------------------------------------------------------------
TournamentCategory = DrawCategory
TournamentCategoryVariant = DrawCategoryVariant
