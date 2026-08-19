"""
Order-of-play schedule.

Note what is NOT here: `printed_score` and `printed_status`. The sheet's own
score is a snapshot from whenever that revision was published and can be hours
stale, so it is never shown to a user — ESPN is the only score anyone sees.
Those columns exist purely to anchor expected-start estimates on courts ESPN
does not cover. Leaving them out of the response model, rather than filtering
them at render time, is what keeps that true when someone later adds a field.
"""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_optional_user
from app.database import get_db
from app.models.prediction import UserPrediction
from app.models.schedule import ScheduleEntry
from app.models.tournament import Draw, Match, Tournament

router = APIRouter(prefix="/schedule", tags=["schedule"])


class SchedulePlayerOut(BaseModel):
    side: str
    position: int
    name: str
    draw_entry_id: Optional[int] = None


class ScheduleEntryOut(BaseModel):
    id: int
    tournament_id: int
    tournament_name: Optional[str] = None
    draw_id: Optional[int] = None
    match_id: Optional[int] = None
    play_date: date
    tour: Optional[str] = None
    stage: str
    discipline: str
    round_label: Optional[str] = None
    court: Optional[str] = None
    court_order: int
    # As printed — the court view renders this verbatim rather than a time.
    start_type: str
    start_time_local: Optional[str] = None
    # Computed chain — the sort key for the time view. `expected_source` tells
    # the client whether to render it firmly ("3:00 PM") or hedged ("~4:15 PM").
    expected_start_at: Optional[datetime] = None
    expected_source: Optional[str] = None
    is_tbd: bool = False
    tbd_side: Optional[str] = None
    status: str = "scheduled"
    players: list[SchedulePlayerOut] = []
    # ESPN only. Absent for doubles and qualifying, which it does not cover.
    live_scores: Optional[list] = None
    scores: Optional[list] = None
    # Whether this slot involves one of the viewer's picks.
    is_my_pick: bool = False


class ScheduleDayOut(BaseModel):
    play_date: date
    entries: list[ScheduleEntryOut]
    courts: list[str]
    tournaments: list[dict]


@router.get("/day", response_model=ScheduleDayOut)
async def schedule_day(
    play_date: Optional[date] = Query(None),
    tournament_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_optional_user),
):
    """Everything scheduled on one day, optionally narrowed to one tournament.

    Returns every discipline and stage; the client filters. Doubles default off
    and singles qualifying always on, but that is a view preference, not
    something to bake into the query — a user toggling it should not wait on a
    round trip.
    """
    day = play_date or date.today()

    q = select(ScheduleEntry).where(ScheduleEntry.play_date == day)
    if tournament_id:
        q = q.where(ScheduleEntry.tournament_id == tournament_id)
    entries = (await db.execute(
        q.order_by(ScheduleEntry.expected_start_at, ScheduleEntry.court,
                   ScheduleEntry.court_order))).scalars().all()

    if not entries:
        return ScheduleDayOut(play_date=day, entries=[], courts=[], tournaments=[])

    t_ids = {e.tournament_id for e in entries}
    t_rows = (await db.execute(
        select(Tournament.id, Tournament.name).where(Tournament.id.in_(t_ids)))).all()
    t_names = {r[0]: r[1] for r in t_rows}

    match_ids = {e.match_id for e in entries if e.match_id}
    matches = {}
    if match_ids:
        rows = (await db.execute(
            select(Match).where(Match.id.in_(match_ids)))).scalars().all()
        matches = {m.id: m for m in rows}

    # Which draw_entries the viewer picked, so the page can highlight them.
    picked: set[int] = set()
    if user is not None:
        draw_ids = {e.draw_id for e in entries if e.draw_id}
        if draw_ids:
            preds = (await db.execute(
                select(UserPrediction.predicted_winner_id).where(
                    UserPrediction.user_id == user.id,
                    UserPrediction.draw_id.in_(draw_ids)))).all()
            picked = {r[0] for r in preds if r[0]}

    out: list[ScheduleEntryOut] = []
    courts: list[str] = []
    for e in entries:
        if e.court and e.court not in courts:
            courts.append(e.court)
        m = matches.get(e.match_id) if e.match_id else None
        players = [
            SchedulePlayerOut(side=p.side, position=p.position,
                              name=p.raw_name, draw_entry_id=p.draw_entry_id)
            for p in sorted(e.players, key=lambda x: (x.side, x.position))
        ]
        out.append(ScheduleEntryOut(
            id=e.id, tournament_id=e.tournament_id,
            tournament_name=t_names.get(e.tournament_id),
            draw_id=e.draw_id, match_id=e.match_id, play_date=e.play_date,
            tour=e.tour, stage=e.stage, discipline=e.discipline,
            round_label=e.round_label, court=e.court, court_order=e.court_order,
            start_type=e.start_type, start_time_local=e.start_time_local,
            expected_start_at=e.expected_start_at, expected_source=e.expected_source,
            is_tbd=e.is_tbd, tbd_side=e.tbd_side, status=e.status, players=players,
            live_scores=(m.live_scores_json if m else None),
            scores=(m.scores_json if m else None),
            is_my_pick=any(p.draw_entry_id in picked for p in e.players if p.draw_entry_id),
        ))

    # The official PDF stays one tap away — the page replaces it as the primary
    # destination, it does not hide it.
    pdf_rows = (await db.execute(
        select(Draw.tournament_id, Draw.oop_url).where(
            Draw.tournament_id.in_(t_ids), Draw.oop_url.isnot(None)))).all()
    pdfs = {r[0]: r[1] for r in pdf_rows}

    return ScheduleDayOut(
        play_date=day, entries=out, courts=courts,
        tournaments=[{"id": i, "name": t_names.get(i), "oop_url": pdfs.get(i)}
                     for i in sorted(t_ids)],
    )


@router.get("/dates")
async def schedule_dates(
    tournament_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Days that actually have a schedule — drives the date stepper so it can
    skip straight to the next real day instead of walking through blanks."""
    q = select(ScheduleEntry.play_date).distinct()
    if tournament_id:
        q = q.where(ScheduleEntry.tournament_id == tournament_id)
    rows = (await db.execute(q.order_by(ScheduleEntry.play_date))).all()
    return {"dates": [r[0].isoformat() for r in rows]}
