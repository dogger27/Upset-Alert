from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.tournament import TournamentOut
from app.schemas.user import UserOut


class LeagueCreate(BaseModel):
    name: str
    scoring_mode: str = "classic"     # classic / atp_wta / upset_bonus / custom
    custom_points: Optional[dict] = None
    is_public: bool = False
    show_real_name: bool = False
    allow_member_invites: bool = False


class LeagueUpdate(BaseModel):
    name: Optional[str] = None
    scoring_mode: Optional[str] = None
    custom_points: Optional[dict] = None
    is_public: Optional[bool] = None
    show_real_name: Optional[bool] = None
    allow_member_invites: Optional[bool] = None


class LeagueMemberOut(UserOut):
    is_admin: bool = False


class LeagueOut(BaseModel):
    id: int
    name: str
    scoring_mode: str
    custom_points: Optional[dict]
    is_public: bool
    show_real_name: bool
    allow_member_invites: bool = False
    invite_code: str
    created_at: datetime
    owner: UserOut
    member_count: int = 0
    members: list[LeagueMemberOut] = []

    model_config = {"from_attributes": True}


class LeaderboardEntry(BaseModel):
    rank: int
    user: UserOut
    total_points: float
    correct_count: int
    # Picking zero upsets is the only thing that disqualifies an entry; an
    # unfinished bracket still competes.
    has_upset_pick: bool = True


class LeaderboardOut(BaseModel):
    league: LeagueOut
    entries: list[LeaderboardEntry]
    total_matches: int = 0
    upset_count: int = 0
    completed_matches_count: int = 0


class LeagueTournamentOut(BaseModel):
    tournament: TournamentOut
    picker_count: int
    # The league's cash pool on this draw. When enabled, only paid members
    # appear in the league's views of the draw, and picker_count counts them.
    cash_pool_enabled: bool = False
    cash_pool_paid_ids: list[int] = []
    # Members with at least one pick in this draw — "competing", whatever the
    # pool says. The pool popup sorts and stars them, so it needs the whole
    # league's answer, not the paid-only one the standings show.
    competing_user_ids: list[int] = []


class CashPoolOut(BaseModel):
    draw_id: int
    enabled: bool = False
    paid_user_ids: list[int] = []


class CashPoolIn(BaseModel):
    enabled: bool
    paid_user_ids: list[int] = []
