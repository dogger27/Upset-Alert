from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user, get_optional_user
from app.database import get_db
from app.models.prediction import UserPrediction
from app.models.rankings import TePlayer, TeRankingsSnapshot
from app.models.tournament import DrawEntry, Match, Draw
from app.models.user import User
from app.schemas.league import LeaderboardEntry, LeagueTournamentOut
from app.schemas.tournament import DrawEntryOut, DrawOut, MatchOut, TournamentCreate, TournamentOut
from app.schemas.user import UserPublicOut
from app.services.draw_changes import classify_change
from app.services.rankings import assign_rankings
from app.services.scraper import scrape_tournament, snap_to_monday
from app.services.scoring import UserScore, _points_table, rank_users
from app.services.upsets import has_upset_pick

router = APIRouter(prefix="/tournaments", tags=["tournaments"])

# How many named unseeded players must hold bracket slots before we accept that
# the draw has actually been made (see the publication-signal block in
# _do_scrape). Small on purpose — the point is to catch publication early, and
# unseeded names cannot appear from a seeds-only entry-list placement. Kept
# above 1 so a single stray wildcard or parse artefact can't trip it.
BRACKET_PUBLISHED_MIN_UNSEEDED = 4


@router.get("", response_model=list[TournamentOut])
async def list_tournaments(db: AsyncSession = Depends(get_db)):
    lat_subq = (
        select(Match.draw_id, func.max(Match.completed_at).label("lat"))
        .group_by(Match.draw_id)
        .subquery()
    )
    result = await db.execute(
        select(Draw, lat_subq.c.lat)
        .outerjoin(lat_subq, Draw.id == lat_subq.c.draw_id)
        .order_by(Draw.year.desc(), Draw.name)
    )
    rows = result.all()
    # Serialised, never assigned back. Writing to a loaded ORM row marks it
    # dirty and the next query in the session autoflushes it as a real UPDATE —
    # which is how a GET comes to hold a write lock. Both of these are computed
    # for the response and neither belongs in the column.
    return [
        TournamentOut.model_validate(t).model_copy(
            update={"status": t.computed_status, "latest_result_at": lat})
        for t, lat in rows
    ]


@router.post("", response_model=TournamentOut, status_code=201)
async def create_tournament(
    body: TournamentCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    t = Draw(
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
        select(Draw).where(
            and_(
                Draw.status != "completed",
                or_(
                    # Already started
                    and_(Draw.start_date != None, Draw.start_date <= today),
                    # DA draw date has passed but not yet confirmed
                    and_(
                        Draw.draw_release_direct != None,
                        Draw.draw_release_direct <= today,
                        Draw.draw_released_direct_at == None,
                    ),
                    # Qualifier date has passed but not yet confirmed
                    and_(
                        Draw.draw_release_qualifiers != None,
                        Draw.draw_release_qualifiers <= today,
                        Draw.draw_released_qualifiers_at == None,
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
            t = await db.get(Draw, t_id)
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

    # Same rule as refresh_all above: hold ids/names, not ORM objects. One
    # failure's rollback expires every attached instance, and reading `t.name`
    # on the next pass would then need a lazy reload the event loop can't do.
    tournaments_res = await db.execute(select(Draw.id, Draw.name))
    tournament_info = tournaments_res.all()

    updated_total = 0
    failed = []

    for t_id, t_name in tournament_info:
        try:
            t = await db.get(Draw, t_id)
            if t is None:
                continue
            ref_date = t.entry_ranking_week or t.start_date or date.today()
            players_res = await db.execute(select(DrawEntry).where(DrawEntry.draw_id == t_id))
            players = players_res.scalars().all()

            before = [p.ranking for p in players]
            await assign_rankings(players, t.gender, ref_date, db)
            after = [p.ranking for p in players]

            updated = sum(1 for b, a in zip(before, after) if b != a)
            await db.commit()
            updated_total += updated
            logger.info("%s: updated %d/%d player rankings", t_name, updated, len(players))
        except Exception as exc:
            logger.error("Failed rankings backfill for %s: %s", t_name, exc)
            await db.rollback()
            failed.append(t_name)

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

    result = await db.execute(select(Draw))
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


def _tier(category: Optional[str]) -> str:
    cat = (category or "").upper()
    if "SLAM" in cat or "GRAND" in cat:
        return "Grand Slam"
    if "1000" in cat:
        return "1000"
    if "500" in cat:
        return "500"
    return "250"


_TIER_ORDER = ["Grand Slam", "1000", "500", "250"]


_HOF_TOP_N = 5


@router.get("/hall-of-fame")
async def hall_of_fame(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Top 5 all-time scores per tier/gender, plus the caller's own best if outside the top 5."""
    from app.models.draw_history import TournamentResult

    # Every stored result counts — a partial bracket competes like any other,
    # it just has fewer chances to score. Only the draw's match count is needed.
    match_count_sq = (
        select(Match.draw_id, func.count().label("total"))
        .where(Match.is_bye == False)  # noqa: E712
        .group_by(Match.draw_id)
        .subquery()
    )

    res = await db.execute(
        select(
            TournamentResult.draw_id,
            TournamentResult.user_id,
            TournamentResult.points,
            TournamentResult.correct_count,
            match_count_sq.c.total.label("total_matches"),
            Draw.name,
            Draw.year,
            Draw.gender,
            Draw.category,
            User.username,
        )
        .join(Draw, Draw.id == TournamentResult.draw_id)
        .join(User, User.id == TournamentResult.user_id)
        .join(match_count_sq, match_count_sq.c.draw_id == TournamentResult.draw_id)
        .where(TournamentResult.league_id.is_(None))
        .order_by(TournamentResult.points.desc())
    )
    rows = res.all()

    me_id = current_user.id if current_user else None

    by_tier: dict[str, dict[str, list]] = {t: {"M": [], "F": []} for t in _TIER_ORDER}
    seen: dict[str, set] = {t: set() for t in _TIER_ORDER}  # (username, tournament_id) per tier
    ranked: dict[str, dict[str, int]] = {t: {"M": 0, "F": 0} for t in _TIER_ORDER}
    # Caller's best result per tier/gender when it falls outside the top 5
    mine: dict[str, dict[str, Optional[dict]]] = {t: {"M": None, "F": None} for t in _TIER_ORDER}

    for row in rows:
        tier = _tier(row.category)
        gender = row.gender  # "M" or "F"
        if gender not in ("M", "F"):
            continue
        key = (row.username, row.draw_id)
        if key in seen[tier]:
            continue
        seen[tier].add(key)

        ranked[tier][gender] += 1
        entry = {
            "rank": ranked[tier][gender],
            "user_id": row.user_id,
            "username": row.username,
            "points": row.points,
            "correct_count": row.correct_count,
            "total_matches": row.total_matches,
            "tournament_id": row.draw_id,
            "tournament_name": row.name,
            "tournament_year": row.year,
            "is_current_user": row.user_id == me_id,
        }

        if entry["rank"] <= _HOF_TOP_N:
            by_tier[tier][gender].append(entry)
        elif row.user_id == me_id and mine[tier][gender] is None:
            # rows are ordered by points desc, so the first one seen is their best
            mine[tier][gender] = entry

    def bucket(tier: str, gender: str) -> list:
        entries = by_tier[tier][gender]
        extra = mine[tier][gender]
        if extra and not any(e["user_id"] == me_id for e in entries):
            return entries + [extra]
        return entries

    return [
        {"tier": tier, "men": bucket(tier, "M"), "women": bucket(tier, "F")}
        for tier in _TIER_ORDER
    ]


@router.get("/global-gs-totals")
async def global_gs_totals(db: AsyncSession = Depends(get_db)):
    """Grand Slam point totals for ALL verified users this year, with is_admin flag."""
    from datetime import date
    from collections import defaultdict
    from app.services.scoring import _points_table

    year = date.today().year
    gs_result = await db.execute(
        select(Draw).where(Draw.year == year, Draw.category.ilike('%grand slam%'))
    )
    gs_draws = gs_result.scalars().all()

    users_result = await db.execute(
        select(User).where(User.email_verified == True).order_by(User.username)
    )
    users = users_result.scalars().all()
    user_ids = [u.id for u in users]

    atp: dict = defaultdict(float)
    wta: dict = defaultdict(float)

    for draw in gs_draws:
        pts_table = _points_table(draw)
        cm_result = await db.execute(
            select(Match).where(
                Match.draw_id == draw.id,
                Match.status == "completed",
                Match.is_bye == False,
            )
        )
        completed = cm_result.scalars().all()
        if not completed:
            continue
        for user_id in user_ids:
            preds_result = await db.execute(
                select(UserPrediction).where(
                    UserPrediction.user_id == user_id,
                    UserPrediction.draw_id == draw.id,
                    UserPrediction.predicted_winner_id.isnot(None),
                )
            )
            pred_by_match = {p.match_id: p.predicted_winner_id for p in preds_result.scalars().all()}
            for m in completed:
                if m.winner_id and pred_by_match.get(m.id) == m.winner_id:
                    pts = pts_table.get(m.round_number, 0)
                    if draw.gender == 'M':
                        atp[user_id] += pts
                    else:
                        wta[user_id] += pts

    entries = [
        {
            "user_id": u.id,
            "username": u.username,
            "full_name": u.full_name,
            "is_admin": u.is_admin,
            "atp_points": int(atp[u.id]),
            "wta_points": int(wta[u.id]),
        }
        for u in users
    ]
    entries.sort(key=lambda x: -(x["atp_points"] + x["wta_points"]))
    return {"year": year, "members": entries}


@router.get("/global-draws", response_model=list[LeagueTournamentOut])
async def global_draws(db: AsyncSession = Depends(get_db)):
    """Draws where at least one user has entered picks, with global picker counts."""
    from collections import defaultdict

    picks_result = await db.execute(
        select(
            UserPrediction.draw_id,
            UserPrediction.user_id,
            func.count().label("pick_count"),
        )
        .where(UserPrediction.predicted_winner_id.isnot(None))
        .group_by(UserPrediction.draw_id, UserPrediction.user_id)
    )
    picks_rows = picks_result.all()

    t_ids = list({r.draw_id for r in picks_rows})
    if not t_ids:
        return []

    # One pick is enough to be entered — a partial bracket still competes.
    entered: defaultdict = defaultdict(int)
    for r in picks_rows:
        if r.pick_count > 0:
            entered[r.draw_id] += 1

    # Fetch first, then decorate. Assigning to a loaded row marks it dirty, and
    # the NEXT db.get in this loop autoflushes it as an UPDATE — a read endpoint
    # taking a write lock, which is what surfaced as "database is locked" on the
    # draw page. Splitting the loop leaves no query after the assignment.
    found = []
    for draw_id, picker_count in entered.items():
        t = await db.get(Draw, draw_id)
        if t:
            found.append((t, picker_count))

    # Overridden on the way out, not on the row — see the note in the list
    # endpoint above.
    return [
        LeagueTournamentOut(
            tournament=TournamentOut.model_validate(t).model_copy(
                update={"status": t.computed_status}),
            picker_count=picker_count,
        )
        for t, picker_count in found
    ]


@router.get("/{tournament_id}", response_model=TournamentOut)
async def get_tournament(tournament_id: int, db: AsyncSession = Depends(get_db)):
    t = await db.get(Draw, tournament_id)
    if not t:
        raise HTTPException(404, "Tournament not found")
    lat = await db.execute(
        select(func.max(Match.completed_at)).where(Match.draw_id == tournament_id)
    )
    t.latest_result_at = lat.scalar_one_or_none()
    # Same override every other serializing endpoint applies — "open" exists
    # only in computed_status, so without this the raw column leaks out and
    # any status === 'open' check against this endpoint silently fails.
    # NEVER ASSIGNED TO THE ROW. Writing to a loaded ORM row marks it dirty and
    # the next query in the session autoflushes it as a real UPDATE — which is
    # how a GET came to hold a write lock and fail with "database is locked".
    # Ordering the assignment after the queries was the old defence and it was
    # too fragile: one query added below it, at any depth, brings the fault
    # straight back. "open" is PURELY computed and must never reach the column,
    # so it is set on the RESPONSE, where nothing can flush it.
    return TournamentOut.model_validate(t).model_copy(
        update={"status": t.computed_status})


@router.get("/{tournament_id}/competitors", response_model=list[UserPublicOut])
async def tournament_competitors(tournament_id: int, db: AsyncSession = Depends(get_db)):
    """Return all users competing in this tournament — one pick is enough."""
    sub = (
        select(UserPrediction.user_id)
        .where(
            UserPrediction.draw_id == tournament_id,
            UserPrediction.predicted_winner_id.isnot(None),
        )
        .group_by(UserPrediction.user_id)
    )
    result = await db.execute(
        select(User).where(User.id.in_(sub)).order_by(User.display_name)
    )
    return result.scalars().all()


@router.get("/{tournament_id}/compare-picks")
async def compare_picks(
    tournament_id: int,
    league_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Everyone's late-round picks side by side — who each user has winning
    the quarterfinals, semifinals and final of one draw.

    Scoped to a league's members when league_id is given, else to every user
    with a pick in the draw (the Global view). Gated by the same
    predictions_visible rule as the draw itself: before picks lock, another
    user's bracket is not yours to read."""
    from app.models.league import League, LeagueMember
    from app.services.locking import predictions_visible

    tournament = await db.get(Draw, tournament_id)
    if not tournament:
        raise HTTPException(404, "Tournament not found")
    if not await predictions_visible(db, tournament):
        return {"hidden": True, "rounds": [], "users": []}

    matches = (await db.execute(
        select(Match).where(Match.draw_id == tournament_id,
                            Match.is_bye == False))).scalars().all()
    if not matches:
        return {"hidden": False, "rounds": [], "users": []}
    max_round = max(m.round_number for m in matches)
    tiers = [(rn, label) for rn, label in
             ((max_round - 2, "QF"), (max_round - 1, "SF"), (max_round, "F"))
             if rn >= 1]
    tier_of = {rn: label for rn, label in tiers}
    late = {m.id: (tier_of[m.round_number], m.match_number)
            for m in matches if m.round_number in tier_of}

    scope_ids = None
    usernames: dict[int, str] = {}
    if league_id is not None:
        league = (await db.execute(
            select(League).options(
                selectinload(League.members).selectinload(LeagueMember.user))
            .where(League.id == league_id))).scalar_one_or_none()
        if not league:
            raise HTTPException(404, "League not found")
        if (not league.is_public and not current_user.is_admin
                and league.owner_id != current_user.id
                and not any(m.user_id == current_user.id for m in league.members)):
            raise HTTPException(403, "Not a member of this league")
        scope_ids = {m.user_id for m in league.members}
        usernames = {m.user_id: m.user.username for m in league.members}

    stmt = (select(UserPrediction, User.username)
            .join(User, User.id == UserPrediction.user_id)
            .where(UserPrediction.draw_id == tournament_id,
                   UserPrediction.predicted_winner_id.isnot(None),
                   UserPrediction.match_id.in_(list(late))))
    rows = (await db.execute(stmt)).all()

    # The name as the bracket prints it — seed or entry token in front
    # ("[6] Donna Vekić", "[WC] Alycia Parks", "[Q] Maria Timofeeva"), so the
    # comparison carries the same at-a-glance context as the draw page.
    def _tagged(e) -> str:
        tag = e.seed if e.seed is not None else e.entry_type
        return f"[{tag}] {e.name}" if tag else e.name
    entry_names = {e.id: _tagged(e) for e in (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == tournament_id))).scalars()}

    by_user: dict[int, dict] = {}
    for pred, username in rows:
        if scope_ids is not None and pred.user_id not in scope_ids:
            continue
        tier, match_number = late[pred.match_id]
        u = by_user.setdefault(pred.user_id, {
            "user_id": pred.user_id,
            "username": usernames.get(pred.user_id, username),
            "picks": {label: [] for _, label in tiers},
        })
        name = entry_names.get(pred.predicted_winner_id)
        if name:
            u["picks"][tier].append((match_number, name))

    users = []
    for u in by_user.values():
        u["picks"] = {k: [n for _, n in sorted(v)] for k, v in u["picks"].items()}
        users.append(u)
    users.sort(key=lambda x: (x["username"] or "").lower())
    return {"hidden": False,
            "rounds": [label for _, label in tiers],
            "users": users}


@router.get("/{tournament_id}/matches/{match_id}/score-history")
async def match_score_history(
    tournament_id: int,
    match_id: int,
    db: AsyncSession = Depends(get_db),
):
    """How a match's score progressed, for the draw page's scrubber popup.

    Public, like the draw itself — a score is not anyone's secret. Snapshots
    come back ascending and already in the `live_point` shape the schedule
    renderer reads (renderable_history), so the client renders each slider
    position through the same component that draws every other score on the
    site. `final` is matches.scores_json: the record, which the last live
    snapshot can miss the closing point of.

    An empty `snapshots` list is a normal answer, not an error — a match played
    before the feature existed, or one whose draw finished more than a day ago
    and was pruned. The popup shows the final score alone.
    """
    from app.models.score_history import MatchScoreSnapshot
    from app.services.sofascore_live import renderable_history

    match = await db.get(Match, match_id)
    if not match or match.draw_id != tournament_id:
        raise HTTPException(404, "Match not found")

    rows = (await db.execute(
        select(MatchScoreSnapshot)
        .where(MatchScoreSnapshot.match_id == match_id)
        .order_by(MatchScoreSnapshot.id)
    )).scalars().all()

    snapshots = []
    for r in rows:
        out = renderable_history(r.snap)
        if out is not None:
            snapshots.append(out)

    # Which draw entry the snapshots' side 1 is. Snapshots are stored in the
    # MATCH's orientation (games[0] = player1 — the poller flips Sofascore's
    # home/away to guarantee it), and the draw page shows player1 on top — but
    # the SCHEDULE popup shows the sheet's order, which need not agree. The
    # timeline hangs each tick beside the player who earned it, so the client
    # has to be able to line the two orientations up; id for the stamped case,
    # name for the rows the resolver has not reached.
    p1 = await db.get(DrawEntry, match.player1_id) if match.player1_id else None
    return {
        "status": match.status,
        "completed_at": match.completed_at,
        "player1_id": match.player1_id,
        "player1_name": p1.name if p1 else None,
        "snapshots": snapshots,
        "final": match.scores_json,
    }


@router.get("/{tournament_id}/matches/{match_id}/predictors")
async def match_predictors(
    tournament_id: int,
    match_id: int,
    league_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Who called a finished match right, and who didn't.

    Scoped to the league the draw page currently has selected, or to every
    participant in the draw when it is on Global. "Participant" means at least
    one pick in this draw — the same bar the standings use. A league member who
    never entered this draw is not wrong about the match, they simply are not
    playing it, and listing them would misrepresent both columns.

    Only completed non-bye matches answer; anything else has no outcome to have
    been right about.
    """
    from app.models.league import League, LeagueMember
    from app.routers.leagues import _check_access

    match = await db.get(Match, match_id)
    if not match or match.draw_id != tournament_id:
        raise HTTPException(404, "Match not found")
    if match.is_bye or match.winner_id is None:
        return {"correct": [], "incorrect": [], "league_name": None}

    # Naming who called a match right names their pick. Held back until the
    # first round is complete for the same reason the brackets are: under
    # progressive locking the rest of the round is still being predicted.
    from app.services.locking import predictions_visible
    _draw = await db.get(Draw, tournament_id)
    if _draw is not None and not await predictions_visible(db, _draw):
        return {"correct": [], "incorrect": [], "league_name": None, "hidden": True}

    # Everyone with a pick in this draw — the participant pool.
    participants_res = await db.execute(
        select(UserPrediction.user_id)
        .where(
            UserPrediction.draw_id == tournament_id,
            UserPrediction.predicted_winner_id.isnot(None),
        )
        .group_by(UserPrediction.user_id)
    )
    participant_ids = {r[0] for r in participants_res.all()}

    league_name = None
    if league_id is not None:
        league_res = await db.execute(
            select(League)
            .options(selectinload(League.owner), selectinload(League.members))
            .where(League.id == league_id)
        )
        league = league_res.scalar_one_or_none()
        if not league:
            raise HTTPException(404, "League not found")
        _check_access(league, current_user)
        league_name = league.name
        member_res = await db.execute(
            select(LeagueMember.user_id).where(LeagueMember.league_id == league_id)
        )
        participant_ids &= {r[0] for r in member_res.all()}

    if not participant_ids:
        return {"correct": [], "incorrect": [], "league_name": league_name}

    picks_res = await db.execute(
        select(UserPrediction.user_id, UserPrediction.predicted_winner_id).where(
            UserPrediction.match_id == match_id,
            UserPrediction.user_id.in_(participant_ids),
        )
    )
    picked_winner = {uid: wid for uid, wid in picks_res.all()}

    # Case-insensitive: a plain ORDER BY username puts every capitalised handle
    # ahead of every lowercase one ("Tono" before "dogger27"), which reads as
    # unsorted. Ordered on the handle the UI actually shows — see UserName.
    users_res = await db.execute(
        select(User)
        .where(User.id.in_(participant_ids))
        .order_by(func.lower(func.coalesce(User.username, User.display_name)))
    )
    correct, incorrect = [], []
    for u in users_res.scalars().all():
        got_it = picked_winner.get(u.id) == match.winner_id
        (correct if got_it else incorrect).append(UserPublicOut.model_validate(u))

    return {"correct": correct, "incorrect": incorrect, "league_name": league_name}


@router.get("/{tournament_id}/standings", response_model=list[LeaderboardEntry])
async def global_standings(tournament_id: int, db: AsyncSession = Depends(get_db)):
    """Global standings for a tournament using classic scoring (no league)."""
    tournament = await db.get(Draw, tournament_id)
    if not tournament:
        raise HTTPException(404, "Tournament not found")

    total_result = await db.execute(
        select(func.count()).where(Match.draw_id == tournament_id, Match.is_bye == False)
    )
    total_matches = total_result.scalar_one()
    if total_matches == 0:
        return []

    completed_result = await db.execute(
        select(Match)
        .options(selectinload(Match.player1), selectinload(Match.player2), selectinload(Match.winner))
        # is_bye excluded: a bye is not a contest. It is stamped completed with
        # an auto-advanced winner, and stray picks do sit on those rows, so
        # scoring them hands out free points.
        .where(Match.draw_id == tournament_id, Match.status == "completed",
               Match.is_bye == False)  # noqa: E712
    )
    completed_matches = completed_result.scalars().all()

    # All matches (not just completed) + draw entries — needed to determine
    # whether a user's picks include at least one upset (a user must pick at
    # least one to count as "participating"), which requires resolving every
    # round's entrants, not just ones already decided.
    all_matches_result = await db.execute(
        select(Match).where(Match.draw_id == tournament_id)
    )
    all_matches = all_matches_result.scalars().all()
    all_entries_result = await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == tournament_id)
    )
    all_entries = all_entries_result.scalars().all()

    # The real Classic table (tier x round), same as league standings, stored
    # results, the Hall of Fame and the round-complete emails. This used to be
    # a local 2^(r-1) approximation, which quietly gave this one screen a
    # different point total than every other view of the same picks.
    pts_table = _points_table(tournament)

    # Users with at least one pick. A partial bracket is still a competing
    # entry — it simply forfeits points on the matches left unpicked. The only
    # bar to competing is picking zero upsets (has_upset_pick below).
    sub = (
        select(UserPrediction.user_id)
        .where(UserPrediction.draw_id == tournament_id, UserPrediction.predicted_winner_id.isnot(None))
        .group_by(UserPrediction.user_id)
    )
    users_result = await db.execute(select(User).where(User.id.in_(sub)))
    users = users_result.scalars().all()

    scores: list[UserScore] = []
    has_upset_map: dict[int, bool] = {}
    for user in users:
        preds_result = await db.execute(
            select(UserPrediction).where(
                UserPrediction.user_id == user.id,
                UserPrediction.draw_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        preds = preds_result.scalars().all()
        pred_by_match = {p.match_id: p.predicted_winner_id for p in preds}
        has_upset_map[user.id] = has_upset_pick(preds, all_matches, all_entries)

        total_pts = 0.0
        correct = 0
        correct_by_round: dict[int, int] = {}
        for m in completed_matches:
            if m.winner_id is None:
                continue
            if pred_by_match.get(m.id) == m.winner_id:
                total_pts += pts_table.get(m.round_number, 0)
                correct += 1
                correct_by_round[m.round_number] = correct_by_round.get(m.round_number, 0) + 1
        scores.append(UserScore(user_id=user.id, total_points=total_pts, correct_count=correct,
                                correct_by_round=correct_by_round))

    ranked = rank_users(scores, tournament.num_rounds)
    user_map = {u.id: u for u in users}
    return [
        LeaderboardEntry(rank=i + 1, user=user_map[s.user_id], total_points=s.total_points,
                         correct_count=s.correct_count, has_upset_pick=has_upset_map[s.user_id])
        for i, s in enumerate(ranked)
    ]


@router.get("/{tournament_id}/global-round-scores")
async def global_round_scores(tournament_id: int, db: AsyncSession = Depends(get_db)):
    """Per-round point breakdown for every user competing in a tournament."""
    from collections import defaultdict
    from app.services.scoring import _points_table

    tournament = await db.get(Draw, tournament_id)
    if not tournament:
        raise HTTPException(404, "Tournament not found")

    pts_table = _points_table(tournament)

    completed_matches_result = await db.execute(
        select(Match)
        .options(selectinload(Match.player1), selectinload(Match.player2))
        .where(
            Match.draw_id == tournament_id,
            Match.status == "completed",
            Match.is_bye == False,
        )
    )
    completed_matches = completed_matches_result.scalars().all()

    # Anyone with at least one pick is competing — a partial bracket simply
    # scores nothing on the matches it left unpicked.
    sub = (
        select(UserPrediction.user_id)
        .where(UserPrediction.draw_id == tournament_id, UserPrediction.predicted_winner_id.isnot(None))
        .group_by(UserPrediction.user_id)
    )
    users_result = await db.execute(select(User).where(User.id.in_(sub)))
    users = users_result.scalars().all()

    timeline_ids = {m.id for m in completed_matches}
    user_predictions: dict = {}
    entries = []
    for user in users:
        preds_result = await db.execute(
            select(UserPrediction).where(
                UserPrediction.user_id == user.id,
                UserPrediction.draw_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        preds = preds_result.scalars().all()
        pred_by_match = {p.match_id: p.predicted_winner_id for p in preds}
        user_predictions[str(user.id)] = {str(k): v for k, v in pred_by_match.items() if k in timeline_ids}
        by_round: defaultdict = defaultdict(float)
        correct_count = 0
        for match in completed_matches:
            if match.winner_id is None:
                continue
            if pred_by_match.get(match.id) != match.winner_id:
                continue
            by_round[match.round_number] += pts_table.get(match.round_number, 0)
            correct_count += 1

        pts_list = [by_round.get(r, 0) for r in range(1, (tournament.num_rounds or 7) + 1)]
        entries.append({
            "user_id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "round_points": pts_list,
            "total": sum(pts_list),
            "correct_count": correct_count,
        })

    entries.sort(key=lambda x: (-x["total"],) + tuple(-rp for rp in reversed(x["round_points"])))
    rounds_with_matches = sorted({m.round_number for m in completed_matches})

    # A round is "complete" only once every non-bye match in it has finished —
    # not just because it's the highest round with any match played so far
    # (that heuristic misfires when there's a rest day before the next round starts).
    total_by_round_result = await db.execute(
        select(Match.round_number, func.count())
        .where(Match.draw_id == tournament_id, Match.is_bye == False)
        .group_by(Match.round_number)
    )
    total_by_round = dict(total_by_round_result.all())
    completed_by_round: defaultdict = defaultdict(int)
    for m in completed_matches:
        completed_by_round[m.round_number] += 1
    completed_round_nums = sorted(
        r for r, total in total_by_round.items()
        if total > 0 and completed_by_round.get(r, 0) >= total
    )

    def _isoZ(dt):
        if dt is None: return None
        s = dt.isoformat()
        return s if (s.endswith('Z') or '+' in s) else s + 'Z'

    def _entry_name(entry): return entry.name if entry else None
    timeline = sorted(
        [{"id": m.id, "round_number": m.round_number, "winner_id": m.winner_id,
          "points": pts_table.get(m.round_number, 0), "completed_at": _isoZ(m.completed_at),
          "winner_name": _entry_name(m.player1 if m.player1_id == m.winner_id else m.player2),
          "loser_name": _entry_name(m.player2 if m.player1_id == m.winner_id else m.player1)}
         for m in completed_matches],
        key=lambda x: (x["completed_at"] is not None, x["completed_at"] or "", x["id"])
    )
    # Everyone's per-match picks travel in this payload, so it is held back with
    # the rest until the first round is complete. The scores and timeline stay:
    # they say how people are DOING, which the standings show anyway, not what
    # they picked.
    from app.services.locking import predictions_visible
    picks_visible = await predictions_visible(db, tournament)

    return {
        "entries": entries,
        "completed_matches_count": len(completed_matches),
        "rounds_with_matches": rounds_with_matches,
        "completed_round_nums": completed_round_nums,
        "matches_timeline": timeline,
        "user_predictions": user_predictions if picks_visible else {},
        "predictions_hidden": not picks_visible,
    }


@router.get("/{tournament_id}/draw", response_model=DrawOut)
async def get_draw(tournament_id: int, db: AsyncSession = Depends(get_db)):
    t = await db.get(Draw, tournament_id)
    if not t:
        raise HTTPException(404, "Tournament not found")
    players_result = await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == tournament_id).order_by(DrawEntry.bracket_position)
    )
    players = players_result.scalars().all()

    # Bulk-load TE player data for all players with a TE identity
    te_ids = [p.te_player_id for p in players if p.te_player_id is not None]
    te_dob_map: dict[int, "date"] = {}
    te_elo_rank_map: dict[int, int] = {}
    if te_ids:
        te_res = await db.execute(
            select(TePlayer.id, TePlayer.date_of_birth)
            .where(TePlayer.id.in_(te_ids))
        )
        for row in te_res:
            if row.date_of_birth:
                te_dob_map[row.id] = row.date_of_birth

        # ELO rank lives in the rankings snapshot closest to (on or before) this
        # tournament's own ranking-reference date — NOT always the single latest
        # snapshot, otherwise viewing an old/historical draw would show each
        # player's CURRENT Elo rank instead of their rank at the time it was played.
        elo_ref_date = t.entry_ranking_week or t.start_date
        max_week_subq = select(func.max(TeRankingsSnapshot.week_date)).where(
            TeRankingsSnapshot.player_id.in_(te_ids)
        )
        if elo_ref_date:
            max_week_subq = max_week_subq.where(TeRankingsSnapshot.week_date <= elo_ref_date)
        elo_snap_res = await db.execute(
            select(TeRankingsSnapshot.player_id, TeRankingsSnapshot.elo_rank)
            .where(
                TeRankingsSnapshot.player_id.in_(te_ids),
                TeRankingsSnapshot.elo_rank.isnot(None),
                TeRankingsSnapshot.week_date == max_week_subq.scalar_subquery(),
            )
        )
        for row in elo_snap_res:
            if row.elo_rank:
                te_elo_rank_map[row.player_id] = row.elo_rank

    matches_result = await db.execute(
        select(Match)
        .where(Match.draw_id == tournament_id)
        .options(
            selectinload(Match.player1),
            selectinload(Match.player2),
            selectinload(Match.winner),
        )
        .order_by(Match.round_number, Match.match_number)
    )
    matches = matches_result.scalars().all()

    # Shared with the schedule router so the two surfaces can never show
    # different scores for the same match. See sofascore_live.live_point_for.
    from app.services.sofascore_live import live_point_for

    def _player_out(p: DrawEntry) -> DrawEntryOut:
        out = DrawEntryOut.model_validate(p)
        # te_slug comes directly from draw_entries column now
        out.date_of_birth = te_dob_map.get(p.te_player_id) if p.te_player_id else None
        out.elo_rank = te_elo_rank_map.get(p.te_player_id) if p.te_player_id else None
        return out

    from app.services.locking import draw_lock_state, predictions_visible
    lock = await draw_lock_state(db, t)

    # Expected start times, where the order of play has named the match. One
    # query for the draw rather than one per match.
    sched = {}
    try:
        from app.models.schedule import ScheduleEntry
        srows = (await db.execute(
            select(ScheduleEntry.match_id, ScheduleEntry.expected_start_at,
                   ScheduleEntry.expected_source, ScheduleEntry.court)
            .where(ScheduleEntry.draw_id == t.id,
                   ScheduleEntry.match_id.isnot(None)))).all()
        sched = {r[0]: r for r in srows}
    except Exception:
        # A schedule is a bonus on this page, never a reason for the draw to
        # fail to load.
        sched = {}

    match_outs = []
    for m in matches:
        sm = sched.get(m.id)
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
            live_scores=m.live_scores_json,
            live_point=live_point_for(m),
            locked=m.id in lock.locked_match_ids,
            # Stamped UTC: SQLite returns these naive, and an ISO string with
            # no zone is parsed by the browser as LOCAL time.
            expected_start_at=(
                (sm[1] if sm[1] is None or sm[1].tzinfo else sm[1].replace(tzinfo=timezone.utc))
                if sm else None),
            expected_source=(sm[2] if sm else None),
            court=(sm[3] if sm else None),
        ))

    # The raw `status` column only ever holds upcoming/active/completed — "open"
    # is purely computed (see Draw.computed_status), and the frontend's every
    # `status === 'open'` check depends on the override reaching it.
    #
    # NEITHER OF THESE IS ASSIGNED TO THE ROW. Writing to a loaded ORM row marks
    # it dirty, and the next query in the session autoflushes it as a real
    # UPDATE — which is how this GET came to hold a write lock:
    #
    #   OperationalError on GET /tournaments/121/draw ... database is locked
    #   [SQL: UPDATE draws SET status=? WHERE draws.id = ?]  ('open', 121)
    #
    # The old defence was to assign only AFTER every query. It read as safe and
    # was not: `predictions_visible` sits inside the return below and queries,
    # so the flush happened anyway. Ordering cannot hold a rule like this —
    # anything added later, at any depth, brings it straight back. Set on the
    # RESPONSE instead, where there is nothing to flush.
    hidden = not await predictions_visible(db, t)
    return DrawOut(
        tournament=TournamentOut.model_validate(t).model_copy(update={
            "status": t.computed_status,
            "latest_result_at": max(
                (m.completed_at for m in matches if m.completed_at), default=None),
        }),
        draw_entries=[_player_out(p) for p in players],
        matches=match_outs,
        lock_mode=lock.mode,
        draw_locked=lock.draw_locked,
        lock_reason=lock.reason,
        predictions_hidden=hidden,
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

    t = await db.get(Draw, tournament_id)
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
    t = await db.get(Draw, tournament_id)
    if not t:
        raise HTTPException(404, "Tournament not found")
    t.selections_unlocked = not t.selections_unlocked
    await db.commit()
    await db.refresh(t)
    return t


# ---------------------------------------------------------------------------
# Internal scrape helper
# ---------------------------------------------------------------------------

async def _do_scrape(tournament: Draw, db: AsyncSession, force_refresh: bool = False) -> None:
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
    if parsed.wiki_page_id and parsed.wiki_page_id != tournament.wiki_page_id:
        # Either first-time resolution (was None) or a correction from the scraper's
        # wrong-page retry (stored ID pointed to e.g. the general event page).
        clash = await db.execute(
            select(Draw.id).where(
                Draw.wiki_page_id == parsed.wiki_page_id,
                Draw.id != tournament.id,
            )
        )
        clash_id = clash.scalar_one_or_none()
        if clash_id is not None:
            # The fetched page IS another record's page (page_ids are unique) —
            # applying its draw data here would pollute this tournament with
            # another event's players/matches (this happened: Hamburg (F)
            # ingested the men's May draw via a title-variant probe). Abort.
            from app.services.system_log import app_log
            await app_log(
                "warning", "scraper",
                f"Scrape for {tournament.year} {tournament.name} ({tournament.gender}) "
                f"resolved to page_id {parsed.wiki_page_id}, which belongs to "
                f"tournament {clash_id} — not applying foreign page data",
                {"tournament_id": tournament.id, "tournament_name": tournament.name,
                 "wiki_title": tournament.wiki_page_title,
                 "resolved_page_id": parsed.wiki_page_id, "owner_tournament_id": clash_id},
                dedup_key=f"foreign_page_{tournament.id}", dedup_hours=6.0,
            )
            return
        if tournament.wiki_page_id is not None:
            logger.warning(
                "Correcting wiki_page_id for %s: %s → %s (wrong page was stored)",
                tournament.wiki_page_title, tournament.wiki_page_id, parsed.wiki_page_id,
            )
        tournament.wiki_page_id = parsed.wiki_page_id
    if parsed.resolved_title:
        # Guard against UNIQUE violation if another record already claims this resolved title.
        # This can happen when the discovery service uses a slightly different title variant
        # (e.g. "– Women's singles" vs "– Singles") for a tournament already in the DB.
        title_clash = await db.execute(
            select(Draw.id).where(
                Draw.wiki_page_title == parsed.resolved_title,
                Draw.id != tournament.id,
            )
        )
        if title_clash.scalar_one_or_none() is None:
            logger.info("Correcting wiki_page_title for %s: %r → %r",
                        tournament.name, tournament.wiki_page_title, parsed.resolved_title)
            tournament.wiki_page_title = parsed.resolved_title
        else:
            logger.warning(
                "Resolved title %r already owned by another record; "
                "keeping %r for tournament %d",
                parsed.resolved_title, tournament.wiki_page_title, tournament.id,
            )

    if parsed.draw_size:
        tournament.draw_size = parsed.draw_size
    if parsed.num_rounds:
        tournament.num_rounds = parsed.num_rounds
    # last_scraped_at IS STAMPED AT THE EXITS, NOT HERE. Assigning it this
    # early made it the first write of a ~600-line transaction, and the very
    # next SELECT autoflushed it — so the scrape took SQLite's single write
    # lock before it had anything to write and held it across everything that
    # follows, including the entry and match upserts and the pick fill. Every
    # other background writer queued behind that, and when the lock went the
    # other way the whole scrape died on "UPDATE draws SET last_scraped_at".
    # Stamping at the exits keeps the write window to the commit itself.

    # Update location from infobox if not already set
    if parsed.city and not tournament.city:
        tournament.city = parsed.city
    if parsed.country and not tournament.country:
        tournament.country = parsed.country

    # Venue timezone and day-1 start hour, which closing_time is computed from
    # below. The deadline itself is NOT derived here: it is a function of
    # start_date, and start_date is corrected a few lines further down — doing
    # it here computed every deadline from the date we were about to replace.
    from app.services.tournament_schedule import (
        apply_learned_start, apply_schedule, sync_closing_time,
    )
    apply_schedule(tournament)
    # Prefer an observed start hour over the curated table's guess — this draw's
    # own, if ESPN has published its order of play, else a previous edition of
    # the same event. Runs BEFORE the deadline is derived below, because that
    # derivation is what consumes the hour.
    if await apply_learned_start(db, tournament):
        logger.info("Learned day-1 start for %s %s: %02d:%02d local",
                    tournament.year, tournament.name,
                    tournament.day1_start_hour or 0, tournament.day1_start_minute or 0)

    # Authoritative dates from the tournament's own infobox (general Wikipedia page).
    # If the general page parse failed, snap whatever date we have to Monday —
    # schedule pages can include qualifying days which shift the date by 1-2 days.
    # Skip date updates once the tournament is active/completed: qualifying can
    # start a day before the Wikipedia-reported date, and Wikipedia lags real play.
    if tournament.status not in ("active", "completed"):
        if parsed.start_date:
            tournament.start_date = parsed.start_date
        elif tournament.start_date:
            tournament.start_date = snap_to_monday(tournament.start_date)
        if parsed.end_date:
            tournament.end_date = parsed.end_date

    # Now that start_date is settled, derive the deadline from it. Re-derived on
    # every scrape rather than filled once, so a date correction carries the
    # deadline with it instead of leaving one pinned to the date it replaced.
    if sync_closing_time(tournament):
        logger.info(
            "Set closing_time for %s %s: %s (start %s, tz=%s %02d:%02d local)",
            tournament.year, tournament.name, tournament.closing_time,
            tournament.start_date, tournament.venue_timezone,
            tournament.day1_start_hour or 0, tournament.day1_start_minute or 0,
        )

    # Record actual draw release dates when detected.
    # Only stamp draw_released_direct_at once the draw is substantially complete
    # (≥50% of non-Q/LL slots — generous threshold to avoid missing real draws).
    # A page with only a handful of seeded players is not a released draw.
    da_players = [p for p in parsed.players if p.name and p.entry_type not in ("Q", "LL")]
    # Q/LL placeholders (named or unnamed) occupy fixed slots that will never be
    # filled by DA players, so subtract them before applying the 85% threshold.
    q_ll_count = sum(1 for p in parsed.players if p.entry_type in ("Q", "LL"))
    effective_da_size = max(tournament.draw_size - q_ll_count, 0)
    draw_substantially_complete = (
        tournament.draw_size > 0 and len(da_players) >= effective_da_size * 0.50
    )
    # Don't stamp draws for tournaments that are more than 60 days out — Wikipedia
    # sometimes has complete draws for far-future events (e.g. Dec/Jan crossover tournaments)
    # and we don't want to notify months early.
    # Use start_date if available, fall back to end_date (which is always more reliable
    # for year-crossover events like Auckland Dec 29 - Jan 5).
    ref_date = tournament.start_date or tournament.end_date
    days_until = (ref_date - date.today()).days if ref_date else 0
    too_far_future = ref_date is not None and days_until > 60

    # --- Publication signal: has the draw ceremony actually happened? ---------
    # Named UNSEEDED players holding bracket slots is the earliest honest
    # evidence. Seeded players alone are not: editors place seeds into their
    # slots as soon as the entry list is announced, days before Round-1 pairings
    # exist — the same false positive the 50% threshold above guards against.
    # An unseeded name can only come from a real draw.
    #
    # This is recorded separately from draw_released_direct_at because the two
    # answer different questions. draw_released_direct_at asks "is the page
    # complete enough to play from" (it gates picks and the release email, and
    # 50% is the right bar for that). bracket_first_seen asks "when was the draw
    # published", which is what next season's estimate must be built from.
    # Learning from the completeness threshold instead made every prediction a
    # measure of Wikipedia editor pace, and the daily scraper then only started
    # polling once that late prediction arrived — so the estimate could never
    # discover it was wrong.
    unseeded_named = [p for p in da_players if p.seed is None]
    bracket_published = len(unseeded_named) >= BRACKET_PUBLISHED_MIN_UNSEEDED
    if bracket_published and tournament.bracket_first_seen_at is None and not too_far_future:
        tournament.bracket_first_seen_at = date.today()
        if tournament.start_date:
            tournament.bracket_first_seen_days_before = (tournament.start_date - date.today()).days
        logger.info("Tournament %s: Bracket first seen on %s (%d unseeded players placed, %s days before start)",
                    tournament.wiki_page_title, date.today(), len(unseeded_named),
                    tournament.bracket_first_seen_days_before)
    elif not bracket_published and tournament.bracket_first_seen_at is not None \
            and tournament.status not in ("active", "completed"):
        # Signal retracted (page blanked, bad parse, vandalism) before play began —
        # drop the observation rather than feed a phantom date into the estimator.
        tournament.bracket_first_seen_at = None
        tournament.bracket_first_seen_days_before = None
        logger.info("Tournament %s: Clearing bracket-first-seen (%d unseeded players now present)",
                    tournament.wiki_page_title, len(unseeded_named))

    if parsed.has_direct_draw and draw_substantially_complete:
        if not tournament.draw_released_direct_at and not too_far_future:
            tournament.draw_released_direct_at = date.today()
            # First time we've observed a substantially-complete draw — start the
            # stability clock. The "draw released" email only fires once this has
            # held for a cooldown (_notify_pending_draw_releases in scheduler.py),
            # so a same-day revert (below) never results in an email having gone out.
            tournament.draw_release_detected_at = datetime.now(timezone.utc)
            if tournament.start_date:
                tournament.da_days_before = (tournament.start_date - date.today()).days
            logger.info("Tournament %s: Direct acceptance draw released on %s (%d players, %s days before start)",
                       tournament.wiki_page_title, date.today(), len(da_players),
                       tournament.da_days_before)
    elif tournament.draw_released_direct_at and not draw_substantially_complete \
            and tournament.status not in ("active", "completed"):
        # Draw was stamped prematurely (e.g. only seeds visible) — revert until complete.
        # da_days_before goes with it: the observation it recorded has been retracted,
        # and leaving it set means the next stamp silently overwrites it with a later,
        # smaller value, so every flicker drags this category's history downward.
        tournament.draw_released_direct_at = None
        tournament.draw_release_detected_at = None
        tournament.da_days_before = None
        logger.info("Tournament %s: Clearing premature draw release (%d/%d players present)",
                   tournament.wiki_page_title, len(da_players), tournament.draw_size)

    if parsed.has_qualifiers and not tournament.draw_released_qualifiers_at:
        tournament.draw_released_qualifiers_at = date.today()
        if tournament.start_date:
            tournament.qual_days_before = (tournament.start_date - date.today()).days
        logger.info("Tournament %s: Qualifiers added on %s (%s days before start)",
                   tournament.wiki_page_title, date.today(), tournament.qual_days_before)

    # If final match has a winner, tournament is completed regardless of current date
    if parsed.has_final_winner:
        if tournament.status != "completed" and tournament.start_date \
                and (tournament.start_date - date.today()).days > 30:
            # A finished bracket for an event supposedly >30 days away means the
            # stored dates point at the wrong edition (Dec/Jan season openers were
            # once stamped a year forward) — surface the contradiction.
            from app.services.system_log import app_log
            await app_log(
                "warning", "scraper",
                f"{tournament.name} {tournament.year} completed but start_date "
                f"{tournament.start_date} is >30 days in the future — dates likely wrong",
                {"draw_id": tournament.id, "start_date": str(tournament.start_date),
                 "wiki_page_title": tournament.wiki_page_title},
                dedup_key=f"future_completed_{tournament.id}", dedup_hours=168,
            )
        tournament.status = "completed"
        logger.info("Tournament %s marked as completed (final match has winner)", tournament.wiki_page_title)

    # Load existing players and matches indexed for upsert
    existing_players_res = await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == tournament.id)
    )
    existing_players: dict[int, DrawEntry] = {
        p.bracket_position: p for p in existing_players_res.scalars()
    }
    existing_matches_res = await db.execute(
        select(Match).where(Match.draw_id == tournament.id)
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

    # Once a draw has been ANNOUNCED, a name changing at a bracket position is
    # news: somebody withdrew and a lucky loser took the slot, or a qualifier was
    # finally placed. People have picked from that bracket and their picks follow
    # the slot silently, so they are told (see _notify_pending_draw_changes).
    #
    # The gate is draw_release_notified_at, not draw_released_direct_at. A draw
    # is stamped released at 50% of its slots and the release email waits out a
    # stability cooldown after that — in between, editors are still transcribing
    # the bracket, and every name they type would otherwise look like a swap.
    # After the announcement there is no such churn: the page is complete, and a
    # change to it is a change to the real draw.
    # Play having started closes the window entirely. A field is settled once the
    # first main-draw ball is struck: withdrawals become walkovers and
    # retirements, which change a RESULT, never who is in the bracket. So an
    # active draw whose parse disagrees about a player is not reporting a
    # transfer, it is a bad parse — and is handled as one below rather than
    # written in and announced.
    play_started = (
        tournament.picks_locked_at is not None
        or tournament.status in ("active", "completed")
    )

    # Once a draw has been ANNOUNCED and before play begins, a name changing at a
    # bracket position is news: somebody withdrew and a lucky loser took the
    # slot, or a qualifier was finally placed. People have picked from that
    # bracket and their picks follow the slot silently, so they are told (see
    # _notify_pending_draw_changes).
    #
    # The gate is draw_release_notified_at, not draw_released_direct_at. A draw
    # is stamped released at 50% of its slots and the release email waits out a
    # stability cooldown after that — in between, editors are still transcribing
    # the bracket, and every name they type would otherwise look like a swap.
    # After the announcement there is no such churn: the page is complete, and a
    # change to it is a change to the real draw.
    # The test is per MATCH, not per draw.
    #
    # "A pick cannot be replaced after a first-round match occurs" is a fact
    # about THAT match, not about the tournament: a draw is in play from its
    # first ball, but most of its first round has not started yet, and both
    # withdrawals and qualifier placements go on landing for hours afterwards.
    # Gating on the draw silenced every one of them — 2026 Cincinnati filled all
    # twelve qualifier slots after its first ball and nobody was told.
    #
    # So a change is news while the slot's own match is still to come, and is
    # ignored once that match is under way or over, where it can only be a
    # correction to something already played.
    announced = tournament.draw_release_notified_at is not None
    started_entry_ids: set[int] = set()
    for (rnd, _num), em in existing_matches.items():
        if rnd != 1:
            continue
        if em.winner_id is not None or em.live_scores_json is not None or em.status == "completed":
            started_entry_ids.update(x for x in (em.player1_id, em.player2_id) if x)
    pending_changes: list[dict] = []

    # --- Reject a shifted parse before it is written -------------------------
    #
    # 2026 Canadian Open, mid-quarter-finals: one scrape parsed the page with one
    # fewer 16-team section than the next, so section_index shifted and every
    # slot from 49 up received the player 16 positions below it. Sixteen entries
    # were rewritten, then rewritten back five minutes later, and everyone
    # competing was told their picks had changed — twice, in opposite directions.
    #
    # The notification was the visible half. The damage is that this rewrites
    # DrawEntry rows that predictions point at AND the player ids on every match,
    # so a shifted parse silently re-points picks and mis-pairs matches in a
    # tournament that is already being scored.
    #
    # A correct parse of a draw in play agrees with the stored field exactly, so
    # any real disagreement condemns the whole parse: nothing from it is applied,
    # and the next scrape (30 min, or sooner via EventStreams) retries. Judged
    # with classify_change so a restored diacritic or an expanded initial — the
    # same tidying draw_changes already knows how to ignore — is not mistaken for
    # a shift and does not block a legitimate scrape forever.
    if play_started:
        # Qualifier slots are exempt. They are the one part of the field that
        # legitimately changes late — a lucky loser stepping in, or Wikipedia
        # replacing a name espn_monitor filled from the order of play while the
        # bracket still said "Q/LL". Treating one of those as corruption would
        # discard every scrape of that draw for the rest of the tournament,
        # taking the results with it.
        #
        # It costs the guard nothing: the failure it exists for is a whole
        # section shifting by sixteen positions, which moves seeds and direct
        # entrants in bulk. A shift that touched only qualifier slots is not a
        # shift.
        LATE_ENTRY_TYPES = ("Q", "LL", "ALT", "SE", "PR")
        misparsed = [
            (pe.bracket_position, existing_players[pe.bracket_position].name, pe.name)
            for pe in parsed.players
            if pe.bracket_position in existing_players
            and (existing_players[pe.bracket_position].entry_type or "").upper() not in LATE_ENTRY_TYPES
            and (pe.entry_type or "").upper() not in LATE_ENTRY_TYPES
            and classify_change(existing_players[pe.bracket_position].name, pe.name) == "replaced"
        ]
        # A COUNT, not a presence test. The fault this guards against is a whole
        # 16-slot section shifting, which rewrites entrants in bulk; one player
        # changing is a withdrawal, which is a real thing that happens mid-draw
        # and must be applied and announced, not discarded as corruption. Three
        # is comfortably above any single legitimate swap and far below a shift.
        if len(misparsed) >= 3:
            from app.services.system_log import app_log
            await app_log(
                "error", "scraper",
                f"Discarded a scrape of {tournament.year} {tournament.name} "
                f"({'ATP' if tournament.gender == 'M' else 'WTA'}): {len(misparsed)} player(s) "
                f"disagree with the field of a draw already in play — treating as a bad parse",
                {"draw_id": tournament.id, "count": len(misparsed),
                 "sample": [f"pos {p}: {old} → {new}" for p, old, new in misparsed[:6]],
                 "wiki_page_title": tournament.wiki_page_title},
                dedup_key=f"misparse_{tournament.id}", dedup_hours=6.0,
            )
            # Stamped even though the scrape is being abandoned: this bails
            # BECAUSE the page is wrong, and leaving the draw unstamped would
            # re-fetch and re-fail it on every tick.
            tournament.last_scraped_at = datetime.now(timezone.utc)
            return

    # Upsert players — update in place to preserve any FK references
    pos_to_player_id: dict[int, int] = {}
    seen_positions: set[int] = set()
    upserted_players: list[DrawEntry] = []
    for pe in parsed.players:
        seen_positions.add(pe.bracket_position)
        if pe.bracket_position in existing_players:
            player = existing_players[pe.bracket_position]
            if player.name != pe.name:
                # Captured BEFORE the overwrite — one line later the old name
                # is gone and there is nothing left to diff against.
                kind = classify_change(player.name, pe.name)
                if kind and announced and tournament.status != "completed" \
                        and player.id not in started_entry_ids:
                    pending_changes.append({
                        "entry_id": player.id,
                        "bracket_position": pe.bracket_position,
                        "kind": kind,
                        "old_name": player.name or None,
                        "new_name": pe.name,
                        "old_entry_type": player.entry_type,
                        "new_entry_type": pe.entry_type,
                        "old_seed": player.seed,
                    })
                # Name changed (withdrawal/replacement) — re-match on next
                # assign_rankings. The slug has to go with the id: left behind,
                # it points the H2H panel at the player who was replaced.
                player.te_player_id = None
                player.te_slug = None
                # And the Sofascore id goes with them, for the worse version
                # of the same reason: a stale one does not just mislabel a
                # panel, it makes the live poller require BOTH sides to match
                # and silently skip the match — Gorzny played on Stadium Court
                # carrying Prizmic's id, and his match recorded no history and
                # showed no points. The resolver re-stamps within the hour.
                player.sofa_player_id = None
            player.name = pe.name
            player.nationality = pe.nationality
            player.seed = pe.seed
            player.entry_type = pe.entry_type
        else:
            player = DrawEntry(
                draw_id=tournament.id,
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

    # Retry unresolved players even when the roster is unchanged. Skipping the
    # whole pass on "no roster change" meant a player who couldn't be matched at
    # the moment they entered the draw stayed unmatched forever — nothing ever
    # looked at them again unless someone else's name happened to change. Now
    # the 30-min sweep keeps re-trying, so a player TE hadn't published yet, or
    # one whose profile lookup lost to rate limiting, resolves on its own.
    # assign_rankings only touches players with te_player_id IS NULL, so this
    # costs one index load and nothing else once everyone is matched.
    unresolved = [p for p in upserted_players if p.te_player_id is None]
    if roster_changed or unresolved:
        try:
            ref_date = tournament.entry_ranking_week or tournament.start_date or date.today()
            await assign_rankings(upserted_players, tournament.gender, ref_date, db)
            if roster_changed:
                logger.info("Roster change in %s — rankings assigned", tournament.name)
            else:
                still = sum(1 for p in upserted_players if p.te_player_id is None)
                logger.info("%s: retried %d unresolved player(s), %d still unresolved",
                            tournament.name, len(unresolved), still)
        except Exception as exc:
            logger.warning("Could not assign rankings for %s: %s", tournament.name, exc)

    # Delete players no longer in the draw — but NEVER once it is in play.
    #
    # A position vanishing from a parse is not a player leaving the draw. Nobody
    # leaves a draw that has started; they withdraw and it becomes a walkover,
    # and the slot keeps its name. So an absent position is a partial parse, and
    # deleting on it destroys a row that predictions point at.
    #
    # That is what happened to 2026 Cincinnati (WTA): positions 81-95 dropped out
    # of one parse, ten entries were deleted and recreated with new ids on the
    # next, and 57 picks across five players were left pointing at ids that no
    # longer existed — brackets that rendered blank. The misparse guard above did
    # not catch it because it compares NAMES, and these positions had no name to
    # compare; they were simply absent.
    missing_positions = [pos for pos in existing_players if pos not in seen_positions]
    if missing_positions and play_started:
        # Deferred, not awaited. This sits inside _do_scrape's write transaction
        # — entries have already been flushed — and app_log opens its own
        # session, so awaiting it here deadlocks on SQLite's write lock and the
        # refusal is swallowed as "database is locked". The scheduler commits
        # immediately after this returns, so the task lands a moment later.
        import asyncio as _asyncio
        from app.services.system_log import app_log
        _asyncio.create_task(app_log(
            # A refusal is the guard WORKING, and Wikipedia is edited live, so a
            # momentary partial parse is an expected state rather than a fault:
            # the next scrape restores it and nothing was lost. Raised as a
            # warning so it stays visible without implying there is something to
            # do — an error here paged for a draw that had already healed.
            # Persistence is the real signal, and a repeat every 6 hours reads as
            # exactly that.
            "warning", "scraper",
            f"Ignored a parse of "
            f"{tournament.year} {tournament.name} "
            f"({'ATP' if tournament.gender == 'M' else 'WTA'}) that dropped "
            f"{len(missing_positions)} entrant(s): the draw is in play, so an absent "
            f"position is a bad parse and not a withdrawal. Nothing was deleted and "
            f"the next scrape restores it",
            {"draw_id": tournament.id, "positions": sorted(missing_positions)[:20],
             "count": len(missing_positions)},
            dedup_key=f"refused_entry_delete_{tournament.id}", dedup_hours=6.0,
        ))
        logger.warning("Ignored a parse of %s %s that dropped %d entrant(s)",
                     tournament.year, tournament.name, len(missing_positions))
    else:
        for pos in missing_positions:
            await db.delete(existing_players[pos])
    await db.flush()

    # Queue the swaps for notification. Written in the same transaction as the
    # entry rows they describe, so a scrape that rolls back cannot leave an
    # event announcing a change the draw never took.
    #
    # A vacated position is deliberately NOT recorded: a bracket_position
    # vanishing means the draw was restructured (a size correction, a bad
    # parse), not that a player was replaced, and the player who eventually
    # takes that slot arrives as an ordinary change on a later scrape.
    if pending_changes:
        from app.models.notification import DrawChangeEvent
        # ONE EVENT PER CHANGE, however many times the scrape re-sees it.
        #
        # The dispatcher waits for a draw to stop moving — 90 minutes of quiet
        # for a qualifier field — and measures that from the newest unnotified
        # event. So a change recorded again on every scrape pushes the deadline
        # forward every scrape and the announcement never goes out. Winston
        # Salem's five qualifiers were recorded 33 times between 20:06 and
        # 20:32 and nobody was ever told they had been placed.
        #
        # A slot that flaps — filled, blank, filled, as a page is edited or a
        # parse wobbles — is exactly when this matters, and exactly when the
        # naive version fails. Matching on the entry and the name it landed on
        # means re-seeing the same outcome is free, while a genuinely new
        # outcome still resets the clock, which is what the clock is for.
        already = {
            (e.entry_id, e.new_name)
            for e in (await db.execute(
                select(DrawChangeEvent).where(
                    DrawChangeEvent.draw_id == tournament.id,
                    DrawChangeEvent.notified_at.is_(None),
                ))).scalars().all()
        }
        pending_changes = [c for c in pending_changes
                           if (c["entry_id"], c["new_name"]) not in already]
    if pending_changes:
        for c in pending_changes:
            db.add(DrawChangeEvent(draw_id=tournament.id, **c))
        from app.services.system_log import app_log
        await app_log(
            "info", "scraper",
            f"{len(pending_changes)} draw change(s) detected in "
            f"{tournament.year} {tournament.name} ({tournament.gender})",
            {"draw_id": tournament.id,
             "changes": [f"{c['old_name'] or '(empty)'} → {c['new_name']}" for c in pending_changes]},
        )

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
            match.player1_id = p1_id
            match.player2_id = p2_id
            match.is_bye = mr.is_bye
            if w_id is not None:
                # Wikipedia has a result — always trust it (includes tiebreak scores)
                if match.winner_id != w_id:
                    # Only stamp completed_at if ESPN hasn't already recorded it;
                    # ESPN timestamps are more accurate (per-match, within 1 min).
                    if match.completed_at is None:
                        match.completed_at = datetime.now(timezone.utc)
                match.winner_id = w_id
                match.status = "completed"
                match.scores_json = mr.scores
                match.live_scores_json = None
            elif match.winner_id is None:
                # No result from either source — update scores/status normally
                match.completed_at = None
                match.scores_json = mr.scores
                match.status = "pending"
        else:
            match = Match(
                draw_id=tournament.id,
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

    # Delete matches no longer in the draw, and the predictions on them — again,
    # never once the draw is in play. This one deletes PICKS outright rather than
    # merely orphaning them, so a partial parse here is unrecoverable without a
    # backup. A bracket does not lose matches after it starts.
    from app.models.prediction import UserPrediction
    missing_matches = [k for k in existing_matches if k not in seen_match_keys]
    if missing_matches and play_started:
        # Deferred, not awaited. This sits inside _do_scrape's write transaction
        # — entries have already been flushed — and app_log opens its own
        # session, so awaiting it here deadlocks on SQLite's write lock and the
        # refusal is swallowed as "database is locked". The scheduler commits
        # immediately after this returns, so the task lands a moment later.
        import asyncio as _asyncio
        from app.services.system_log import app_log
        _asyncio.create_task(app_log(
            "warning", "scraper",
            f"Ignored a parse of "
            f"{tournament.year} {tournament.name} "
            f"({'ATP' if tournament.gender == 'M' else 'WTA'}) that dropped "
            f"{len(missing_matches)} match(es): the draw is in play, and deleting them "
            f"would have deleted the predictions on them. Nothing was deleted",
            {"draw_id": tournament.id, "count": len(missing_matches),
             "rounds": sorted({r for r, _ in missing_matches})},
            dedup_key=f"refused_match_delete_{tournament.id}", dedup_hours=6.0,
        ))
        logger.warning("Ignored a parse of %s %s that dropped %d match(es)",
                     tournament.year, tournament.name, len(missing_matches))
    else:
        for key in missing_matches:
            old_match = existing_matches[key]
            orphaned = await db.execute(
                select(UserPrediction).where(UserPrediction.match_id == old_match.id)
            )
            for pred in orphaned.scalars():
                await db.delete(pred)
            await db.delete(old_match)

    # Auto-set tournament status
    from datetime import date as _date
    today = _date.today()
    total_matches = len(parsed.matches)
    completed = sum(1 for m in parsed.matches if m.winner_position is not None)

    # Byes resolve the instant the draw is released — no match is actually
    # played — so they must NOT count as "activity" or the tournament would
    # show active/started before a single real match has begun (any draw with
    # first-round byes for top seeds hits this immediately on release).
    real_completed = sum(1 for m in parsed.matches if m.winner_position is not None and not m.is_bye)

    # Snap start_date to today on first detected REAL match activity.
    # Qualifying rounds begin before the Wikipedia-reported main-draw start date,
    # so use the real play date rather than Wikipedia's potentially lagging value.
    # Guard: only snap after the main draw is released — otherwise qualifying activity
    # would prematurely move the start_date forward by a week or more.
    has_activity = real_completed > 0 or any(m.scores for m in parsed.matches if not m.is_bye)
    if (has_activity and tournament.start_date and today < tournament.start_date
            and tournament.draw_released_direct_at is not None):
        tournament.start_date = today

    started = tournament.start_date is None or tournament.start_date <= today
    if completed == total_matches and completed > 0:
        tournament.status = "completed"
    elif real_completed > 0 and started:
        tournament.status = "active"
    else:
        tournament.status = "upcoming"

    # NO ENTRANT'S BRACKET IS LEFT WITH A HOLE IN IT.
    #
    # Every unpicked match defaults to the better-ranked player, and this is one
    # of the two moments a hole can appear — not because anybody picked or
    # failed to pick, but because the DRAW changed underneath them. A slot that
    # was an unnamed qualifier when they entered had nobody to advance and was
    # skipped; once the qualifier is named there is.
    #
    # ONLY WHEN THE BRACKET ACTUALLY CHANGED. Running this on every scrape put
    # ~7 entrants x a 127-match bracket inside the scrape's own write
    # transaction, four draws in a row: the refresh went to 81 seconds, and
    # Cincinnati's failed outright on "database is locked" trying to stamp its
    # own last_scraped_at while every other background writer queued behind it.
    # A draw whose entrants are already complete has nothing to fill, and
    # pending_changes is precisely the signal that a name moved.
    #
    # The rows are read ONCE and shared across entrants — they are the same
    # every time, and re-reading them per user was most of the cost.
    #
    # A locked draw is left alone: its brackets are final, and adding picks to
    # one after the fact would be inventing entries nobody made.
    if pending_changes and not tournament.is_locked:
        from app.models.prediction import UserPrediction
        from app.services.highest_rank_bot import fill_missing_picks
        await db.flush()
        entrants = (await db.execute(
            select(UserPrediction.user_id)
            .where(UserPrediction.draw_id == tournament.id).distinct())).scalars().all()
        if entrants:
            fill_entries = (await db.execute(
                select(DrawEntry).where(DrawEntry.draw_id == tournament.id))).scalars().all()
            fill_matches = (await db.execute(
                select(Match).where(Match.draw_id == tournament.id))).scalars().all()
            for entrant_id in entrants:
                await fill_missing_picks(db, tournament, entrant_id,
                                         entries=fill_entries, matches=fill_matches)

    # The scrape got here, so it worked. Last write before the caller's
    # commit — see the note where this used to be stamped.
    tournament.last_scraped_at = datetime.now(timezone.utc)

