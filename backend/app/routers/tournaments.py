from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.database import get_db
from app.models.prediction import UserPrediction
from app.models.rankings import TePlayer
from app.models.tournament import DrawEntry, Match, Tournament
from app.models.user import User
from app.schemas.league import LeaderboardEntry
from app.schemas.tournament import DrawEntryOut, DrawOut, MatchOut, TournamentCreate, TournamentOut
from app.schemas.user import UserPublicOut
from app.services.rankings import assign_rankings
from app.services.scraper import scrape_tournament
from app.services.scoring import UserScore, rank_users

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


@router.get("", response_model=list[TournamentOut])
async def list_tournaments(db: AsyncSession = Depends(get_db)):
    lat_subq = (
        select(Match.tournament_id, func.max(Match.completed_at).label("lat"))
        .group_by(Match.tournament_id)
        .subquery()
    )
    result = await db.execute(
        select(Tournament, lat_subq.c.lat)
        .outerjoin(lat_subq, Tournament.id == lat_subq.c.tournament_id)
        .order_by(Tournament.year.desc(), Tournament.name)
    )
    rows = result.all()
    tournaments = []
    for t, lat in rows:
        t.status = t.computed_status
        t.latest_result_at = lat
        tournaments.append(t)
    return tournaments


@router.post("", response_model=TournamentOut, status_code=201)
async def create_tournament(
    body: TournamentCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    t = Tournament(
        name=" ".join(body.name.split()),  # collapse any accidental extra spaces
        year=body.year,
        gender=body.gender,
        surface=body.surface,
        wiki_page_title=body.wiki_page_title,
        start_date=body.start_date,
        end_date=body.end_date,
        venue_timezone=body.venue_timezone,
        day1_start_hour=body.day1_start_hour,
        day1_start_minute=body.day1_start_minute,
        closing_time=body.closing_time,
        draw_size=0,
        num_rounds=0,
    )
    db.add(t)
    await db.flush()  # get ID before scraping
    await _do_scrape(t, db)
    await db.commit()
    await db.refresh(t)
    return t


@router.post("/refresh-completed", response_model=dict)
async def refresh_all_completed(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Re-scrape every in-progress tournament (skips fully completed ones).

    Covers:
    - Tournaments that have already started (start_date <= today)
    - Upcoming tournaments whose expected draw date has passed but draw is not yet confirmed
    """
    import logging
    from datetime import date, timedelta
    from sqlalchemy import or_, and_
    logger = logging.getLogger(__name__)
    today = date.today()
    result = await db.execute(
        select(Tournament).where(
            and_(
                Tournament.status != "completed",
                or_(
                    # Already started
                    and_(Tournament.start_date != None, Tournament.start_date <= today),
                    # DA draw date has passed but not yet confirmed
                    and_(
                        Tournament.draw_release_direct != None,
                        Tournament.draw_release_direct <= today,
                        Tournament.draw_released_direct_at == None,
                    ),
                    # Qualifier date has passed but not yet confirmed
                    and_(
                        Tournament.draw_release_qualifiers != None,
                        Tournament.draw_release_qualifiers <= today,
                        Tournament.draw_released_qualifiers_at == None,
                    ),
                )
            )
        )
    )
    # Capture id/name/title before any rollback can expire ORM objects
    tournament_info = [
        (t.id, t.name, t.wiki_page_title)
        for t in result.scalars().all()
    ]
    ok, failed = 0, []
    for t_id, t_name, t_title in tournament_info:
        try:
            # Re-fetch fresh each time so a previous rollback doesn't leave a stale object
            t = await db.get(Tournament, t_id)
            if t is None or t.status == "completed":
                continue
            await _do_scrape(t, db, force_refresh=True)
            await db.commit()
            ok += 1
        except Exception as exc:
            logger.error("Failed to re-scrape %s: %s", t_title, exc)
            await db.rollback()
            failed.append(t_name)
    return {"refreshed": ok, "failed": failed}


@router.post("/backfill-rankings", response_model=dict)
async def backfill_rankings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Re-resolve te_player_id and refresh rankings for every tournament."""
    import logging
    from datetime import date
    logger = logging.getLogger(__name__)

    tournaments_res = await db.execute(select(Tournament))
    tournaments = tournaments_res.scalars().all()

    updated_total = 0
    failed = []

    for t in tournaments:
        try:
            ref_date = t.start_date or date.today()
            players_res = await db.execute(select(DrawEntry).where(DrawEntry.tournament_id == t.id))
            players = players_res.scalars().all()

            before = [p.ranking for p in players]
            await assign_rankings(players, t.gender, ref_date, db)
            after = [p.ranking for p in players]

            updated = sum(1 for b, a in zip(before, after) if b != a)
            await db.commit()
            updated_total += updated
            logger.info("%s: updated %d/%d player rankings", t.name, updated, len(players))
        except Exception as exc:
            logger.error("Failed rankings backfill for %s: %s", t.name, exc)
            await db.rollback()
            failed.append(t.name)

    return {"updated_players": updated_total, "failed": failed}


@router.post("/backfill-dob", response_model=dict)
async def backfill_dob(
    _: User = Depends(get_current_user),
):
    """Admin: fetch date-of-birth from TE for all te_players missing it."""
    from app.services.rankings import backfill_all_dob
    import asyncio
    asyncio.create_task(backfill_all_dob())
    return {"status": "started"}


@router.post("/sync-tournaments", response_model=dict)
async def sync_tournaments(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Run a full discovery + title-correction + scrape cycle for the current year.
    Fixes wrong wiki page titles (e.g. '– Men's singles' stored when Wikipedia
    uses '– Singles') then immediately scrapes any tournament still missing a
    confirmed page ID.
    """
    import logging
    from datetime import datetime, timezone
    logger = logging.getLogger(__name__)
    current_year = datetime.now(timezone.utc).year
    try:
        from app.services.tournament_sync import sync_season
        summary = await sync_season(db, current_year, scrape_new=True)
        return {"status": "ok", **summary}
    except Exception as exc:
        logger.error("sync_tournaments failed: %s", exc)
        await db.rollback()
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/apply-schedules", response_model=dict)
async def apply_all_schedules(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Back-fill venue_timezone, day1_start_hour, day1_start_minute, and closing_time
    for all tournaments that are missing them.  Safe to re-run; won't overwrite
    manually-set values.
    """
    import logging
    from app.services.tournament_schedule import apply_schedule, apply_closing_time
    logger = logging.getLogger(__name__)

    result = await db.execute(select(Tournament))
    tournaments = result.scalars().all()

    schedule_set = closing_set = 0
    for t in tournaments:
        if apply_schedule(t):
            schedule_set += 1
        if apply_closing_time(t):
            closing_set += 1
            logger.info("Set closing_time for %s %s: %s", t.year, t.name, t.closing_time)

    await db.commit()
    return {"schedule_fields_set": schedule_set, "closing_times_set": closing_set}


@router.get("/{tournament_id}", response_model=TournamentOut)
async def get_tournament(tournament_id: int, db: AsyncSession = Depends(get_db)):
    t = await db.get(Tournament, tournament_id)
    if not t:
        raise HTTPException(404, "Tournament not found")
    lat = await db.execute(
        select(func.max(Match.completed_at)).where(Match.tournament_id == tournament_id)
    )
    t.latest_result_at = lat.scalar_one_or_none()
    return t


@router.get("/{tournament_id}/competitors", response_model=list[UserPublicOut])
async def tournament_competitors(tournament_id: int, db: AsyncSession = Depends(get_db)):
    """Return all users who have submitted complete picks for this tournament."""
    total_result = await db.execute(
        select(func.count())
        .where(Match.tournament_id == tournament_id, Match.is_bye == False)
    )
    total = total_result.scalar_one()
    if total == 0:
        return []

    sub = (
        select(UserPrediction.user_id)
        .where(
            UserPrediction.tournament_id == tournament_id,
            UserPrediction.predicted_winner_id.isnot(None),
        )
        .group_by(UserPrediction.user_id)
        .having(func.count() >= total)
    )
    result = await db.execute(
        select(User).where(User.id.in_(sub)).order_by(User.display_name)
    )
    return result.scalars().all()


@router.get("/{tournament_id}/standings", response_model=list[LeaderboardEntry])
async def global_standings(tournament_id: int, db: AsyncSession = Depends(get_db)):
    """Global standings for a tournament using classic scoring (no league)."""
    tournament = await db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(404, "Tournament not found")

    total_result = await db.execute(
        select(func.count()).where(Match.tournament_id == tournament_id, Match.is_bye == False)
    )
    total_matches = total_result.scalar_one()
    if total_matches == 0:
        return []

    completed_result = await db.execute(
        select(Match)
        .options(selectinload(Match.player1), selectinload(Match.player2), selectinload(Match.winner))
        .where(Match.tournament_id == tournament_id, Match.status == "completed")
    )
    completed_matches = completed_result.scalars().all()

    # Classic points: round_number → 2^(r-1)
    pts_table = {r: 2 ** (r - 1) for r in range(1, tournament.num_rounds + 1)}
    final_round = tournament.num_rounds

    sub = (
        select(UserPrediction.user_id)
        .where(UserPrediction.tournament_id == tournament_id, UserPrediction.predicted_winner_id.isnot(None))
        .group_by(UserPrediction.user_id)
        .having(func.count() >= total_matches)
    )
    users_result = await db.execute(select(User).where(User.id.in_(sub)))
    users = users_result.scalars().all()

    scores: list[UserScore] = []
    for user in users:
        preds_result = await db.execute(
            select(UserPrediction).where(
                UserPrediction.user_id == user.id,
                UserPrediction.tournament_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        preds = preds_result.scalars().all()
        pred_by_match = {p.match_id: p.predicted_winner_id for p in preds}

        total_pts = 0.0
        correct = 0
        champ = False
        finalist = False
        for m in completed_matches:
            if m.winner_id is None:
                continue
            if pred_by_match.get(m.id) == m.winner_id:
                total_pts += pts_table.get(m.round_number, 0)
                correct += 1
                if m.round_number == final_round:
                    champ = True
                elif m.round_number == final_round - 1:
                    finalist = True
        scores.append(UserScore(user_id=user.id, total_points=total_pts, correct_count=correct,
                                champion_correct=champ, finalist_correct=finalist))

    ranked = rank_users(scores)
    user_map = {u.id: u for u in users}
    return [
        LeaderboardEntry(rank=i + 1, user=user_map[s.user_id], total_points=s.total_points,
                         correct_count=s.correct_count, champion_correct=s.champion_correct,
                         finalist_correct=s.finalist_correct)
        for i, s in enumerate(ranked)
    ]


@router.get("/{tournament_id}/draw", response_model=DrawOut)
async def get_draw(tournament_id: int, db: AsyncSession = Depends(get_db)):
    t = await db.get(Tournament, tournament_id)
    if not t:
        raise HTTPException(404, "Tournament not found")

    players_result = await db.execute(
        select(DrawEntry).where(DrawEntry.tournament_id == tournament_id).order_by(DrawEntry.bracket_position)
    )
    players = players_result.scalars().all()

    # Bulk-load te_slug and date_of_birth from te_players for all players with a TE identity
    te_ids = [p.te_player_id for p in players if p.te_player_id is not None]
    te_slug_map: dict[int, str] = {}
    te_dob_map: dict[int, "date"] = {}
    if te_ids:
        te_res = await db.execute(
            select(TePlayer.id, TePlayer.te_slug, TePlayer.date_of_birth).where(TePlayer.id.in_(te_ids))
        )
        for row in te_res:
            if row.te_slug:
                te_slug_map[row.id] = row.te_slug
            if row.date_of_birth:
                te_dob_map[row.id] = row.date_of_birth

    matches_result = await db.execute(
        select(Match)
        .where(Match.tournament_id == tournament_id)
        .options(
            selectinload(Match.player1),
            selectinload(Match.player2),
            selectinload(Match.winner),
        )
        .order_by(Match.round_number, Match.match_number)
    )
    matches = matches_result.scalars().all()

    def _player_out(p: DrawEntry) -> DrawEntryOut:
        out = DrawEntryOut.model_validate(p)
        out.te_slug = te_slug_map.get(p.te_player_id) if p.te_player_id else None
        out.date_of_birth = te_dob_map.get(p.te_player_id) if p.te_player_id else None
        return out

    match_outs = []
    for m in matches:
        match_outs.append(MatchOut(
            id=m.id,
            round_number=m.round_number,
            match_number=m.match_number,
            player1=_player_out(m.player1) if m.player1 else None,
            player2=_player_out(m.player2) if m.player2 else None,
            winner=_player_out(m.winner) if m.winner else None,
            is_bye=m.is_bye,
            status=m.status,
            round_name=t.round_name(m.round_number),
            scores=m.scores_json,
        ))

    t.latest_result_at = max((m.completed_at for m in matches if m.completed_at), default=None)
    return DrawOut(
        tournament=TournamentOut.model_validate(t),
        draw_entries=[_player_out(p) for p in players],
        matches=match_outs,
    )


@router.post("/{tournament_id}/refresh", response_model=TournamentOut)
async def refresh_draw(
    tournament_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    import asyncio
    from app.services.h2h import prefetch_h2h_for_draw
    from app.services.rankings import prefetch_dob_for_draw

    t = await db.get(Tournament, tournament_id)
    if not t:
        raise HTTPException(404, "Tournament not found")
    await _do_scrape(t, db, force_refresh=True)
    await db.commit()
    await db.refresh(t)
    # Kick off background tasks — neither blocks the response
    asyncio.create_task(prefetch_h2h_for_draw(tournament_id))
    asyncio.create_task(prefetch_dob_for_draw(tournament_id))
    return t


@router.post("/{tournament_id}/toggle-unlock", response_model=TournamentOut)
async def toggle_unlock_selections(
    tournament_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(403, "Admin only")
    t = await db.get(Tournament, tournament_id)
    if not t:
        raise HTTPException(404, "Tournament not found")
    t.selections_unlocked = not t.selections_unlocked
    await db.commit()
    await db.refresh(t)
    return t


# ---------------------------------------------------------------------------
# Internal scrape helper
# ---------------------------------------------------------------------------

async def _do_scrape(tournament: Tournament, db: AsyncSession, force_refresh: bool = False) -> None:
    from datetime import date
    import logging
    logger = logging.getLogger(__name__)

    parsed = await scrape_tournament(
        tournament.wiki_page_title,
        year=tournament.year,
        gender=tournament.gender,
        page_id=tournament.wiki_page_id,
        force_refresh=force_refresh,
    )
    if parsed.wiki_page_id and tournament.wiki_page_id is None:
        tournament.wiki_page_id = parsed.wiki_page_id
    if parsed.resolved_title:
        logger.info("Correcting wiki_page_title for %s: %r → %r",
                    tournament.name, tournament.wiki_page_title, parsed.resolved_title)
        tournament.wiki_page_title = parsed.resolved_title

    if parsed.draw_size:
        tournament.draw_size = parsed.draw_size
    if parsed.num_rounds:
        tournament.num_rounds = parsed.num_rounds
    tournament.last_scraped_at = datetime.now(timezone.utc)

    # Update location from infobox if not already set
    if parsed.city and not tournament.city:
        tournament.city = parsed.city
    if parsed.country and not tournament.country:
        tournament.country = parsed.country

    # Auto-populate schedule fields and closing_time from lookup table
    from app.services.tournament_schedule import apply_schedule, apply_closing_time
    apply_schedule(tournament)
    if apply_closing_time(tournament):
        logger.info(
            "Auto-set closing_time for %s %s: %s (tz=%s %02d:%02d local)",
            tournament.year, tournament.name, tournament.closing_time,
            tournament.venue_timezone, tournament.day1_start_hour or 0,
            tournament.day1_start_minute or 0,
        )

    # Authoritative dates from the tournament's own infobox
    if parsed.start_date:
        tournament.start_date = parsed.start_date
    if parsed.end_date:
        tournament.end_date = parsed.end_date

    # Record actual draw release dates when detected.
    # Only stamp draw_released_direct_at once the draw is substantially complete
    # (≥85% of expected draw_size — essentially all DA slots filled).
    # A page with only a handful of seeded players is not a released draw.
    da_players = [p for p in parsed.players if p.name and p.entry_type not in ("Q", "LL")]
    draw_substantially_complete = (
        tournament.draw_size > 0 and len(da_players) >= tournament.draw_size * 0.85
    )
    if parsed.has_direct_draw and draw_substantially_complete:
        if not tournament.draw_released_direct_at:
            tournament.draw_released_direct_at = date.today()
            logger.info("Tournament %s: Direct acceptance draw released on %s (%d players)",
                       tournament.wiki_page_title, date.today(), len(da_players))
    elif tournament.draw_released_direct_at and not draw_substantially_complete \
            and tournament.status not in ("active", "completed"):
        # Draw was stamped prematurely (e.g. only seeds visible) — revert until complete
        tournament.draw_released_direct_at = None
        logger.info("Tournament %s: Clearing premature draw release (%d/%d players present)",
                   tournament.wiki_page_title, len(da_players), tournament.draw_size)

    if parsed.has_qualifiers and not tournament.draw_released_qualifiers_at:
        tournament.draw_released_qualifiers_at = date.today()
        logger.info("Tournament %s: Qualifiers added on %s",
                   tournament.wiki_page_title, date.today())

    # If final match has a winner, tournament is completed regardless of current date
    if parsed.has_final_winner:
        tournament.status = "completed"
        logger.info("Tournament %s marked as completed (final match has winner)", tournament.wiki_page_title)

    # Load existing players and matches indexed for upsert
    existing_players_res = await db.execute(
        select(DrawEntry).where(DrawEntry.tournament_id == tournament.id)
    )
    existing_players: dict[int, DrawEntry] = {
        p.bracket_position: p for p in existing_players_res.scalars()
    }
    existing_matches_res = await db.execute(
        select(Match).where(Match.tournament_id == tournament.id)
    )
    existing_matches: dict[tuple, Match] = {
        (m.round_number, m.match_number): m for m in existing_matches_res.scalars()
    }

    # Detect whether the player roster changed (additions, removals, or replacements).
    # Rankings are only re-fetched when the roster changes — not on every match-result sync.
    incoming_positions = {pe.bracket_position for pe in parsed.players}
    roster_changed = (
        incoming_positions != set(existing_players.keys())
        or any(
            pe.name != existing_players[pe.bracket_position].name
            for pe in parsed.players
            if pe.bracket_position in existing_players
        )
    )

    # Upsert players — update in place to preserve any FK references
    pos_to_player_id: dict[int, int] = {}
    seen_positions: set[int] = set()
    upserted_players: list[DrawEntry] = []
    for pe in parsed.players:
        seen_positions.add(pe.bracket_position)
        if pe.bracket_position in existing_players:
            player = existing_players[pe.bracket_position]
            player.name = pe.name
            player.nationality = pe.nationality
            player.seed = pe.seed
            player.entry_type = pe.entry_type
        else:
            player = DrawEntry(
                tournament_id=tournament.id,
                name=pe.name,
                nationality=pe.nationality,
                seed=pe.seed,
                entry_type=pe.entry_type,
                bracket_position=pe.bracket_position,
            )
            db.add(player)
            await db.flush()
        pos_to_player_id[pe.bracket_position] = player.id
        upserted_players.append(player)

    if roster_changed:
        try:
            ref_date = tournament.start_date or date.today()
            await assign_rankings(upserted_players, tournament.gender, ref_date, db)
            logger.info("Roster change in %s — rankings assigned", tournament.name)
        except Exception as exc:
            logger.warning("Could not assign rankings for %s: %s", tournament.name, exc)

    # Delete players no longer in draw
    for pos, old_player in existing_players.items():
        if pos not in seen_positions:
            await db.delete(old_player)
    await db.flush()

    # Upsert matches — update in place to preserve prediction foreign keys
    seen_match_keys: set[tuple] = set()
    for mr in parsed.matches:
        p1_id = pos_to_player_id.get(mr.player1_position)
        p2_id = pos_to_player_id.get(mr.player2_position) if mr.player2_position else None
        w_id = pos_to_player_id.get(mr.winner_position) if mr.winner_position else None
        key = (mr.round_number, mr.match_number)
        seen_match_keys.add(key)
        if key in existing_matches:
            match = existing_matches[key]
            if w_id and match.winner_id != w_id:
                match.completed_at = datetime.now(timezone.utc)
            elif not w_id:
                match.completed_at = None
            match.player1_id = p1_id
            match.player2_id = p2_id
            match.winner_id = w_id
            match.is_bye = mr.is_bye
            match.scores_json = mr.scores
            match.status = "completed" if w_id else "pending"
        else:
            match = Match(
                tournament_id=tournament.id,
                round_number=mr.round_number,
                match_number=mr.match_number,
                player1_id=p1_id,
                player2_id=p2_id,
                winner_id=w_id,
                is_bye=mr.is_bye,
                scores_json=mr.scores,
                status="completed" if w_id else "pending",
                completed_at=datetime.now(timezone.utc) if w_id else None,
            )
            db.add(match)

    # Delete matches no longer in draw (and their orphaned predictions)
    from app.models.prediction import UserPrediction
    for key, old_match in existing_matches.items():
        if key not in seen_match_keys:
            orphaned = await db.execute(
                select(UserPrediction).where(UserPrediction.match_id == old_match.id)
            )
            for pred in orphaned.scalars():
                await db.delete(pred)
            await db.delete(old_match)

    # Auto-set tournament status
    from datetime import date as _date
    total_matches = len(parsed.matches)
    completed = sum(1 for m in parsed.matches if m.winner_position is not None)
    started = tournament.start_date is None or tournament.start_date <= _date.today()
    if completed == total_matches and completed > 0:
        tournament.status = "completed"
    elif completed > 0 and started:
        tournament.status = "active"
    else:
        tournament.status = "upcoming"
