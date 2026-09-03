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
    # Sofascore's MIXED doubles event — a third uniqueTournament beside the
    # gendered pairs the draws carry, so it lives on the tournament: one mixed
    # championship per event, not one per gender. Same contract as the draws'
    # doubles pointers: no bracket, no draw — a pointer used to find scores
    # for schedule rows, nothing more. Resolved by sofascore_doubles.
    sofa_mixed_tournament_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sofa_mixed_season_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # WTA's own event id, which is also the path segment for their order-of-play
    # PDF. Sits on the tournament rather than the draw because one event id
    # covers both draws when the tours share a site — see order_of_play.py.
    wta_live_scoring_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # The ATP's own tournament id — the number in an atptour.com URL, and the
    # path segment of its order-of-play PDF on protennislive. Needed only for
    # events with no WTA counterpart; at a shared-venue combined event the WTA
    # file already covers both draws.
    atp_tournament_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

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
    # Sofascore's uniqueTournament id and the season within it. The tournament id
    # is stable across years (Cincinnati ATP has been 2373 for several), the
    # season id is not — it identifies this edition's draw. Both are resolved
    # once by name and then never re-derived; see services/sofascore.py.
    sofa_tournament_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sofa_season_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # The DOUBLES event of the same tournament and gender. Sofascore keeps it as
    # a separate uniqueTournament — Cincinnati is 2373 (ATP) / 2548 (WTA) for
    # singles and 2381 / 2553 for doubles — so it needs its own id.
    #
    # Stored on the DRAW rather than the tournament because a combined event has
    # two of each and the draw is already the per-gender row. There is still no
    # doubles draw and no doubles bracket: this is a pointer used to find the
    # scores for schedule rows, nothing more.
    sofa_doubles_tournament_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sofa_doubles_season_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # When resolution was last ATTEMPTED for this draw — not when it succeeded.
    # The automatic resolver retries a draw that still has unstamped entries,
    # because entries arrive over days (qualifiers fill in last) and one pass
    # can only ever stamp who was in the field at the time. Without a record of
    # the attempt that retry has no floor: a draw with four names Sofascore
    # simply does not carry would be re-resolved every single pass, forever,
    # spending a request per pass on an answer that is not going to change.
    sofa_resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
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
    # Which locking rule this draw uses — and, once it is over, USED. Stamped
    # from the site-wide default rather than read through to it, so a finished
    # tournament keeps reporting the rules it was actually played under when the
    # default later changes. See services/settings.resolve_draw_lock_mode.
    pick_lock_mode: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    selections_unlocked: Mapped[bool] = mapped_column(Boolean, default=False)
    # Today's order-of-play PDF, or NULL when there isn't a current one. Held
    # per draw rather than per tournament because at a split-venue event the
    # men's and women's schedules are genuinely different documents.
    # oop_date is the day the PDF is FOR, read out of the file itself — the
    # only trustworthy freshness signal, since a finished event serves its last
    # day's PDF forever at HTTP 200. See services/order_of_play.py.
    oop_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    oop_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    oop_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set the first time an order of play covers this draw, and never cleared.
    # oop_url cannot answer "does this tournament publish a schedule yet" — it
    # holds only TODAY's file and goes null overnight and between rounds, so a
    # link keyed to it would blink in and out. This is the durable signal.
    oop_first_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
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
        # UNDER MATCH-BY-MATCH LOCKING THE CALENDAR DECIDES NOTHING. The bracket
        # stays open until every first-round match is complete, however long
        # that takes and whatever the date says — matches freeze individually as
        # they go on court, which is draw_lock_state's business, and it stamps
        # picks_locked_at at the moment the round is genuinely done.
        # computed_status still moves to "active" on the start date, because
        # that is a statement about PLAY and this is a statement about PICKS;
        # under this mode the two are deliberately not the same thing.
        if self.pick_lock_mode == "r1_progressive":
            return self.picks_locked_at is not None
        return self.computed_status in ("active", "completed")

    @property
    def computed_status(self) -> str:
        today = date.today()

        # MATCH-BY-MATCH DRAWS STAY "OPEN" WHILE THEY ARE STILL PICKABLE.
        #
        # Everything below decides "active" from the calendar and from play
        # having begun, which is right when the whole bracket shuts at the first
        # ball. Under this rule it is not: matches freeze one at a time and the
        # rest of the bracket stays editable, so the draw went on reading
        # "Active" while every remaining pick could still be changed — a label
        # contradicting the buttons underneath it.
        #
        # picks_locked_at is the one fact that settles it, and draw_lock_state
        # stamps it the moment every first-round match has STARTED (the
        # owner's rule — see _r1_all_started). Until then the draw is open,
        # whatever the date says, and anyone entering gets the favourite
        # filled in for every match already frozen.
        if (self.pick_lock_mode == "r1_progressive"
                and not self.picks_locked_at
                and self.draw_released_direct_at
                and self.status != "completed"):
            return "open"

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
    # Sofascore's player id, resolved once against this draw's own field and
    # then joined on rather than re-matched. ESPN is matched by name on every
    # poll because it publishes no id; this column is what stops the live-score
    # path from repeating that. NULL means unresolved, never "no such player" —
    # an unresolved entry is reported, not silently skipped.
    sofa_player_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

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
    # none_as_null on both JSON columns below. Without it SQLAlchemy stores a
    # Python None as the JSON TEXT 'null', which is not SQL NULL — so
    # `col.isnot(None)` still matches the row. Production accumulated 1,039 such
    # rows in live_scores_json: harmless there only because espn_monitor also
    # re-checks in Python, but it means every poll selects a thousand rows it has
    # no use for. The same pattern in sofa_live_json below would have been a real
    # fault, re-clearing and re-broadcasting a finished match every 10 seconds.
    live_scores_json: Mapped[Optional[list]] = mapped_column(
        JSON(none_as_null=True), nullable=True)
    served_first: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Sofascore's live snapshot, kept in its OWN column rather than merged into
    # live_scores_json above. Two reasons, and both are about not creating a
    # contradiction on screen:
    #
    #  1. espn_monitor owns live_scores_json outright — it writes it, clears it
    #     when a match leaves the in-progress list, and treats "non-null" as
    #     "this match is live". A second writer on the same column would fight
    #     it every poll.
    #  2. ESPN and Sofascore are sampled at different moments. Taking games from
    #     one and points from the other produces states that never existed: a
    #     game that has already been won still showing 40-30 beside a set score
    #     that has moved on. Each snapshot here is internally consistent because
    #     it came from a single response.
    #
    # Shape: {"sets": [[p1,p2], ...], "point": [p1,p2], "tiebreak": bool,
    #         "serving": 1|2|None, "at": iso8601}
    # Readers prefer this while it is fresh and fall back to live_scores_json,
    # so ESPN remains the source of record and this is strictly additive.
    sofa_live_json: Mapped[Optional[dict]] = mapped_column(
        JSON(none_as_null=True), nullable=True)
    # ── Shadow columns ───────────────────────────────────────────────────────
    # What Sofascore says the RESULT was. Deliberately parallel to winner_id /
    # completed_at / scores_json / started_at above rather than replacing them.
    #
    # Only espn_monitor writes the real columns; eighteen other modules read
    # them — scoring, standings, locking, notifications, H2H, upsets. So the
    # eventual cutover is one writer, not eighteen consumers, and until it
    # happens the safe way to earn confidence is to write a second opinion
    # beside the first and compare them over a real tournament.
    #
    # A wrong winner does not render badly, it scores the league wrong and
    # emails everyone about it — and the notification dedup tables mean a bad
    # send cannot be un-sent. Hence: shadow first, diff, then cut over.
    sofa_winner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("draw_entries.id"), nullable=True)
    # When we first OBSERVED the match finished, not when it actually ended —
    # Sofascore publishes no end timestamp. Later than the truth by up to one
    # poll interval, which is the same limitation espn_monitor already has.
    sofa_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Final per-set games, in the same shape as scores_json ([p1[], p2[]], with
    # the set loser's cell carrying "(n)" for a tiebreak) so the two can be
    # compared cell by cell rather than through a translation layer.
    sofa_scores_json: Mapped[Optional[list]] = mapped_column(
        JSON(none_as_null=True), nullable=True)
    # Sofascore's stated start. Better than started_at, which espn_monitor can
    # only infer as "the first poll that saw it live".
    sofa_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # WHEN PLAY CAME BACK. started_at is the first point of the match and never
    # moves; a match suspended overnight and picked up the next day needs the
    # second time too, or its row on the new day prints yesterday afternoon as
    # its start.
    resumed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # WHEN PLAY STOPPED — the start of the stop resumed_at ends. The two
    # together are what decide whether a resumption is worth naming: see
    # live_state.note_resumption.
    suspended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # First moment ESPN reported this match in progress, and the minutes between
    # that and completion. completed_at alone gives no duration — there was
    # nothing to subtract from it — so the schedule's expected-start chain had
    # to guess every match length from a constant. Measured lengths accumulate
    # from here and can replace those constants once a season exists.
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    draw: Mapped["Draw"] = relationship("Draw", back_populates="matches")
    player1: Mapped[Optional["DrawEntry"]] = relationship("DrawEntry", foreign_keys=[player1_id])
    player2: Mapped[Optional["DrawEntry"]] = relationship("DrawEntry", foreign_keys=[player2_id])
    winner: Mapped[Optional["DrawEntry"]] = relationship("DrawEntry", foreign_keys=[winner_id])


# ---------------------------------------------------------------------------
# Backwards-compat aliases — remove once all call sites are updated
# ---------------------------------------------------------------------------
TournamentCategory = DrawCategory
TournamentCategoryVariant = DrawCategoryVariant
