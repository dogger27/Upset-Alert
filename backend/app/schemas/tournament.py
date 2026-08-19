from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class TournamentCreate(BaseModel):
    name: str
    year: int
    gender: str          # "M" or "F"
    surface: Optional[str] = None
    wiki_page_title: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    venue_timezone: Optional[str] = None
    day1_start_hour: Optional[int] = None
    day1_start_minute: Optional[int] = None
    closing_time: Optional[datetime] = None


class TournamentOut(BaseModel):
    """Serialises a Draw (individual gender draw). Named TournamentOut for API backwards-compat."""
    id: int
    tournament_id: Optional[int] = None
    name: str
    year: int
    gender: str
    surface: Optional[str]
    category: Optional[str]
    draw_size: int
    num_rounds: int
    start_date: Optional[date]
    week: Optional[int] = None
    end_date: Optional[date]
    draw_release_direct: Optional[date]
    draw_release_qualifiers: Optional[date]
    draw_released_direct_at: Optional[date]
    draw_released_qualifiers_at: Optional[date]
    city: Optional[str]
    country: Optional[str]
    wiki_page_title: str
    wiki_page_id: Optional[int]
    venue_timezone: Optional[str]
    day1_start_hour: Optional[int]
    day1_start_minute: Optional[int]
    closing_time: Optional[datetime]
    entry_ranking_week: Optional[date] = None
    seed_ranking_week: Optional[date] = None
    variant_id: Optional[int] = None
    logo_path: Optional[str] = None
    num_byes: int = 0
    scoring_tier: str = "250"
    status: str
    # Which locking rule this draw uses / used — see models/tournament.py.
    pick_lock_mode: Optional[str] = None
    selections_unlocked: bool = False
    # Today's order of play, or None when there is no current one. The server
    # decides currency (see order_of_play.py) precisely so the client never has
    # to reason about it — a non-null url is always today's.
    oop_url: Optional[str] = None
    oop_date: Optional[date] = None
    # True once an order of play has EVER been published for this draw. Distinct
    # from oop_url, which is only today's and goes null between days.
    oop_first_seen_at: Optional[datetime] = None
    last_scraped_at: Optional[datetime]
    latest_result_at: Optional[datetime] = None
    is_locked: bool

    @property
    def computed_status(self) -> str:
        from datetime import date
        now = date.today()
        if self.end_date and now > self.end_date:
            return "completed"
        if self.start_date and now < self.start_date:
            return "upcoming"
        if self.start_date and self.end_date and self.start_date <= now <= self.end_date:
            return "active"
        return self.status

    model_config = {"from_attributes": True}


class TournamentEventOut(BaseModel):
    """Serialises a Tournament (the real-world event grouping M+F draws)."""
    id: int
    name: str
    year: int
    city: Optional[str]
    country: Optional[str]
    surface: Optional[str]

    model_config = {"from_attributes": True}


class DrawEntryOut(BaseModel):
    id: int
    name: str
    nationality: Optional[str]
    seed: Optional[int]
    entry_type: Optional[str]
    bracket_position: int
    ranking: Optional[int] = None
    date_of_birth: Optional[date] = None
    elo_rank: Optional[int] = None
    te_slug: Optional[str] = None

    model_config = {"from_attributes": True}


class MatchOut(BaseModel):
    id: int
    round_number: int
    match_number: int
    player1: Optional[DrawEntryOut]
    player2: Optional[DrawEntryOut]
    winner: Optional[DrawEntryOut]
    is_bye: bool
    status: str
    round_name: Optional[str] = None
    scores: Optional[list] = None
    live_scores: Optional[list] = None
    # Under progressive locking this match is under way or over, so its pick can
    # no longer be changed even though the bracket as a whole is still open.
    locked: bool = False
    # When this match is expected on court, from the order-of-play chain. Only
    # present once a schedule naming it has been published, so most of a bracket
    # carries nothing — a match three rounds out has no court and no time.
    expected_start_at: Optional[datetime] = None
    expected_source: Optional[str] = None
    court: Optional[str] = None

    model_config = {"from_attributes": True}


class DrawOut(BaseModel):
    tournament: TournamentOut
    draw_entries: list[DrawEntryOut]
    matches: list[MatchOut]
    # How this draw locks, and whether it is shut. Sent so the client greys out
    # exactly what the server would refuse, rather than deriving it a second
    # time from status and dates and drifting.
    lock_mode: str = "draw_start"
    draw_locked: bool = False
    lock_reason: str = ""
    predictions_hidden: bool = True
