import time
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user, get_optional_user
from app.database import get_db
from app.models.prediction import UserPrediction
from app.models.rankings import TePlayer, TeRankingsSnapshot
from app.models.tournament import DrawEntry, Match, Draw, Tournament, default_short_name
from app.services.events import attach
from app.models.user import User
from app.schemas.league import LeaderboardEntry, LeagueTournamentOut
from app.schemas.tournament import DrawEntryOut, DrawOut, MatchOut, TournamentCreate, TournamentOut
from app.schemas.user import UserPublicOut
from app.services.draw_changes import classify_change
from app.services import final_tiebreak
from app.services.rankings import assign_rankings, assign_seed_week_rankings
from app.services.scraper import scrape_tournament, snap_to_monday
from app.services.scoring import (UserScore, _points_table, enumerate_worlds, finish_history_async,
                                  finish_range_async, chances_available, chances_fingerprint,
                                  chances_sampled, podium_locked, rank_users)
from app.services.win_chances import ATTRIBUTION as ODDS_ATTRIBUTION, draw_odds
from app.services.scoring import potential_points
from app.services.upsets import has_upset_pick

router = APIRouter(prefix="/tournaments", tags=["tournaments"])

# How many named unseeded players must hold bracket slots before we accept that
# the draw has actually been made (see the publication-signal block in
# _do_scrape). Small on purpose — the point is to catch publication early, and
# unseeded names cannot appear from a seeds-only entry-list placement. Kept
# above 1 so a single stray wildcard or parse artefact can't trip it.
BRACKET_PUBLISHED_MIN_UNSEEDED = 4


def _wikipedia_may_decide(mr) -> bool:
    """THE ONE GATE on Wikipedia deciding anything about a match's outcome.

    Wikipedia supplies the draw's SHAPE — players, positions, seeds, entry
    types — and never a result. "NEVER, EVER, use Wikipedia for a match result
    or score. EVER AGAIN. Sofascore only, and only when necessary, ESPN."
    (owner, 2026-09-16, after Guadalajara's four quarter-finals showed winners
    before any had been played: bold markup read as a result, and a lone
    occupant read as a bye.)

    The single exception is a FIRST-ROUND BYE, and it is an exception because
    it is shape, not result: a seed placed opposite nothing on the sheet has
    no match for Sofascore or ESPN to ever report. The parser only sets
    `is_bye` in round one now (scraper.py), so this is exactly that case.
    """
    return bool(mr.is_bye)


# HOW LONG WIKIPEDIA MAY BE AHEAD OF SOFASCORE before it is worth a row in
# /issues. Being ahead is the ordinary state for a few minutes after most
# matches: an edit triggers a scrape within seconds (eventstream), while the
# results sweep runs every three minutes and reads walkovers declared ahead of
# their slot every fifteen (sofascore_results.NEXT_INTERVAL). Guadalajara
# 2026-09-16 warned two minutes into exactly that window. Past this, the claim
# is a real question — an unmapped event, or an edit that is wrong.
WIKI_CLAIM_GRACE = 30 * 60
# match id -> monotonic first sighting of the claim. In process memory, like
# app_log's dedup: a restart restarts the clock, which delays a warning and
# never invents one.
_wiki_claim_seen: dict[int, float] = {}


def _wiki_claim_overdue(match_id: int, now: Optional[float] = None) -> bool:
    """Record a sighting of an unapplied Wikipedia result; True once it has
    outlasted WIKI_CLAIM_GRACE."""
    now = time.monotonic() if now is None else now
    return now - _wiki_claim_seen.setdefault(match_id, now) >= WIKI_CLAIM_GRACE


def _clear_phantom(match: Match) -> bool:
    """Undo a stored result that no source can vouch for.

    Only fires when the stored winner has NO score and NO Sofascore backing —
    the shape only a Wikipedia-derived winner can leave. A real result always
    has one of those, so nothing genuine is touched; the branch is a no-op for
    the pending row it usually meets. Scores are never restored from the
    sheet: the row goes back to bare pending.
    """
    if match.winner_id is None:
        return False
    if match.sofa_winner_id is not None:
        return False
    if match.scores_json:              # sets, "w/o", "3r" — any real outcome
        return False
    match.winner_id = None
    match.status = "pending"
    match.completed_at = None
    match.scores_json = None
    match.live_scores_json = None
    return True



async def _bot_ids(db) -> set[int]:
    """See routers.leagues._bot_ids: a bot competes but takes no place."""
    from app.models.user import User
    return set((await db.execute(select(User.id).where(User.is_bot.is_(True)))).scalars().all())


async def _log_phantom_cleared(match: Match, tournament: Draw, mr) -> None:
    """A stored result was undone. That is worth a row in /issues even though
    it is the fix working: the interesting question is why it was there."""
    try:
        from app.services.system_log import app_log
        await app_log(
            "warning", "scraper",
            f"Cleared a stored result nobody can vouch for on match {match.id} "
            f"(draw {tournament.id}, round {mr.round_number}): winner with no score "
            f"and no Sofascore backing",
            detail={"match_id": match.id, "round": mr.round_number,
                    "match_number": mr.match_number},
            dedup_key=f"scraper:phantom-cleared:{match.id}",
            dedup_hours=24.0,
        )
    except Exception:                                    # noqa: BLE001
        pass


@router.get("", response_model=list[TournamentOut])
async def list_tournaments(db: AsyncSession = Depends(get_db)):
    # Imported here, as the schedule lookup further down this file does: the
    # module-level imports in this router are the draw/prediction models, and
    # schedule is a different subsystem pulled in by the two places that need it.
    from app.models.schedule import ScheduleEntry

    lat_subq = (
        select(Match.draw_id, func.max(Match.completed_at).label("lat"))
        .group_by(Match.draw_id)
        .subquery()
    )
    # WHEN QUALIFYING BEGAN, per EVENT rather than per draw.
    #
    # Qualifying matches are not in `matches` at all — a 128 draw stores rounds
    # 1-7 and the players who fail to qualify never reach draw_entries — so the
    # schedule row IS the only record qualifying has, and `stage`
    # ("main"|"qualifying") is what names it. started_at on the row is the
    # doubles/qualifying equivalent of matches.started_at, written by the live
    # feeds because ESPN covers neither.
    #
    # KEYED ON tournament_id BECAUSE THAT IS WHOSE IT IS: qualifying rows carry
    # no draw_id, and one qualifying draw feeds both halves of a combined
    # event, so both of an event's draws report the same answer. MIN, not MAX —
    # the question is when the FIRST match started.
    qual_subq = (
        select(
            ScheduleEntry.tournament_id.label("tid"),
            func.min(ScheduleEntry.started_at).label("qual"),
        )
        .where(ScheduleEntry.stage == "qualifying", ScheduleEntry.started_at.isnot(None))
        .group_by(ScheduleEntry.tournament_id)
        .subquery()
    )
    # The EVENT's names ride along: a draw carries the scraped name, and an
    # admin's display and short names live on the tournament. Outer-joined
    # because Draw.tournament_id is nullable, and a draw with no event row
    # still gets a short name — off its own name.
    result = await db.execute(
        select(Draw, lat_subq.c.lat, qual_subq.c.qual,
               Tournament.display_name, Tournament.short_name)
        .outerjoin(lat_subq, Draw.id == lat_subq.c.draw_id)
        .outerjoin(qual_subq, Draw.tournament_id == qual_subq.c.tid)
        .outerjoin(Tournament, Tournament.id == Draw.tournament_id)
        .order_by(Draw.year.desc(), Draw.name)
    )
    rows = result.all()
    # Serialised, never assigned back. Writing to a loaded ORM row marks it
    # dirty and the next query in the session autoflushes it as a real UPDATE —
    # which is how a GET comes to hold a write lock. Both of these are computed
    # for the response and neither belongs in the column.
    return [
        TournamentOut.model_validate(t).model_copy(
            update={"status": t.computed_status, "latest_result_at": lat,
                    "qualifying_started_at": qual,
                    "tournament_short_name": (
                        (t_short or "").strip()
                        or default_short_name((t_display or "").strip() or t.name)),
                    "tournament_short_name_custom": (t_short or "").strip() or None})
        for t, lat, qual, t_display, t_short in rows
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
    # The event this draw belongs to — matched on when it is played, not on
    # its name alone. See services/events.py for what that cost when it was
    # the name and the year.
    await attach(db, t)
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
    from datetime import date
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
            # And the badge's week, which is a different one — see
            # assign_seed_week_rankings.
            await assign_seed_week_rankings(players, t.gender, t.seed_ranking_week, db)
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
            User.is_bot,
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

        # The ranking bot competes but does not PLACE: it is a yardstick, not a
        # rival, so it takes no number and displaces no one from the top five
        # (owner, 2026-09-13). Its row still appears, in points order.
        if not row.is_bot:
            ranked[tier][gender] += 1
        entry = {
            "rank": None if row.is_bot else ranked[tier][gender],
            "is_bot": bool(row.is_bot),
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

        # A bot sits wherever its points put it among the five placed rows; past
        # them it is simply off the list, like anyone else.
        if (ranked[tier][gender] < _HOF_TOP_N if row.is_bot
                else entry["rank"] <= _HOF_TOP_N):
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
    """Grand Slam point totals for every verified PERSON this year, with the
    is_admin flag.

    NOT THE BOTS. Highest_Rank picks the higher-ranked player in every match —
    it is a yardstick, and a yardstick does not belong in a leaderboard of
    people: it held the top total on the season tally, which reads as somebody
    winning (owner, 2026-09-13). It still competes in draws and still appears
    in a draw's standings, where beating it is the whole point.

    `is_bot` is the flag the notification enrolment already honours."""
    from datetime import date
    from collections import defaultdict
    from app.services.scoring import _points_table

    year = date.today().year
    gs_result = await db.execute(
        select(Draw).where(Draw.year == year, Draw.category.ilike('%grand slam%'))
    )
    gs_draws = gs_result.scalars().all()

    users_result = await db.execute(
        select(User).where(User.email_verified == True,               # noqa: E712
                           func.coalesce(User.is_bot, False) == False)  # noqa: E712
        .order_by(User.username)
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
    from app.services.locking import draw_lock_state, predictions_visible

    tournament = await db.get(Draw, tournament_id)
    if not tournament:
        raise HTTPException(404, "Tournament not found")
    # STRICTER THAN THE DRAW PAGE, DELIBERATELY. predictions_visible answers
    # "may one user see another's picks", and under draw-start locking it says
    # yes because nothing can change after the first ball. That reasoning holds
    # AFTER the lock; before it, every bracket is still editable, and a table
    # of everyone's semifinalists is a bracket to copy. So this view waits for
    # the picks to actually close: while a draw is open it shows nothing, for
    # any lock mode.
    lock = await draw_lock_state(db, tournament)
    if not lock.draw_locked and tournament.status != "completed":
        return {"hidden": True, "rounds": [], "users": []}
    if not await predictions_visible(db, tournament):
        return {"hidden": True, "rounds": [], "users": []}

    matches = (await db.execute(
        select(Match).where(Match.draw_id == tournament_id,
                            Match.is_bye == False))).scalars().all()
    if not matches:
        return {"hidden": False, "rounds": [], "users": []}
    max_round = max(m.round_number for m in matches)
    # Labelled by what the pick MEANS, not which round the match is in: the
    # winner of a quarterfinal is your predicted SEMIFINALIST, and the
    # final's winner is your champion — so the columns read QF, SF, F, W.
    #
    # QF is sent whether or not anything asks for it: the compare view's
    # depth switch chooses between the quarter-finalists and the rounds after
    # them, and paying for a second round trip to change a client-side setting
    # would be worse than the handful of extra rows this costs. Ordered
    # earliest-first so the client can render them in bracket order without
    # sorting.
    tiers = [(rn, label) for rn, label in
             ((max_round - 3, "QF"), (max_round - 2, "SF"),
              (max_round - 1, "F"), (max_round, "W"))
             if rn >= 1]
    tier_of = {rn: label for rn, label in tiers}
    late = {m.id: (tier_of[m.round_number], m.match_number)
            for m in matches if m.round_number in tier_of}

    scope_ids = None
    usernames: dict[int, str] = {}
    fullnames: dict[int, str] = {}
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
        # Real names travel ONLY when this league opted in — the flag is the
        # league's, so the gate lives here, not in any client.
        if league.show_real_name:
            fullnames = {m.user_id: m.user.full_name for m in league.members}

    stmt = (select(UserPrediction, User.username)
            .join(User, User.id == UserPrediction.user_id)
            .where(UserPrediction.draw_id == tournament_id,
                   UserPrediction.predicted_winner_id.isnot(None),
                   UserPrediction.match_id.in_(list(late))))
    rows = (await db.execute(stmt)).all()

    # The verdict on each pick, WITHOUT naming winners: green needs the pick's
    # own match decided, red only needs the picked player to have lost
    # anywhere already — a QF pick is dead the moment its player goes out in
    # R2, long before the QF exists.
    winner_of = {}
    eliminated: set = set()
    for m in matches:
        if m.status == "completed" and m.winner_id is not None:
            winner_of[m.id] = m.winner_id
            for pid in (m.player1_id, m.player2_id):
                if pid is not None and pid != m.winner_id:
                    eliminated.add(pid)

    def _state(match_id: int, picked: int) -> str:
        w = winner_of.get(match_id)
        if w is not None:
            return "correct" if w == picked else "out"
        return "out" if picked in eliminated else "open"

    # Structured, not a string: the client renders the same pos-badge the
    # draw page uses. `seed` is the real one (grey box); `implied` is the
    # draw-order rank BracketView derives for unseeded players — seeds keep
    # their number, everyone else is ordered by world ranking after the
    # highest seed number present, so withdrawn seeds cannot collide.
    all_entries = (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == tournament_id))).scalars().all()
    offset = max((e.seed for e in all_entries if e.seed is not None), default=0)
    unseeded = sorted((e for e in all_entries if e.seed is None),
                      key=lambda e: (e.ranking is None, e.ranking or 0))
    implied = {e.id: offset + i + 1 for i, e in enumerate(unseeded)}
    entry_names = {e.id: {"name": e.display_name, "seed": e.seed,
                          "implied": implied.get(e.id),
                          "entry_type": e.entry_type}
                   for e in all_entries}

    by_user: dict[int, dict] = {}
    for pred, username in rows:
        if scope_ids is not None and pred.user_id not in scope_ids:
            continue
        tier, match_number = late[pred.match_id]
        u = by_user.setdefault(pred.user_id, {
            "user_id": pred.user_id,
            "username": usernames.get(pred.user_id, username),
            "full_name": fullnames.get(pred.user_id),
            "picks": {label: [] for _, label in tiers},
        })
        name = entry_names.get(pred.predicted_winner_id)
        if name:
            u["picks"][tier].append((match_number, {
                **name, "state": _state(pred.match_id, pred.predicted_winner_id)}))

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
    from app.services.rounds import compact_round
    from app.services.schedule import _best_of
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
    draw = await db.get(Draw, match.draw_id)
    # "Prev Point: Ace". One label per snapshot, mostly null — an ace or a
    # double fault is about 8% of points and nothing else can be said about an
    # individual point (see services/sofascore_points.py). Fetched on demand,
    # one request per MATCH, and never allowed to fail the score history.
    from app.services.sofascore_points import labels_for, labels_pending
    for _snap, _label in zip(
            snapshots,
            await labels_for(snapshots, match.sofa_event_id,
                             finished=match.winner_id is not None)):
        # ON the snapshot, not a parallel array: the client drops snapshots it
        # judges to be feed corrections (sanitizeSnapshots), and an index-based
        # list would silently shift a label onto the wrong point.
        if _label:
            _snap["point_label"] = _label
    return {
        "status": match.status,
        "completed_at": match.completed_at,
        "player1_id": match.player1_id,
        "player1_name": p1.name if p1 else None,
        "snapshots": snapshots,
        "final": match.scores_json,
        # HOW LONG IT TOOK. Sofascore's figure first — it is the sum of the set
        # clocks, so a rain delay between sets is already outside it, where our
        # own is completed-minus-started and counts a suspension as tennis.
        "duration_min": match.sofa_duration_min or match.duration_min,
        # For a match still on court there is no total yet, so the client
        # counts up from here. Wall-clock by nature: what a viewer means by
        # "how long has this been going" includes the rain.
        "started_at": match.started_at or match.sofa_started_at,
        # The point labels' fetch outran the wait above and is still running:
        # the client asks again shortly, so a finished match's first open is
        # not the one open that never shows an ace.
        "labels_pending": labels_pending(match.sofa_event_id),
        # Through compact_round, not a fourth spelling of the same idea — see
        # the note at the top of services/rounds.py.
        "round_label": compact_round(draw.round_name(match.round_number))
                       if draw and match.round_number else None,
        # Sets in the match, so the timeline can tell a set point from a
        # MATCH point. The same answer the schedule plans with.
        "best_of": _best_of(draw, "singles", "main"),
    }


@router.get("/{tournament_id}/matches/{match_id}/statistics")
async def match_statistics(
    tournament_id: int,
    match_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Sofascore's serve and return figures for the Match Stats tab.

    Deliberately a SEPARATE endpoint from score-history, because the two have
    different natural cadences: the history is polled every ten seconds while
    a popup is open, whereas these numbers only move when a game ends. The
    client asks for them far less often, and the service caches per event.

    Unlike the scrubber's own statistics — which are computed from our
    snapshots and follow the slider — these have no per-point history.
    Sofascore keeps a running total per period only, so this answers "how has
    the match gone", never "how had it gone at point 47". `order` lists the
    periods it holds: `ALL` plus one per set played.

    Public, like the score history and the draw itself.
    """
    from app.services.sofascore_stats import stats_for

    match = await db.get(Match, match_id)
    if not match or match.draw_id != tournament_id:
        raise HTTPException(404, "Match not found")

    # An empty answer is normal, not an error: a match with no Sofascore event
    # id (played before the column existed, or never matched) simply has no
    # figures, and the tab says so rather than erroring.
    data = await stats_for(match.sofa_event_id,
                           finished=match.winner_id is not None)
    return {"order": data.get("order") or [],
            "periods": data.get("periods") or {},
            # Per period: is the first/second serve split obviously wrong? When
            # it is, the rows built on it are already gone from `periods` and
            # the client says why instead of drawing a blank panel.
            "split_suspect": data.get("split_suspect") or {}}


@router.get("/{tournament_id}/my-standouts")
async def my_standout_picks(
    tournament_id: int,
    # Whose bracket is being read. The draw page already lets you open somebody
    # else's, and a standout is a fact about a finished match rather than a
    # secret — if you can see their picks you can see which of them the field
    # missed. Defaults to the reader's own.
    user_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Match ids in this draw where that bracket called a result the field missed.

    Same test the standout notification used before it was retired, so the
    bracket marks exactly what used to be emailed: the reader picked the
    winner, at least STANDOUT_MIN_PREDICTIONS people predicted the match, and
    strictly fewer than half of them got it right. Strict, so a field split
    down the middle is not flattered into "you saw something they didn't".

    Computed live rather than read from standout_pick_notifications: that table
    is the notifier's claim ledger, one row per match measured once, and it
    stops being written the moment nothing schedules the measurement. The
    numbers behind it are cheap to recount from the picks themselves.
    """
    from app.services.notifications import (STANDOUT_MAX_SHARE,
                                            STANDOUT_MIN_PREDICTIONS)
    from collections import defaultdict

    if current_user is None:
        return {"match_ids": []}
    subject_id = user_id if user_id is not None else current_user.id

    rows = (await db.execute(
        select(UserPrediction.match_id, UserPrediction.user_id,
               UserPrediction.predicted_winner_id, Match.winner_id)
        .join(Match, Match.id == UserPrediction.match_id)
        .where(Match.draw_id == tournament_id,
               Match.winner_id.isnot(None),
               Match.is_bye == False,  # noqa: E712
               UserPrediction.predicted_winner_id.isnot(None))
    )).all()

    picked: dict[int, int] = defaultdict(int)
    correct: dict[int, int] = defaultdict(int)
    mine: set[int] = set()
    for match_id, uid, guess, winner in rows:
        picked[match_id] += 1
        if guess == winner:
            correct[match_id] += 1
            if uid == subject_id:
                mine.add(match_id)

    out = [mid for mid in mine
           if picked[mid] >= STANDOUT_MIN_PREDICTIONS
           and correct[mid] / picked[mid] < STANDOUT_MAX_SHARE]
    return {"match_ids": sorted(out)}


@router.get("/{tournament_id}/matches/{match_id}/predictors")
async def match_predictors(
    tournament_id: int,
    match_id: int,
    league_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Who called a match right, and who didn't — or, before it is decided,
    whose pick is still standing and whose has already gone out.

    Scoped to the league the draw page currently has selected, or to every
    participant in the draw when it is on Global. "Participant" means at least
    one pick in this draw — the same bar the standings use. A league member who
    never entered this draw is not wrong about the match, they simply are not
    playing it, and listing them would misrepresent both columns.

    Completed match: `correct` picked the winner, `incorrect` did not (their
    pick named). Undecided match (`pending: true`): `correct` picked a player
    who has not lost yet — one of the two on court, or, while a slot is still
    open, anyone in it who has no loss in this draw — and `incorrect` picked
    someone already beaten. Both columns then name the pick and are ordered
    by how many backed it, so the room's split reads at a glance. Byes answer
    with nothing: there is no contest to have called.
    """
    from collections import Counter
    from app.models.league import League, LeagueMember
    from app.routers.leagues import _check_access

    match = await db.get(Match, match_id)
    if not match or match.draw_id != tournament_id:
        raise HTTPException(404, "Match not found")
    pending = match.winner_id is None
    if match.is_bye:
        return {"correct": [], "incorrect": [], "league_name": None, "pending": pending}

    # Naming who called a match right names their pick. Held back until the
    # first round is complete for the same reason the brackets are: under
    # progressive locking the rest of the round is still being predicted.
    from app.services.locking import predictions_visible
    _draw = await db.get(Draw, tournament_id)
    if _draw is not None and not await predictions_visible(db, _draw):
        return {"correct": [], "incorrect": [], "league_name": None, "hidden": True,
                "pending": pending}

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
        # A cash pool on this draw: only the members who paid in are the
        # league's view of it, here as everywhere else the league looks at
        # the draw (see leagues._pool_visible).
        from app.models.cash_pool import LeagueCashPool
        pool = (await db.execute(
            select(LeagueCashPool).where(LeagueCashPool.league_id == league_id,
                                         LeagueCashPool.draw_id == tournament_id))).scalar_one_or_none()
        if pool is not None and pool.enabled:
            participant_ids &= {m.user_id for m in pool.members}

    if not participant_ids:
        return {"correct": [], "incorrect": [], "league_name": league_name,
                "pending": pending}

    picks_res = await db.execute(
        select(UserPrediction.user_id, UserPrediction.predicted_winner_id).where(
            UserPrediction.match_id == match_id,
            UserPrediction.user_id.in_(participant_ids),
        )
    )
    picked_winner = {uid: wid for uid, wid in picks_res.all()}

    # UNDECIDED: "still standing" is being one of the two in this match. While
    # a slot is still open (its feeder not yet decided) nobody is on court for
    # that side, so anyone without a loss in this draw still qualifies —
    # a pick can only be from the match's own feeder subtree, so this never
    # counts a survivor from elsewhere in the draw.
    in_match = {pid for pid in (match.player1_id, match.player2_id) if pid is not None}
    slots_open = match.player1_id is None or match.player2_id is None
    eliminated: set = set()
    if pending and slots_open:
        for p1, p2, w in (await db.execute(
            select(Match.player1_id, Match.player2_id, Match.winner_id)
            .where(Match.draw_id == tournament_id, Match.winner_id.isnot(None),
                   Match.is_bye == False)  # noqa: E712
        )).all():
            eliminated.update(pid for pid in (p1, p2) if pid is not None and pid != w)

    def _still_in(pid) -> bool:
        return pid is not None and (pid in in_match
                                    or (slots_open and pid not in eliminated))

    # Case-insensitive: a plain ORDER BY username puts every capitalised handle
    # ahead of every lowercase one ("Tono" before "dogger27"), which reads as
    # unsorted. Ordered on the handle the UI actually shows — see UserName.
    users_res = await db.execute(
        select(User)
        .where(User.id.in_(participant_ids))
        .order_by(func.lower(func.coalesce(User.username, User.display_name)))
    )
    # WHO THEY PICKED, for the ones who got it wrong. "dogger27" alone says a
    # pick missed; "dogger27 (S. Shimabukuro)" says what they believed, which
    # is the interesting half — and on a match nobody watched it is the only
    # way to see whether the room split or everyone backed the same loser.
    # Only the losers need naming: a correct pick is the winner, already in
    # the title.
    # Undecided: both columns name the pick — nobody is "the winner, already
    # in the title" yet.
    if pending:
        name_ids = {wid for wid in picked_winner.values() if wid is not None}
    else:
        name_ids = {wid for uid, wid in picked_winner.items()
                    if wid is not None and wid != match.winner_id}
    picked_names = {}
    if name_ids:
        picked_names = {e.id: e.display_name for e in (await db.execute(
            select(DrawEntry).where(DrawEntry.id.in_(name_ids)))).scalars()}

    correct, incorrect = [], []
    for u in users_res.scalars().all():
        pid = picked_winner.get(u.id)
        got_it = _still_in(pid) if pending else pid == match.winner_id
        out = UserPublicOut.model_validate(u).model_dump()
        if pending or not got_it:
            out["picked"] = picked_names.get(pid)
        (correct if got_it else incorrect).append(out)

    # Wrong picks group by WHO they backed, so the split in the room reads at a
    # glance — five names under one player, two under another — rather than
    # being interleaved alphabetically by handle. Surname first, since that is
    # what the column shows; handle breaks ties.
    def _by_pick(u):
        name = u.get("picked") or ""
        parts = name.split()
        surname = parts[-1].casefold() if parts else ""
        return (surname, name.casefold(),
                (u.get("username") or u.get("display_name") or "").casefold())

    if pending:
        # Most-backed pick first in BOTH columns; a user with no pick for this
        # match (a partial bracket) has nothing to count and sorts last.
        freq = Counter(u.get("picked") for u in correct + incorrect if u.get("picked"))

        def _by_freq(u):
            return (-freq.get(u.get("picked"), 0),) + _by_pick(u)
        correct.sort(key=_by_freq)
        incorrect.sort(key=_by_freq)
    else:
        incorrect.sort(key=_by_pick)

    return {"correct": correct, "incorrect": incorrect, "league_name": league_name,
            "pending": pending}


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
    max_map: dict[int, float] = {}
    picks_map: dict[int, dict] = {}
    position_by_entry = {e.id: e.bracket_position for e in all_entries}
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
        picks_map[user.id] = pred_by_match
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
        max_map[user.id] = total_pts + potential_points(
            pred_by_match, all_matches, position_by_entry, pts_table)

    guesses = await final_tiebreak.guesses_for(db, tournament_id)
    final_tiebreak.apply(scores, tournament, guesses,
                         await final_tiebreak.default_for(tournament))
    ranked = rank_users(scores, tournament.num_rounds)
    user_map = {u.id: u for u in users}
    # Where each bracket can still finish, once the draw is down to R16.
    ranges = await finish_range_async(
        tournament_id, all_matches, pts_table, tournament.num_rounds,
        {s.user_id: s for s in scores}, picks_map, bots=await _bot_ids(db)) or {}
    return [
        LeaderboardEntry(rank=i + 1, user=user_map[s.user_id], total_points=s.total_points,
                         correct_count=s.correct_count, max_points=max_map[s.user_id],
                         has_upset_pick=has_upset_map[s.user_id],
                         best_rank=ranges.get(s.user_id, (None, None))[0],
                         worst_rank=ranges.get(s.user_id, (None, None))[1],
                         **final_tiebreak.guess_fields(guesses.get(s.user_id)),
                         tie_sets_diff=s.tie_sets_diff,
                         tie_aces_diff=s.tie_aces_diff, tie_minutes_diff=s.tie_minutes_diff,
                         podium_locked=podium_locked(ranges.get(s.user_id)))
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

    # Every match and every line, for the best case still open to each
    # bracket (potential_points): who is out, and which half each pick is in.
    all_matches = (await db.execute(
        select(Match).where(Match.draw_id == tournament_id))).scalars().all()
    all_entries = (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == tournament_id))).scalars().all()
    position_by_entry = {e.id: e.bracket_position for e in all_entries}

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
    banked: dict[int, UserScore] = {}
    picks_map: dict[int, dict] = {}
    guesses_d = await final_tiebreak.guesses_for(db, tournament_id)
    default_d = await final_tiebreak.default_for(tournament)
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
        picks_map[user.id] = pred_by_match
        user_predictions[str(user.id)] = {str(k): v for k, v in pred_by_match.items() if k in timeline_ids}
        by_round: defaultdict = defaultdict(float)
        correct_by_round: dict[int, int] = {}
        correct_count = 0
        for match in completed_matches:
            if match.winner_id is None:
                continue
            if pred_by_match.get(match.id) != match.winner_id:
                continue
            by_round[match.round_number] += pts_table.get(match.round_number, 0)
            correct_by_round[match.round_number] = correct_by_round.get(match.round_number, 0) + 1
            correct_count += 1

        pts_list = [by_round.get(r, 0) for r in range(1, (tournament.num_rounds or 7) + 1)]
        banked[user.id] = UserScore(user_id=user.id, total_points=sum(pts_list),
                                    correct_count=correct_count, correct_by_round=correct_by_round)
        entries.append({
            "user_id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            # A BOT COMPETES BUT TAKES NO PLACE. Highest_Rank picks the
            # higher-ranked player in every match; it belongs in the table as a
            # yardstick and not in the numbering, where it pushed every person
            # below it down one (owner, 2026-09-13). The clients do the
            # numbering, so they need to know which row this is.
            "is_bot": bool(user.is_bot),
            "round_points": pts_list,
            # THREE ANSWERS AND THREE GAPS, computed ONCE. diffs_for returns
            # (sets, aces, minutes) and it used to return (aces, minutes) —
            # anything still reading [0] as the aces gap now silently sorts on
            # sets under the wrong name.
            **(lambda g, d: {
                "final_guess": ({"sets": g[0], "aces": g[1], "minutes": g[2]} if g else None),
                "tie_sets_diff": d[0], "tie_aces_diff": d[1], "tie_minutes_diff": d[2],
            })(
                guesses_d.get(user.id),
                final_tiebreak.diffs_for(
                    guesses_d.get(user.id) or default_d,
                    tournament.final_winner_aces, tournament.final_duration_min,
                    tournament.final_sets),
            ),
            "total": sum(pts_list),
            "correct_count": correct_count,
            "max_points": sum(pts_list) + potential_points(
                pred_by_match, all_matches, position_by_entry, pts_table),
        })

    # Where each bracket can still finish, once the draw is down to R16 — and,
    # over the same futures, weighted by who is likely to win each match left:
    # the chance it finishes first and the chance it finishes on the podium.
    # The odds are built only when the range is (the same R16 line), because
    # they ride along with that enumeration and cost two queries otherwise.
    # THE CHANCES REACH BACK FURTHER THAN THE RANGE. Up to fifteen undecided
    # matches both are exact, from the same enumeration. Beyond that the
    # futures are sampled (scoring.CHANCES_SAMPLES, fixed seed) so Win and
    # Top 3 exist from the first round — and the range comes back empty,
    # because it is an extreme and a sample would understate it. No loss: with
    # sixty matches left every bracket can still finish first and last, so the
    # range says nothing there while the chances say plenty.
    # NOT UNTIL THE PICKS ARE SHUT. A chance computed over brackets people
    # are still editing is a number about a field that does not exist yet: it
    # moves when anyone saves, it is nobody's real standing, and it invites a
    # reader to tune their own bracket against it. The owner's rule,
    # 2026-09-12 — and it is the same line the warm pass already draws
    # (chances_warm refuses an open draw), so nothing is precomputed for a
    # state that is never shown.
    #
    # `is_locked` is the model's own read-only property: picks_locked_at under
    # match-by-match locking, computed_status otherwise, and it honours an
    # admin's selections_unlocked. Read-only matters — a GET must not take the
    # writer (feedback_reads_must_not_write).
    picks_shut = bool(tournament.is_locked)
    sampled = chances_sampled(all_matches)
    odds = (await draw_odds(db, tournament, all_matches)
            if picks_shut and chances_available(all_matches) else None)
    ranges = await finish_range_async(
        tournament_id, all_matches, pts_table, tournament.num_rounds or 7, banked, picks_map,
        odds=odds, sample=sampled, bots=await _bot_ids(db))
    for e in entries:
        rng = (ranges or {}).get(e["user_id"])
        e["best_rank"], e["worst_rank"] = (rng[0], rng[1]) if rng else (None, None)
        e["podium_locked"] = podium_locked(rng) if rng and rng[1] is not None else None
        e["p_win"], e["p_podium"] = (rng[2], rng[3]) if rng and len(rng) > 3 else (None, None)
    # WHAT-IF WORLDS, from the semis on: every way the last matches can go,
    # each labelled by its final, with everyone's picks on those matches so
    # the table can be re-scored under any of them in the browser.
    names_by_entry = {e.id: e.display_name for e in all_entries}
    worlds = enumerate_worlds(all_matches, pts_table, names_by_entry)
    world_ids = {r["match_id"] for w in (worlds or []) for r in w["results"]}
    world_predictions = {
        str(uid): {str(k): v for k, v in picks.items() if k in world_ids}
        for uid, picks in picks_map.items()
    } if worlds else {}
    # The last two rounds as they stand — who is in each semi, who has won —
    # for the mini bracket beside the world stepper.
    nr = tournament.num_rounds or 7
    tail_matches = sorted(
        ({"match_id": m.id, "round_number": m.round_number, "match_number": m.match_number,
          "player1_id": m.player1_id, "player1": names_by_entry.get(m.player1_id),
          "player2_id": m.player2_id, "player2": names_by_entry.get(m.player2_id),
          "winner_id": m.winner_id}
         for m in all_matches if m.round_number >= nr - 1 and not m.is_bye),
        key=lambda x: (x["round_number"], x["match_number"])) if worlds else None

    # Points, then the final tiebreak (services/final_tiebreak); level stays level.
    _big = 10 ** 6
    entries.sort(key=lambda x: (-x["total"],
                                x["tie_sets_diff"] if x["tie_sets_diff"] is not None else _big,
                                x["tie_aces_diff"] if x["tie_aces_diff"] is not None else _big,
                                x["tie_minutes_diff"] if x["tie_minutes_diff"] is not None else _big))
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

    # THE FINISH COLUMN OF EVERY SNAPSHOT the slider can show, from the first
    # position it is computable at. Keyed by position; the client reads the
    # one under the thumb, and prints a dash before `finish_from`.
    finish_from, finish_hist = await finish_history_async(
        tournament_id, all_matches, [m["id"] for m in timeline], pts_table, tournament.num_rounds or 7,
        picks_map, odds=odds, bots=await _bot_ids(db))
    # [best, worst, p_win, p_podium] — the Chances columns follow the slider
    # for the same reason Finish does: the row under the thumb is a snapshot,
    # and two columns disagreeing about which moment they describe is worse
    # than either of them being absent.
    finish_history = {str(p): {str(u): list(v) for u, v in r.items()} for p, r in finish_hist.items()}

    return {
        "entries": entries,
        "finish_range_available": ranges is not None and not sampled,
        "odds_available": odds is not None and ranges is not None,
        "chances_sampled": bool(sampled and ranges),
        "chances_version": (chances_fingerprint(all_matches, tournament.num_rounds or 7,
                                                picks_map, odds) if odds else None),
        "odds_attribution": getattr(odds, "attribution", ODDS_ATTRIBUTION),
        "finish_from": finish_from,
        "finish_history": finish_history,
        "cash_pool": False,
        "worlds": worlds,
        "tail_matches": tail_matches,
        "world_predictions": world_predictions if picks_visible else {},
        "completed_matches_count": len(completed_matches),
        "rounds_with_matches": rounds_with_matches,
        "completed_round_nums": completed_round_nums,
        "matches_timeline": timeline,
        "user_predictions": user_predictions if picks_visible else {},
        "predictions_hidden": not picks_visible,
    }


@router.get("/{tournament_id}/global-chances")
async def global_chances(tournament_id: int, position: int, db: AsyncSession = Depends(get_db)):
    """The chances of one timeline position, for the global standings — the
    twin of `/leagues/{id}/chances`, and the same reason for existing: before
    fifteen undecided matches a position costs a sampled walk, so they are
    asked for one at a time instead of all hundred and twenty up front."""
    from app.services.scoring import _points_table, chances_at_async

    draw = await db.get(Draw, tournament_id)
    if not draw:
        raise HTTPException(404, "Tournament not found")

    all_matches = (await db.execute(
        select(Match).where(Match.draw_id == tournament_id))).scalars().all()
    completed = [m for m in all_matches if m.status == "completed" and not m.is_bye]
    timeline_ids = [m.id for m in sorted(
        completed, key=lambda m: (m.completed_at is not None, m.completed_at or "", m.id))]

    rows = (await db.execute(
        select(UserPrediction.user_id, UserPrediction.match_id, UserPrediction.predicted_winner_id)
        .where(UserPrediction.draw_id == tournament_id,
               UserPrediction.predicted_winner_id.isnot(None)))).all()
    picks_map: dict[int, dict] = {}
    for uid, mid, w in rows:
        picks_map.setdefault(uid, {})[mid] = w

    # The same gate as round-scores: no chances while the brackets are open.
    odds = (await draw_odds(db, draw, all_matches)
            if picks_map and draw.is_locked else None)
    sampled, chances = False, {}
    if odds is not None:
        sampled, chances = await chances_at_async(
            tournament_id, all_matches, timeline_ids, position, _points_table(draw),
            draw.num_rounds or 7, picks_map, odds=odds)
    return {
        "position": max(1, min(int(position), len(timeline_ids))) if timeline_ids else 0,
        "sampled": bool(sampled),
        "chances": {str(u): [v[0], v[1]] for u, v in chances.items()},
    }


@router.get("/{tournament_id}/global-chances-history")
async def global_chances_history(tournament_id: int, db: AsyncSession = Depends(get_db)):
    """Every computed position at once, for the global standings — the twin of
    /leagues/{id}/chances-history, and the same reason: the slider should read
    a map it already holds rather than ask for each stop. Per-mille integers."""
    from app.services.scoring import (chances_fingerprint, chances_history_held,
                                      chances_history_key)

    draw = await db.get(Draw, tournament_id)
    if not draw:
        raise HTTPException(404, "Tournament not found")
    all_matches = (await db.execute(
        select(Match).where(Match.draw_id == tournament_id))).scalars().all()
    completed = [m for m in all_matches if m.status == "completed" and not m.is_bye]
    timeline_ids = [m.id for m in sorted(
        completed, key=lambda m: (m.completed_at is not None, m.completed_at or "", m.id))]
    if not timeline_ids:
        return {"scale": 1000, "complete": True, "positions": {}}
    rows = (await db.execute(
        select(UserPrediction.user_id, UserPrediction.match_id, UserPrediction.predicted_winner_id)
        .where(UserPrediction.draw_id == tournament_id,
               UserPrediction.predicted_winner_id.isnot(None)))).all()
    picks_map: dict[int, dict] = {}
    for uid, mid, w in rows:
        picks_map.setdefault(uid, {})[mid] = w
    if not picks_map:
        return {"scale": 1000, "complete": True, "positions": {}}
    odds = await draw_odds(db, draw, all_matches)
    if odds is None:
        return {"scale": 1000, "complete": True, "positions": {}}
    key = chances_history_key(tournament_id, draw.num_rounds or 7, picks_map,
                              odds.without_live(), all_matches)
    held = chances_history_held(key, timeline_ids)
    # See the note on /leagues/{id}/chances-history: a visit warms the draw
    # being read, because the scheduled pass only covers the last three weeks.
    if len(held) < len(timeline_ids):
        from app.services.chances_warm import warm_soon
        warm_soon([tournament_id])
    return {
        "scale": 1000,
        "complete": len(held) >= len(timeline_ids),
        "version": chances_fingerprint(all_matches, draw.num_rounds or 7, picks_map,
                                       odds.without_live()),
        "positions": {str(p): {str(u): [round(v[0] * 1000), round(v[1] * 1000)]
                               for u, v in rows_.items()}
                      for p, rows_ in sorted(held.items())},
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

        # A LATE ENTRANT HAS NO SNAPSHOT AT THAT WEEK AT ALL. The week above is
        # pinned to the tournament's reference date so a historical draw shows
        # the Elo of its own era — but a qualifier who first appeared in the
        # rankings after the cutoff has nothing on or before it, and fell
        # through as a dash beside her WTA rank. Fill only those, from the most
        # recent snapshot she does have; every player already resolved keeps
        # the era-correct value. Mirrors the same fallback in
        # services/rankings.py, for the same reason.
        missing_elo = [tid for tid in te_ids if tid not in te_elo_rank_map]
        if missing_elo:
            latest_res = await db.execute(
                select(TeRankingsSnapshot.player_id, TeRankingsSnapshot.week_date,
                       TeRankingsSnapshot.elo_rank)
                .where(TeRankingsSnapshot.player_id.in_(missing_elo),
                       TeRankingsSnapshot.elo_rank.isnot(None))
            )
            newest: dict[int, tuple] = {}
            for pid, wk, elo in latest_res:
                if wk is not None and (pid not in newest or wk > newest[pid][0]):
                    newest[pid] = (wk, elo)
            for pid, (_wk, elo) in newest.items():
                te_elo_rank_map[pid] = elo

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

def _keep_known(round_number: int, incoming, existing) -> bool:
    """Whether a match's player slot may be overwritten with `incoming`.

    Round 1: always — it is structural and every source states it in full.
    Later rounds: only when the source names somebody, or nobody is there yet.
    A None from a shape-only source must never erase a player a result placed.
    """
    return round_number == 1 or incoming is not None or existing is None


def _agreement(shape, entries) -> float:
    """How much of a draw already in the database a shape agrees with, 0..1.

    Judged on NAMED slots only, as the same person (draw_changes.same_person —
    diacritics, hyphens and given/surname order all count as the same), over
    the slots both sides name. A source that identified the wrong tournament
    scores near zero; a source that respells everyone scores one.
    """
    from app.services.draw_changes import same_person

    ours = {e.bracket_position: (e.name or "").strip() for e in entries if (e.name or "").strip()}
    theirs = {e.bracket_position: e.name for e in shape.entrants if (e.name or "").strip()}
    both = [p for p in theirs if p in ours]
    if not both:
        return 0.0
    return sum(1 for p in both if same_person(ours[p], theirs[p])) / len(both)


# The floor a shape must clear before it may REWRITE a draw that already has a
# field. Below it, the source has almost certainly found a different
# tournament, and the draw keeps its current author.
REFRESH_AGREEMENT_FLOOR = 0.9


async def _shape_from_sources(tournament: Draw, db: AsyncSession, report: dict,
                              allow_sofascore_identity: bool = True):
    """The best complete shape any source has for this draw, or (None, None, {}).

    Order of trust: the tour's own sheet — the WTA's JSON for a women's draw,
    the ATP's mds.pdf for a men's; Tennis Explorer for either tour; Sofascore last — the cup tree of an already-resolved draw
    from the cache, or a fresh identity lookup when the caller allows it.
    Returns (shape, source_name, identity_fields_to_store).
    """
    import logging

    from app.services.sofa_draw_shape import bracket_is_complete
    logger = logging.getLogger(__name__)

    if (tournament.gender or "").upper() == "F":
        from app.services import wta_draw
        row = await db.get(Tournament, tournament.tournament_id) if tournament.tournament_id else None
        event_id = wta_draw.event_id_for(tournament, row)
        if event_id:
            report["tried"].append("wta_official")
            try:
                got = wta_draw.fetch_shape(int(event_id), int(tournament.year))
            except Exception as exc:
                logger.warning("WTA draw fetch failed for draw %s: %s", tournament.id, exc)
                got = None
            if got and bracket_is_complete(got):
                return got, "wta_official", {}
            if got:
                report["wta_official"] = "incomplete"

    # THE ATP'S OWN SHEET FIRST for a men's draw (owner, 2026-09-25):
    # protennislive's mds.pdf — positions, seeds, entry types, byes and
    # countries, from the tour itself. Tennis Explorer and Wikipedia remain
    # behind it, and a cut name is resolved against them (atp_pdf_draw).
    if (tournament.gender or "").upper() == "M":
        from app.services import atp_pdf_draw
        row = await db.get(Tournament, tournament.tournament_id) if tournament.tournament_id else None
        if row is not None and row.atp_tournament_id:
            report["tried"].append("atp_official")
            try:
                got, extra = await atp_pdf_draw.fetch_shape(tournament, row, db)
                report.update(extra)
            except Exception as exc:
                logger.warning("ATP draw sheet failed for draw %s: %s", tournament.id, exc)
                got = None
            if got and bracket_is_complete(got):
                return got, "atp_official", {}
            if got:
                report["atp_official"] = "incomplete"

    from app.services import te_draw
    report["tried"].append("tennisexplorer")
    try:
        got = await te_draw.fetch_shape(tournament)
    except Exception as exc:
        logger.warning("TE draw fetch failed for draw %s: %s", tournament.id, exc)
        got = None
    if got and bracket_is_complete(got):
        # TE prints SURNAMES and no flags. The slug is the identity, and the
        # TE player index this project already keeps turns it back into the
        # full name and the IOC code — locally, no request.
        from app.models.rankings import TePlayer
        from app.services.rankings import COUNTRY_TO_IOC
        slugs = [e.te_slug for e in got.entrants if e.te_slug]
        if slugs:
            rows = (await db.execute(select(TePlayer).where(
                TePlayer.te_slug.in_(slugs)))).scalars().all()
            by_slug = {r.te_slug: r for r in rows}
            nats = 0
            for e in got.entrants:
                r = by_slug.get(e.te_slug) if e.te_slug else None
                if r is None:
                    continue
                full = (r.name_display or f"{r.first_name or ''} {r.last_name or ''}").strip()
                if full:
                    e.name = full
                ioc = COUNTRY_TO_IOC.get((r.nationality or "").strip().lower())
                if ioc and not e.nationality:
                    e.nationality, nats = ioc, nats + 1
            report["te_names_resolved"] = f"{len(by_slug)}/{len(slugs)}"
            report["te_nationalities"] = nats
        return got, "tennisexplorer", {}
    if got:
        report["tennisexplorer"] = "incomplete"

    report["tried"].append("sofascore")
    from app.services import sofascore
    from app.services.sofa_draw_shape import draw_shape
    if tournament.sofa_tournament_id and tournament.sofa_season_id:
        try:
            payload = await sofascore._cuptree_of(tournament.sofa_tournament_id,
                                                  tournament.sofa_season_id)
            got = draw_shape(payload)
        except Exception as exc:
            logger.debug("cup tree unavailable for draw %s: %s", tournament.id, exc)
            got = None
        if got and bracket_is_complete(got):
            return got, "sofascore", {}
        if got:
            report["sofascore"] = (f"incomplete: {got.entrant_count} entrants + "
                                   f"{len(got.byes)} byes in a {got.bracket_size} bracket")
    elif allow_sofascore_identity:
        found = await sofascore.resolve_without_field(tournament)
        if found is not None:
            uid, season_id, got = found
            ids = {"sofa_tournament_id": uid, "sofa_season_id": season_id}
            if bracket_is_complete(got):
                return got, "sofascore", ids
            report["sofascore"] = (f"incomplete: {got.entrant_count} entrants + "
                                   f"{len(got.byes)} byes in a {got.bracket_size} bracket")
    return None, None, {}


async def refresh_shape(tournament: Draw, db: AsyncSession) -> dict:
    """Keep a draw's shape current from the best non-Wikipedia source.

    THE OTHER HALF OF GETTING RID OF WIKIPEDIA. bootstrap_draw builds a draw
    that has nothing; this keeps one current that does — the qualifier slots
    filled when qualifying ends, a withdrawal replaced by a lucky loser, a seed
    printed late — and it runs BEFORE the Wikipedia scrape in the refresh loop,
    which is skipped when this succeeds. Wikipedia becomes the fallback.

    Three things make rewriting a live draw safe rather than reckless:

      the writer's guards   a later-round player or a winner is never cleared
                            by a source that does not know it (_keep_known,
                            and the winner guard that already existed)
      the agreement floor   a shape may only take over a draw it agrees with
                            on >= 90% of the slots both name, judged as the
                            same person — the guard against Tennis Explorer
                            having matched the wrong city
      spelling is kept      where the source names the same person we already
                            hold, our spelling stays. No churn, no phantom
                            "replaced" notices, one author per draw

    Never touches a completed draw. Returns a report; the caller commits.
    """
    from app.services.draw_changes import same_person
    from app.services.sofa_draw_shape import shape_to_parsed
    from app.services.system_log import app_log

    report: dict = {"draw_id": tournament.id, "refreshed": False, "tried": []}
    if tournament.status == "completed":
        report["error"] = "completed draws are not refreshed"
        return report
    entries = (await db.execute(select(DrawEntry).where(
        DrawEntry.draw_id == tournament.id))).scalars().all()
    if not entries:
        report["error"] = "no entries — that is a bootstrap, not a refresh"
        # SAID AS A FLAG, not only in the sentence: the refresh loop acts on
        # this — it is the one decline that means "another door may open" —
        # and a caller should never have to read an error message to find out.
        report["needs_bootstrap"] = True
        return report

    shape, source, ids = await _shape_from_sources(
        tournament, db, report, allow_sofascore_identity=False)
    if shape is None:
        report["error"] = "no source has a complete bracket"
        return report

    agreement = _agreement(shape, entries)
    report["agreement"] = round(agreement, 3)
    if agreement < REFRESH_AGREEMENT_FLOOR:
        report["error"] = (f"{source} disagrees with the draw on "
                           f"{round((1 - agreement) * 100)}% of named slots — not taking over")
        await app_log(
            "warning", "draws",
            f"{source} bracket for {tournament.year} {tournament.name} "
            f"({tournament.gender}) agrees with only {round(agreement * 100)}% of "
            f"the field — draw keeps its current author",
            report, dedup_key=f"shape_disagree_{source}_{tournament.id}", dedup_hours=24)
        return report

    # Keep our spelling for anyone the source merely respells.
    ours = {e.bracket_position: e for e in entries}
    for e in shape.entrants:
        mine = ours.get(e.bracket_position)
        if mine and (mine.name or "").strip() and e.name and same_person(mine.name, e.name):
            e.name = mine.name
        if mine and mine.nationality and not e.nationality:
            e.nationality = mine.nationality
        if mine and mine.seed and not e.seed:
            e.seed = mine.seed                 # a seed TE has not printed yet

    await _do_scrape(tournament, db, parsed=shape_to_parsed(shape))
    slugs = {e.bracket_position: e.te_slug for e in shape.entrants if e.te_slug}
    if slugs:
        for e in entries:
            if not e.te_slug and slugs.get(e.bracket_position):
                e.te_slug = slugs[e.bracket_position]
    for k, v in ids.items():
        setattr(tournament, k, v)
    changed = tournament.shape_source != source
    tournament.shape_source = source
    report.update(refreshed=True, source=source, entrants=shape.entrant_count,
                  byes=len(shape.byes))
    if changed:
        await app_log(
            "info", "draws",
            f"{tournament.year} {tournament.name} ({tournament.gender}) is now "
            f"authored by {source} ({shape.entrant_count} entrants, "
            f"{round(agreement * 100)}% agreement with the field it replaces)",
            report)
    return report


async def bootstrap_draw(tournament: Draw, db: AsyncSession) -> dict:
    """Build a draw's shape from the best source that has it, when we have none.

    THE CASE, AND THE ONLY ONE: a draw with NO entries — Hangzhou and Chengdu
    on 2026-09-21, two days from play with no Wikipedia article, nothing to
    show and picks impossible. Once a draw has a field, whatever wrote it owns
    it and the normal pipeline keeps it current; re-shaping a live draw from
    another source would put two writers on one bracket and risk clearing
    results the way feedback_scraper_clears_espn_winner records. So this
    bootstraps, records where the shape came from, and gets out of the way.

    SOURCES, IN ORDER OF TRUST, each returning the same DrawShape:

      wta_official   the WTA's own draw sheet as JSON — every slot, byes
                     explicit, seeds, entry types, IOC nationality, the
                     tour's player ids. Women's draws only.
      tennisexplorer the complete field at two days out for either tour,
                     keyed by the te_slug this project already stores; seeds
                     when printed, never required.
      sofascore      identity from tour + bracket + dates (resolve_without_
                     field), shape from the cup tree — which is a view over
                     EVENTS and so hides a player until his first match
                     exists. Last, because it is the one that fills late.

    A shape is accepted only if `bracket_is_complete` — every slot occupied
    or a bye — because Sofascore's tree, and possibly the others', fills in
    over days, and a half-filled bracket written and stamped released is worse
    than no bracket (the bootstrap would never revisit it).

    The shape goes through shape_to_parsed into _do_scrape, so the write is
    the same write Wikipedia gets.
    """
    from app.services.sofa_draw_shape import shape_to_parsed
    from app.services.system_log import app_log

    report: dict = {"draw_id": tournament.id, "bootstrapped": False, "tried": []}

    existing = (await db.execute(
        select(func.count()).select_from(DrawEntry).where(
            DrawEntry.draw_id == tournament.id))).scalar() or 0
    if existing:
        report["error"] = f"draw already has {existing} entries — not ours to rebuild"
        return report

    shape, source, ids = await _shape_from_sources(tournament, db, report)

    if shape is None:
        report["error"] = "no source has a complete bracket for this draw yet"
        return report

    # THE CHECK THAT REPLACES THE FIELD, for the source that finds a draw BY
    # NAME. `refresh_shape` can demand 90% agreement with the players it
    # already holds; a draw with nothing holds nothing, and Tennis Explorer
    # identifies an event by its city or its name — "a name is not an
    # identity" (te_draw.match_tournament, and the whole reason Sofascore
    # refuses to resolve one without corroboration).
    #
    # So the bracket must be the one a field of our draw_size plays in: the
    # same geometry test Sofascore's own field-less identity uses, imported
    # rather than restated so the two can never drift. The WTA sheet is keyed
    # by the tour's own event id — no name is guessed, and a disagreement
    # there would mean OUR draw_size is stale, which must not hold up a
    # release. Sofascore checks itself, inside resolve_without_field.
    if source == "tennisexplorer":
        from app.services.sofascore import _geometry_agrees
        if not _geometry_agrees(tournament.draw_size, shape.bracket_size):
            report["error"] = (
                f"tennisexplorer's bracket of {shape.bracket_size} is not the one a "
                f"{tournament.draw_size}-player draw plays in — not building from it")
            await app_log(
                "warning", "draws",
                f"Tennis Explorer's bracket for {tournament.year} {tournament.name} "
                f"({tournament.gender}) is a {shape.bracket_size} against our "
                f"draw_size {tournament.draw_size} — refusing to build a draw we "
                f"cannot corroborate", report,
                dedup_key=f"te_geometry_{tournament.id}", dedup_hours=24)
            return report

    parsed = shape_to_parsed(shape)
    await _do_scrape(tournament, db, parsed=parsed)

    # What the writer cannot carry, set here: the slugs a source stated, and
    # the identity Sofascore resolved, so the next pass reads the field direct.
    slugs = {e.bracket_position: e.te_slug for e in shape.entrants if e.te_slug}
    if slugs:
        rows = (await db.execute(select(DrawEntry).where(
            DrawEntry.draw_id == tournament.id,
            DrawEntry.bracket_position.in_(list(slugs))))).scalars().all()
        for e in rows:
            if not e.te_slug:
                e.te_slug = slugs[e.bracket_position]
    for k, v in ids.items():
        setattr(tournament, k, v)
    tournament.shape_source = source

    report.update(bootstrapped=True, source=source, bracket_size=shape.bracket_size,
                  entrants=shape.entrant_count, byes=len(shape.byes), **ids)
    await app_log(
        "info", "draws",
        f"Built {tournament.year} {tournament.name} ({tournament.gender}) from "
        f"{source}: {shape.entrant_count} entrants in a {shape.bracket_size} "
        f"bracket, {len(shape.byes)} bye(s) — no Wikipedia article was needed",
        report)
    return report


# The name the first version shipped under, kept for anything that imported it.
bootstrap_from_sofascore = bootstrap_draw


async def _do_scrape(tournament: Draw, db: AsyncSession, force_refresh: bool = False,
                     parsed=None) -> None:
    """Write a draw from a ParsedDraw, fetching one from Wikipedia if not given.

    `parsed` exists so a shape from ANOTHER SOURCE can use this exact writer
    rather than a parallel one. Everything below — the upsert, the bye and
    match handling, the draw-release stamp and its premature-revert, ranking
    assignment, qualifier detection, the pick repair — is decisions that took a
    long time to get right, and a second copy of them would drift. See
    services/sofa_draw_shape.shape_to_parsed, which builds a ParsedDraw from a
    Sofascore cup tree and hands it here.
    """
    from datetime import date
    import logging
    logger = logging.getLogger(__name__)

    if parsed is None:
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
    from app.services.tournament_sync import official_dates
    if (tournament.status not in ("active", "completed")
            and getattr(parsed, "carries_dates", True)
            and not await official_dates(db, tournament)):
        # A RELEASED DRAW'S START DATE NEVER MOVES BACKWARDS. Moving it earlier
        # is the one date change that can close a draw people are picking:
        # Draw.computed_status calls any draw whose start has passed "active",
        # which locks picks with nothing logged. The 2026 US Open sat locked on
        # release day carrying 24 August — its qualifying Monday — while the
        # main draw had not begun. Forward corrections still apply; so does
        # every change while the draw is unreleased.
        # Refused only when the move would make the draw look STARTED — that
        # is the harm (computed_status flips to active and picks close). An
        # earlier date still in the future is an ordinary correction: the 2026
        # US Open main draw opens on the Sunday, not the Monday, and that
        # correction has to be able to land.
        released = tournament.draw_released_direct_at is not None
        proposed = parsed.start_date or (
            snap_to_monday(tournament.start_date) if tournament.start_date else None)
        if proposed and not (released and tournament.start_date
                             and proposed < tournament.start_date
                             and proposed <= date.today()):
            tournament.start_date = proposed
        elif proposed:
            logger.warning(
                "Refused to move %s %s start_date back from %s to %s on a "
                "released draw", tournament.year, tournament.name,
                tournament.start_date, proposed)
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
            # A SOURCE THAT DOES NOT KNOW THE NAME DOES NOT GET TO ERASE IT.
            #
            # An unfilled qualifier slot parses to an empty name, and writing
            # that over a slot we HAVE a name for is not an update, it is a
            # deletion by a source that has nothing to say. The same law the
            # match upsert below already states for a later-round slot: a
            # shape-only source's blank means "unknown", not "nobody".
            #
            # 2026 Chengdu Open, 2026-09-23: Wikipedia still printed four
            # Round-1 slots as "Qualifier" hours into play, while ESPN's
            # pairings had already named them. Each scrape blanked the four
            # names and the ESPN fill put them back — three round trips inside
            # seven minutes, a duplicate "filled" draw-change event every time
            # (24 queued for re-announcement), and `assign_rankings` handed a
            # blank name on every pass, so the four kept te_player_id NULL and
            # rendered with no rank badge, no ranking, no ELO, no H2H and no
            # form on a draw already on court. `classify_change` had long since
            # decided a slot going blank is not news; it is not a FACT either.
            #
            # entry_type still applies: Q is the slot's own property and the
            # placeholder is the thing that states it. Nothing else does, so
            # nothing else can be lost.
            if not (pe.name or "").strip() and (player.name or "").strip():
                if pe.entry_type:
                    player.entry_type = pe.entry_type
                pos_to_player_id[pe.bracket_position] = player.id
                upserted_players.append(player)
                continue
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
            await assign_seed_week_rankings(upserted_players, tournament.gender,
                                            tournament.seed_ranking_week, db)
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
        # AN ENTRY SOMEBODY HAS PICKED IS NOT DELETABLE. Deleting it orphans
        # the prediction silently: the pick survives pointing at a row that no
        # longer exists, the bracket shows no selection, and the user's next
        # round reads TBD. The 2026 US Open qualifier slots hit this on every
        # scrape — Wikipedia does not list them, so the cleanup removed them
        # and the official-draw fill recreated them under new ids.
        from app.models.prediction import UserPrediction
        picked_ids = set((await db.execute(
            select(UserPrediction.predicted_winner_id).where(
                UserPrediction.draw_id == tournament.id,
                UserPrediction.predicted_winner_id.isnot(None)))).scalars().all())
        for pos in missing_positions:
            entry = existing_players[pos]
            if entry.id in picked_ids:
                continue
            await db.delete(entry)
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
    # One read per scrape: is Sofascore the source of record right now?
    from app.services.settings import load_sofa_authoritative
    sofa_is_record = await load_sofa_authoritative(db)
    for mr in parsed.matches:
        p1_id = pos_to_player_id.get(mr.player1_position)
        p2_id = pos_to_player_id.get(mr.player2_position) if mr.player2_position else None
        w_id = pos_to_player_id.get(mr.winner_position) if mr.winner_position else None
        key = (mr.round_number, mr.match_number)
        seen_match_keys.add(key)
        if key in existing_matches:
            match = existing_matches[key]
            # A LATER-ROUND SLOT IS NEVER CLEARED BY A SOURCE THAT DOES NOT KNOW
            # IT. Round 1 is structural and the source always states it; from
            # round 2 on a player is there because a result put him there, and
            # a shape-only source (the WTA sheet, Tennis Explorer, a cup tree
            # read for shape) carries no results — so its None means "unknown",
            # not "nobody". Same principle as the winner guard below.
            if _keep_known(mr.round_number, p1_id, match.player1_id):
                match.player1_id = p1_id
            if _keep_known(mr.round_number, p2_id, match.player2_id):
                match.player2_id = p2_id
            match.is_bye = mr.is_bye
            # SOFASCORE IS THE SOURCE OF RECORD FOR RESULTS; Wikipedia is the
            # fallback for a match it has none for. Until 2026-09-04 this block
            # "always trusted" Wikipedia, so every 30-minute scrape overwrote
            # the score the results sweep had written minutes earlier, and the
            # sweep wrote it back — the same tiebreak flipped between "6(5)"
            # and "65" (an unclosed <sup> on Wikipedia) all evening. The draw
            # SHAPE (players, byes, positions) stays Wikipedia's either way.
            sofa_has_it = (sofa_is_record and match.sofa_winner_id is not None)
            if sofa_has_it or w_id is None or _wikipedia_may_decide(mr):
                _wiki_claim_seen.pop(match.id, None)    # no claim outstanding
            if sofa_has_it:
                if w_id is not None and w_id != match.sofa_winner_id:
                    # Worth a row in /issues, not an overwrite: a disagreement
                    # here is either a Wikipedia edit error or a wrong event
                    # mapping, and both need eyes rather than a coin toss.
                    try:
                        from app.services.system_log import app_log
                        await app_log(
                            "warning", "scraper",
                            f"Wikipedia and Sofascore disagree on the winner of match "
                            f"{match.id} (draw {tournament.id}); kept Sofascore's",
                            detail={"match_id": match.id, "wiki_winner_id": w_id,
                                    "sofa_winner_id": match.sofa_winner_id},
                            dedup_key=f"scraper:winner-mismatch:{match.id}",
                            dedup_hours=24.0,
                        )
                    except Exception:                                    # noqa: BLE001
                        pass
            elif w_id is not None and _wikipedia_may_decide(mr):
                # A FIRST-ROUND BYE, and nothing else — see _wikipedia_may_decide.
                # The seed advances because the sheet placed nobody opposite,
                # not because anyone won. No score, because there was no match.
                if match.winner_id != w_id and match.completed_at is None:
                    match.completed_at = datetime.now(timezone.utc)
                match.winner_id = w_id
                match.status = "completed"
                match.scores_json = None
                match.live_scores_json = None
            elif w_id is not None:
                # WIKIPEDIA CLAIMS A RESULT SOFASCORE DOES NOT HAVE. It is not
                # applied — ever — but it is worth a row in /issues: the usual
                # reason is a match Sofascore never mapped, which is the thing
                # to go and fix. The row is then treated as if the sheet had
                # said nothing, and any earlier run that did apply it is undone.
                # Only once the claim outlasts WIKI_CLAIM_GRACE: before that,
                # Sofascore being a few minutes behind is the normal order.
                if _wiki_claim_overdue(match.id):
                    try:
                        from app.services.system_log import app_log
                        await app_log(
                            "warning", "scraper",
                            f"Wikipedia shows a result for match {match.id} (draw "
                            f"{tournament.id}, round {mr.round_number}) that Sofascore "
                            f"has not reported; ignored — check the event mapping",
                            detail={"match_id": match.id, "round": mr.round_number,
                                    "match_number": mr.match_number, "wiki_winner_id": w_id,
                                    "wiki_scores": mr.scores,
                                    "sofa_event_id": match.sofa_event_id},
                            dedup_key=f"scraper:wiki-result-ignored:{match.id}",
                            dedup_hours=24.0,
                        )
                    except Exception:                                    # noqa: BLE001
                        pass
                if _clear_phantom(match):
                    await _log_phantom_cleared(match, tournament, mr)
            elif match.winner_id is None:
                # No result from any source we trust: bare pending. Never the
                # sheet's in-progress score either — Sofascore live owns that.
                match.completed_at = None
                match.scores_json = None
                match.status = "pending"
            else:
                # Neither source reports a result now, but a winner is stored.
                # Nothing legitimate can have put it there without a score:
                # Sofascore writes sofa_winner_id (checked above), ESPN writes
                # scores_json beside every winner, and a bye is caught by
                # mr.is_bye. So a stored winner with no score and no Sofascore
                # backing is an earlier run of the artifact above — undo it, so
                # the draw heals on the next scrape instead of needing a hand
                # in the database.
                if _clear_phantom(match):
                    await _log_phantom_cleared(match, tournament, mr)
        else:
            # A NEW ROW TAKES NO RESULT FROM THE SHEET EITHER — only a
            # first-round bye's advancement. Its result arrives from Sofascore.
            bye_w = w_id if _wikipedia_may_decide(mr) else None
            match = Match(
                draw_id=tournament.id,
                round_number=mr.round_number,
                match_number=mr.match_number,
                player1_id=p1_id,
                player2_id=p2_id,
                winner_id=bye_w,
                is_bye=mr.is_bye,
                scores_json=None,
                status="completed" if bye_w else "pending",
                completed_at=datetime.now(timezone.utc) if bye_w else None,
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

    # THE FIELD WIKIPEDIA HAS NOT FINISHED WRITING DOWN. Its draw pages fill
    # over hours; the tournament publishes the same draw complete. Only empty
    # first-round sides are touched, so this can add nothing that contradicts
    # the page — and it self-cancels once the page catches up.
    if "US Open" in (tournament.name or ""):
        try:
            # The tournament's own day index states when play begins; every
            # week-based guess puts a Slam on the Monday, and this one starts
            # Sunday. The deadline follows from it.
            from app.services.uso_feed import fetch_main_draw_window
            from app.services.tournament_schedule import sync_closing_time
            d1, dN = await fetch_main_draw_window(tournament.year)
            if d1 and tournament.start_date != d1:
                logger.info("US Open %s: start_date %s -> %s (official day index)",
                            tournament.gender, tournament.start_date, d1)
                tournament.start_date = d1
                if dN:
                    tournament.end_date = dN
                sync_closing_time(tournament)
        except Exception:
            logger.exception("official date window failed for draw %s", tournament.id)
        try:
            from app.services.uso_draw import fill_missing_slots
            added = await fill_missing_slots(db, tournament)
            if added:
                logger.info("US Open %s: filled %d slot(s) from the official draw",
                            tournament.gender, added)
                # Same law as the ESPN fill: a slot that gains a name gains a
                # player. This runs AFTER the upsert's own assign_rankings, so
                # without this the names it just wrote would carry no ranking
                # until the next scrape came round — and a draw holding
                # entrants nothing can rank is `entries_without_draw_rank`.
                # Still inside the scrape's write, so there is no window.
                ref = (tournament.entry_ranking_week
                       or tournament.start_date or date.today())
                fresh = (await db.execute(
                    select(DrawEntry).where(
                        DrawEntry.draw_id == tournament.id,
                        DrawEntry.te_player_id.is_(None)))).scalars().all()
                if fresh:
                    await assign_rankings(fresh, tournament.gender, ref, db)
                    await assign_seed_week_rankings(
                        fresh, tournament.gender, tournament.seed_ranking_week, db)
        except Exception:
            logger.exception("official draw fill failed for draw %s", tournament.id)

    # Snap start_date to today on first detected REAL match activity.
    # Qualifying rounds begin before the Wikipedia-reported main-draw start date,
    # so use the real play date rather than Wikipedia's potentially lagging value.
    # Guard: only snap after the main draw is released — otherwise qualifying activity
    # would prematurely move the start_date forward by a week or more.
    has_activity = real_completed > 0 or any(m.scores for m in parsed.matches if not m.is_bye)
    if (has_activity and tournament.start_date and today < tournament.start_date
            and tournament.draw_released_direct_at is not None):
        tournament.start_date = today

    # A SOURCE THAT CARRIES NO RESULTS DOES NOT GET TO SAY THE DRAW HAS NONE.
    # The counters above come from the parsed matches; a shape source's are
    # all resultless, and judging status from them demoted SP Open — thirty
    # results in — to "upcoming" on the first refresh pass. For such a source
    # the matches already in the database are the evidence, which also puts
    # a demoted draw right on the next pass.
    if not getattr(parsed, "carries_results", True):
        held = list(existing_matches.values())
        total_matches = len(held)
        completed = sum(1 for m in held if m.winner_id is not None)
        real_completed = sum(1 for m in held if m.winner_id is not None and not m.is_bye)
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




# ---------------------------------------------------------------------------
# THE TIEBREAK QUESTIONS (owner, 2026-09-18): the champion's aces in the
# final and the final's length, asked when a user enters a draw, judged
# once the final is played (scoring.tiebreak_key). The GET hands the page
# the slider ends and the reference figures for the player the user has
# picked to win; the PUT stores the answers, until the picks lock.
# ---------------------------------------------------------------------------
from pydantic import BaseModel as _BaseModel, Field as _Field  # noqa: E402
from app.models.final_guess import DrawFinalGuess, answers_are_stale  # noqa: E402


class FinalGuessIn(_BaseModel):
    # Optional so a client that predates the sets question can still save the
    # other two rather than being refused outright.
    final_sets: Optional[int] = _Field(default=None, ge=2, le=5)
    final_aces: int = _Field(ge=0, le=200)
    final_duration_min: int = _Field(ge=0, le=900)


def predicted_finalists(picks: dict, matches: list, num_rounds: int) -> tuple[Optional[int], Optional[int]]:
    """(champion entry id, runner-up entry id) as the user's own bracket has
    them: the two SEMI-FINAL picks are the final, and the final's pick is the
    champion — but only if it is one of those two.

    THE FINAL'S PICK ALONE IS NOT THE CHAMPION. This read `picks[final]` and
    trusted it, so a reader who changed an earlier pick — sending their old
    champion out in the quarters — still had that player named as the champion
    in the tiebreak questions, because the row for the final still said so
    (owner, 2026-09-22: "the tiebreaker popup doesn't update the finalists to
    reflect their changes"). It could even report a champion who appears in
    neither semi-final, which is not a bracket anybody picked.

    The semis are the authority on WHO the final is, because they are the last
    round whose two winners are the final's two slots. The final's own pick
    only decides WHICH of them lifts the trophy, and an answer that names
    neither is not an answer yet: champion comes back None, and the dialog
    already knows to say "Pick your champion in the draw".

    Deliberately not a full bracket projection. The two semi picks are the
    narrowest thing that makes the pair coherent, and a projection would make
    this endpoint re-derive what the client already draws.
    """
    by = {(m.round_number, m.match_number): m for m in matches if not getattr(m, "is_bye", False)}
    semis = [picks.get(by[k].id) for k in ((num_rounds - 1, 1), (num_rounds - 1, 2)) if k in by]
    finalists = [w for w in semis if w is not None]
    final = by.get((num_rounds, 1))
    picked = picks.get(final.id) if final else None
    champion = picked if picked in finalists else None
    runner_up = next((w for w in finalists if w != champion), None) if champion else None
    return champion, runner_up


async def _tml_id_of(db, entry_id: Optional[int]) -> tuple[Optional[str], Optional[str]]:
    """(TennisMyLife id, display name) for a draw entry, through its Tennis Explorer row."""
    if not entry_id:
        return None, None
    entry = await db.get(DrawEntry, entry_id)
    if entry is None:
        return None, None
    name = getattr(entry, "display_name", None) or entry.name
    if entry.te_player_id:
        tp = await db.get(TePlayer, entry.te_player_id)
        if tp is not None and tp.tml_player_id:
            return tp.tml_player_id, name
    return None, name


@router.get("/{tournament_id}/final-guess")
async def get_final_guess(tournament_id: int, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    """THE THREE TIEBREAK QUESTIONS AND WHAT TO ANSWER THEM WITH.

    Every figure is conditioned on THIS draw — its tour, its tier, its surface
    — and on the two players this bracket picked for the final. A WTA 250 on
    clay is never answered with ATP hard numbers.

    Two kinds of figure, from two places. The draw-level ones (how many sets a
    final here goes, the aces and minutes per set) are the same for every
    reader and are cached on the draw by a scheduler sweep
    (services/final_reference). The per-finalist ones depend on who was picked,
    so they are fetched live — and they are the only history queries a normal
    open costs.
    """
    from app.services import final_reference
    from app.services.history import db as hdb
    from app.services.history.final_stats import (
        RATE_YEARS, ceilings, estimate_minutes, h2h_set_minutes, h2h_sets,
        head_to_head, player_rates, set_lengths,
    )
    from app.services.history.link import norm_surface
    from app.services.locking import draw_lock_state
    from app.services.schedule import _best_of

    draw = await db.get(Draw, tournament_id)
    if draw is None:
        raise HTTPException(status_code=404, detail="Draw not found")
    tour = "wta" if (draw.gender or "").upper() == "F" else "atp"
    surface = norm_surface(draw.surface)
    best_of = _best_of(draw, "singles", "main")
    tier = draw.scoring_tier

    matches = (await db.execute(select(Match).where(Match.draw_id == tournament_id))).scalars().all()
    preds = (await db.execute(select(UserPrediction).where(
        UserPrediction.draw_id == tournament_id, UserPrediction.user_id == current_user.id))).scalars().all()
    picks = {p.match_id: p.predicted_winner_id for p in preds if p.predicted_winner_id is not None}
    champion_id, runner_up_id = predicted_finalists(picks, matches, draw.num_rounds)
    champ_tml, champ_name = await _tml_id_of(db, champion_id)
    run_tml, run_name = await _tml_id_of(db, runner_up_id)

    # Cached, and never written from this read (feedback_reads_must_not_write).
    tier_ref = await final_reference.for_draw(db, draw)

    def _read(conn):
        """The per-finalist half — the only part that cannot be cached."""
        from app.services.history.final_stats import default_guess
        h2h_min = (h2h_set_minutes(conn, tour, champ_tml, run_tml, surface)
                   if champ_tml and run_tml else None)
        return {
            "default": default_guess(conn, tour, surface, best_of),
            "ceilings": ceilings(conn, tour, surface, best_of),
            "h2h": head_to_head(conn, tour, champ_tml, run_tml),
            "h2h_sets": (h2h_sets(conn, tour, champ_tml, run_tml, surface)
                         if champ_tml and run_tml else None),
            "h2h_set_minutes": h2h_min,
            # The champion's own rates, and theirs against this opponent.
            "champion_on_surface": (player_rates(conn, tour, champ_tml, surface, RATE_YEARS)
                                    if champ_tml else None),
            "champion_vs": (player_rates(conn, tour, champ_tml, surface, RATE_YEARS,
                                         opponent_tml_id=run_tml)
                            if champ_tml and run_tml else None),
        }

    try:
        live = await hdb.run(_read)
    except Exception:       # noqa: BLE001 — history is a convenience, not the page
        live = {k: None for k in ("default", "ceilings", "h2h", "h2h_sets",
                                  "h2h_set_minutes", "champion_on_surface", "champion_vs")}

    guess = (await db.execute(select(DrawFinalGuess).where(
        DrawFinalGuess.draw_id == tournament_id, DrawFinalGuess.user_id == current_user.id))).scalars().first()
    lock = await draw_lock_state(db, draw)

    _lengths = set_lengths(best_of)
    tier_label = {"GS": "Grand Slam", "1000": f"{tour.upper()} 1000",
                  "500": f"{tour.upper()} 500", "250": f"{tour.upper()} 250"}.get(tier, tier)
    h2h_min = live["h2h_set_minutes"]
    return {
        "draw_id": tournament_id, "tour": tour.upper(), "surface": surface, "best_of": best_of,
        "tier": tier, "tier_label": tier_label,
        "locked": bool(lock.draw_locked) or draw.status == "completed",
        "champion": {"entry_id": champion_id, "name": champ_name, "has_history": bool(champ_tml)},
        "runner_up": {"entry_id": runner_up_id, "name": run_name, "has_history": bool(run_tml)},
        # ANSWERED FOR A DIFFERENT FINAL (owner, 2026-09-22). The questions are
        # about two named players, so a pick that changes who reaches the final
        # invalidates the answers — and nothing used to say so. The clients
        # colour their way in when this is true.
        #
        # False unless we can PROVE it: no guess, or a row saved before the
        # finalists were stamped, or a draw already locked (where nothing can
        # be done about it) all read false. Order matters — swapping who wins
        # the final changes who the aces question is about.
        "stale": answers_are_stale(
            guess, champion_id, runner_up_id,
            locked=bool(lock.draw_locked) or draw.status == "completed"),
        "answered_for": ({"champion_entry_id": guess.final_a_entry_id,
                          "runner_up_entry_id": guess.final_b_entry_id}
                         if guess is not None and guess.final_a_entry_id is not None else None),
        # ── The three questions, each with only the figures it needs ────────
        "sets_question": {
            "tier_finals": (tier_ref or {}).get("sets"),
            "h2h": live["h2h_sets"],
        },
        "aces_question": {
            # Per SET; the client multiplies by the sets the reader chose, as
            # the owner specified, so the figure follows question one's answer.
            "tier_finals": (tier_ref or {}).get("rates"),
            "champion_vs": live["champion_vs"],
            "champion_on_surface": live["champion_on_surface"],
        },
        "minutes_question": {
            "tier_finals": (tier_ref or {}).get("rates"),
            # Already multiplied out per set count, from the cache.
            "tier_minutes_by_sets": (tier_ref or {}).get("minutes_by_sets"),
            # EVERY DURATION ROW IS MODELLED THE SAME WAY (owner, 2026-09-19):
            # playing time per set, times the predicted sets, plus a changeover
            # between each pair of them. Pre-computed for every length this
            # format allows, so the client does no arithmetic and cannot get
            # the break count wrong.
            "champion_on_surface": (None if not live["champion_on_surface"] else {
                **live["champion_on_surface"],
                "by_sets": {str(n): estimate_minutes(
                    live["champion_on_surface"].get("play_minutes_per_set"), n)
                    for n in _lengths},
            }),
            "h2h_estimate": (None if not h2h_min else {
                "play_minutes_per_set": h2h_min["play_minutes_per_set"],
                "matches": h2h_min["matches"],
                "by_sets": {str(n): estimate_minutes(h2h_min["play_minutes_per_set"], n)
                            for n in _lengths},
            }),
        },
        # Every match the two picked finalists have played, most recent first.
        "h2h": live["h2h"],
        "ceilings": live["ceilings"],
        # What this bracket is taken to have said if it never answers.
        "default": live["default"],
        "guess": ({"final_sets": guess.final_sets, "final_aces": guess.final_aces,
                   "final_duration_min": guess.final_duration_min} if guess else None),
        "actual": ({"final_sets": draw.final_sets, "final_aces": draw.final_winner_aces,
                    "final_duration_min": draw.final_duration_min}
                   if final_tiebreak.final_played(draw) else None),
    }


@router.put("/{tournament_id}/final-guess")
async def put_final_guess(tournament_id: int, body: FinalGuessIn, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    from app.services.locking import draw_lock_state

    draw = await db.get(Draw, tournament_id)
    if draw is None:
        raise HTTPException(status_code=404, detail="Draw not found")
    lock = await draw_lock_state(db, draw)
    if lock.draw_locked or draw.status == "completed":
        raise HTTPException(status_code=409, detail="Picks are locked for this draw")
    # THE FINAL THESE ANSWERS ARE ABOUT, recorded with them. Read from the
    # user's own picks at save time, exactly as the GET reads it, so the two
    # can be compared later without either guessing what the other meant.
    matches = (await db.execute(select(Match).where(Match.draw_id == tournament_id))).scalars().all()
    preds = (await db.execute(select(UserPrediction).where(
        UserPrediction.draw_id == tournament_id,
        UserPrediction.user_id == current_user.id))).scalars().all()
    picks = {p.match_id: p.predicted_winner_id for p in preds if p.predicted_winner_id is not None}
    champion_id, runner_up_id = predicted_finalists(picks, matches, draw.num_rounds)
    guess = (await db.execute(select(DrawFinalGuess).where(
        DrawFinalGuess.draw_id == tournament_id, DrawFinalGuess.user_id == current_user.id))).scalars().first()
    if guess is None:
        guess = DrawFinalGuess(user_id=current_user.id, draw_id=tournament_id,
                               final_sets=body.final_sets,
                               final_aces=body.final_aces, final_duration_min=body.final_duration_min,
                               final_a_entry_id=champion_id, final_b_entry_id=runner_up_id)
        db.add(guess)
    else:
        guess.final_a_entry_id, guess.final_b_entry_id = champion_id, runner_up_id
        # Only overwrite sets when the client sent one: an older client
        # omitting the field must not erase an answer already given.
        if body.final_sets is not None:
            guess.final_sets = body.final_sets
        guess.final_aces = body.final_aces
        guess.final_duration_min = body.final_duration_min
    await db.commit()
    return {"final_aces": guess.final_aces, "final_duration_min": guess.final_duration_min}
