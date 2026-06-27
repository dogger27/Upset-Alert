from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.database import get_db
from app.models.tournament import Draw
from app.models.user import User
from app.routers.tournaments import _do_scrape
from app.services.discovery import discover_tournaments

router = APIRouter(prefix="/discover", tags=["discovery"])


class DiscoveredOut(BaseModel):
    name: str
    year: int
    gender: str
    surface: str
    category: str
    draw_size: int
    wiki_page_title: str
    start_date: Optional[str]
    end_date: Optional[str]
    already_added: bool


@router.get("/{year}", response_model=list[DiscoveredOut])
async def get_discovered(
    year: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    discovered = await discover_tournaments(year)

    # Check which are already in DB
    existing = await db.execute(
        select(Draw.wiki_page_title).where(Draw.year == year)
    )
    existing_titles = {r[0] for r in existing}

    return [
        DiscoveredOut(
            name=t.name,
            year=t.year,
            gender=t.gender,
            surface=t.surface,
            category=t.category,
            draw_size=t.draw_size,
            wiki_page_title=t.wiki_page_title,
            start_date=t.start_date.isoformat() if t.start_date else None,
            end_date=t.end_date.isoformat() if t.end_date else None,
            already_added=t.wiki_page_title in existing_titles,
        )
        for t in discovered
    ]


class AddTournamentRequest(BaseModel):
    wiki_page_title: str
    name: str
    year: int
    gender: str
    surface: Optional[str] = None
    start_date: Optional[str] = None


@router.post("/add", status_code=201)
async def add_discovered(
    body: AddTournamentRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from datetime import date

    # Check not already added
    existing = await db.execute(
        select(Draw).where(Draw.wiki_page_title == body.wiki_page_title)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Tournament already added")

    start = date.fromisoformat(body.start_date) if body.start_date else None

    t = Draw(
        name=" ".join(body.name.split()),
        year=body.year,
        gender=body.gender,
        surface=body.surface,
        wiki_page_title=body.wiki_page_title,
        start_date=start,
        draw_size=0,
        num_rounds=0,
    )
    db.add(t)
    await db.flush()
    await _do_scrape(t, db)
    await db.commit()
    return {"id": t.id, "name": t.name}
