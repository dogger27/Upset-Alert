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
    venue_timezone: Optional[str] = None   # IANA timezone, e.g. "Europe/London"
    day1_start_hour: Optional[int] = None
    day1_start_minute: Optional[int] = None
    closing_time: Optional[datetime] = None


class TournamentOut(BaseModel):
    id: int
    name: str
    year: int
    gender: str
    surface: Optional[str]
    category: Optional[str]
    draw_size: int
    num_rounds: int
    start_date: Optional[date]
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
    status: str
    selections_unlocked: bool = False
    last_scraped_at: Optional[datetime]
    latest_result_at: Optional[datetime] = None
    is_locked: bool

    @property
    def computed_status(self) -> str:
        """Return computed status based on dates."""
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


class DrawEntryOut(BaseModel):
    id: int
    name: str
    nationality: Optional[str]
    seed: Optional[int]
    entry_type: Optional[str]
    bracket_position: int
    ranking: Optional[int] = None
    date_of_birth: Optional[date] = None
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
    scores: Optional[list] = None  # [[p1_s1, p1_s2, ...], [p2_s1, p2_s2, ...]]

    model_config = {"from_attributes": True}


class DrawOut(BaseModel):
    tournament: TournamentOut
    draw_entries: list[DrawEntryOut]
    matches: list[MatchOut]
