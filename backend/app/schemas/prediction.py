from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PredictionSet(BaseModel):
    """Submitted as a dict: {match_id: predicted_winner_player_id or null}"""
    picks: dict[int, Optional[int]]  # match_id -> player_id (None = no pick)


class PredictionOut(BaseModel):
    match_id: int
    predicted_winner_id: Optional[int]
    submitted_at: datetime

    model_config = {"from_attributes": True}
