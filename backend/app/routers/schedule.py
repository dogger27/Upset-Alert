"""
Order-of-play schedule.

Note what is NOT here: `printed_score` and `printed_status`. The sheet's own
score is a snapshot from whenever that revision was published and can be hours
stale, so it is never shown to a user — ESPN is the only score anyone sees.
Those columns exist purely to anchor expected-start estimates on courts ESPN
does not cover. Leaving them out of the response model, rather than filtering
them at render time, is what keeps that true when someone later adds a field.
"""

import re as _re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_optional_user
from app.database import get_db
from app.models.schedule import ScheduleEntry
from app.models.rankings import TePlayer, TeRankingsSnapshot
from app.models.tournament import Draw, DrawEntry, Match, Tournament
from app.services.sofascore_live import live_point_for

router = APIRouter(prefix="/schedule", tags=["schedule"])


class SchedulePlayerOut(BaseModel):
    side: str
    position: int
    name: str
    draw_entry_id: Optional[int] = None
    # From our own draw_entries, not from the printed name. The sheet drops the
    # country whenever space is tight — abbreviated "OR" slots especially — and
    # a resolved slot carries the bracket's name, which never had one inline.
    # Stays null for players we genuinely hold no country for, which is how
    # neutral athletes keep no flag.
    nationality: Optional[str] = None
    # Seeding and entry status as data rather than as "[17] " on the front of
    # the name. The bracket is preferred where the player resolved; the sheet
    # is the only source for doubles teams and qualifiers, who have no
    # draw_entries row at all.
    seed: Optional[int] = None
    entry_type: Optional[str] = None
    # For the H2H panel. Deliberately NOT what gates the button — an unmatched
    # player would otherwise take head-to-head away from a match that is
    # actually being played. Null means "no Tennis Explorer match", and the
    # panel shows what it can.
    te_slug: Optional[str] = None
    # The rest of what H2HPanel shows — rank, Elo rank, age — so head-to-head
    # opened from here is the same panel it is on the draw page rather than a
    # thinner one. Without these it rendered with the comparison rows missing
    # and no explanation for why.
    ranking: Optional[int] = None
    elo_rank: Optional[int] = None
    date_of_birth: Optional[date] = None
    # The BRACKET's name, clean, beside the sheet's own. The row keeps printing
    # the sheet's typography ("[7] Iga SWIATEK POL"); the panel wants
    # "Iga Świątek", with the diacritics the sheet drops.
    entry_name: Optional[str] = None


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
    # Verbatim from the sheet; the court view prints this as-is.
    start_note: Optional[str] = None
    # The printed clock as a real instant, so the client can show "Not before
    # 3:00 PM" in the reader's own zone as well as the venue's. Without it the
    # note is just text and a time-zone switch cannot touch it.
    printed_start_at: Optional[datetime] = None
    # Computed chain — the sort key for the time view. `expected_source` tells
    # the client whether to render it firmly ("3:00 PM") or hedged ("~4:15 PM").
    expected_start_at: Optional[datetime] = None
    expected_source: Optional[str] = None
    # When the match was actually first seen on court. Only main-draw singles
    # carry this — ESPN is the source and it covers nothing else — and only from
    # the moment we started recording it, so the client must fall back.
    started_at: Optional[datetime] = None
    is_tbd: bool = False
    tbd_side: Optional[str] = None
    status: str = "scheduled"
    players: list[SchedulePlayerOut] = []
    # ESPN only. Absent for doubles and qualifying, which it does not cover.
    live_scores: Optional[list] = None
    scores: Optional[list] = None
    # The point score, on the same terms as the draw page — and from the same
    # helper, so this page and the bracket can never disagree about a match they
    # are both showing. Carries its own `games`, which the client prefers over
    # live_scores when present.
    live_point: Optional[dict] = None
    # The draw's own surface and gender. H2HPanel needs the surface for its
    # per-surface comparison row and the gender to label the ranking column —
    # without them it renders a thinner panel than the draw page does, with
    # nothing on screen to explain the difference.
    surface: Optional[str] = None
    gender: Optional[str] = None


class ScheduleDayOut(BaseModel):
    play_date: date
    entries: list[ScheduleEntryOut]
    courts: list[str]
    tournaments: list[dict]


_CLOCK_RE = _re.compile(r'^(\d{1,2})[:.](\d{2})\s*(am|pm)?$', _re.I)


_MARK_RE = _re.compile(r"\[([^\]]+)\]")


def _printed_mark(raw: str) -> tuple:
    """(seed, entry_type) as the sheet printed them.

    The only source for a doubles team or a qualifier, neither of which has a
    draw_entries row to read a seeding off. A name can carry both markers —
    "[WC] [2]" — so digits and codes are collected separately rather than by
    taking the first bracket.
    """
    seed = None
    etype = None
    for m in _MARK_RE.finditer(raw or ""):
        value = m.group(1).strip()
        if value.isdigit():
            if seed is None:
                seed = int(value)
        elif value:
            etype = value.upper()
    return seed, etype


def _player_out(p, nats: dict, seeds: dict, types: dict, from_bracket: bool,
                slugs: dict = None, extra: dict = None):
    """One player, preferring what the bracket knows over what the sheet printed.

    `from_bracket` is false for anything but main-draw singles. A doubles
    player still resolves to a draw_entries row — their own singles entry, the
    only one this tournament has — and reading a seeding off it puts a SINGLES
    seed on a DOUBLES team: Siniakova/Townsend are the [1] seeds in the doubles
    and she is [33] in the singles. Qualifying is seeded separately again. In
    both, the sheet is the only source that is about the event being played.
    """
    seed, etype = _printed_mark(p.raw_name)
    if from_bracket:
        seed = seeds.get(p.draw_entry_id) or seed
        etype = types.get(p.draw_entry_id) or etype
    return SchedulePlayerOut(
        side=p.side, position=p.position,
        name=p.raw_name,
        draw_entry_id=p.draw_entry_id,
        nationality=nats.get(p.draw_entry_id),
        seed=seed,
        entry_type=etype,
        te_slug=(slugs or {}).get(p.draw_entry_id),
        **((extra or {}).get(p.draw_entry_id) or {}),
    )


def _printed_instant(entry, tz_name: Optional[str]) -> Optional[datetime]:
    """The slot's printed clock as a UTC instant, or None.

    The sheet prints venue-local wall time. Turning it into an instant is what
    lets the client render the same moment in whichever zone the reader picks.
    """
    if not entry.start_time_local or not tz_name:
        return None
    m = _CLOCK_RE.match(entry.start_time_local.strip())
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        return None
    return datetime.combine(entry.play_date, time(hour, minute), tzinfo=tz).astimezone(timezone.utc)


def _utc(dt):
    """Stamp UTC on a naive datetime before it is serialised.

    SQLite hands these back without an offset, and an ISO string with no zone
    is parsed by the browser as LOCAL time — so an 18:00 UTC start renders as
    18:00 wherever the reader happens to be. Everything stored here is UTC.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _doubles_point(entry) -> Optional[dict]:
    """The live point for a doubles row, on the same freshness terms as singles.

    A point is worthless once it is stale — it sits on 15-30 for a whole game
    and contradicts the set score beside it — so the same rule applies whether
    the match has a bracket row or not.
    """
    from app.services.sofascore_live import FRESH_SECONDS

    snap = getattr(entry, "live_point_json", None)
    if not snap or getattr(entry, "winner_side", None):
        return None
    try:
        at = datetime.fromisoformat(snap["at"])
    except (KeyError, TypeError, ValueError):
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - at).total_seconds() > FRESH_SECONDS:
        return None
    point = snap.get("point") or [None, None]
    if not any(p is not None for p in point):
        return None
    sets = snap.get("sets") or []
    games = [[str(s[0]) if s and s[0] is not None else "" for s in sets],
             [str(s[1]) if s and s[1] is not None else "" for s in sets]]
    return {"point": point, "games": games if sets else None,
            "tiebreak": bool(snap.get("tiebreak")), "serving": snap.get("serving")}


def _status_of(entry, match) -> str:
    """Live state comes from the MATCH, not from the schedule row.

    schedule_entries.status was only ever written as "scheduled" — the ingest
    has no idea what is happening on court. ESPN does, and it already writes
    both of these onto the match every 60 seconds.
    """
    if match is not None:
        if getattr(match, "winner_id", None):
            return "completed"
        if getattr(match, "live_scores_json", None):
            return "live"
    else:
        # Doubles: the row IS the record, so its own columns decide.
        if getattr(entry, "winner_side", None):
            return "completed"
        if getattr(entry, "live_scores_json", None):
            return "live"
    return entry.status or "scheduled"


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

    ent_ids = {p.draw_entry_id for e in entries for p in e.players if p.draw_entry_id}
    nats = {}
    ent_seeds = {}
    ent_types = {}
    ent_slugs = {}
    ent_extra = {}
    if ent_ids:
        rows = (await db.execute(
            select(DrawEntry.id, DrawEntry.nationality,
                   DrawEntry.seed, DrawEntry.entry_type, DrawEntry.te_slug,
                   DrawEntry.ranking, DrawEntry.te_player_id,
                   DrawEntry.name).where(
                DrawEntry.id.in_(ent_ids)))).all()
        nats = {r[0]: r[1] for r in rows if r[1]}
        # Seeding from the bracket, so it survives a name that never carried it.
        # The printed name is otherwise left alone: the client already turns
        # "[17] Frances TIAFOE USA" into a badge, a name and a flag, and the
        # capitalised surname it lays out is the page's own typography. What
        # went missing was the seeding on rows whose name came from US — a slot
        # resolved from "Tien OR Tiafoe" carries the bracket's name, and the
        # bracket writes no "[17]" into it.
        ent_seeds = {r[0]: r[2] for r in rows if r[2]}
        ent_types = {r[0]: r[3] for r in rows if r[3]}
        ent_slugs = {r[0]: r[4] for r in rows if r[4]}

        # Age and Elo come from the Tennis Explorer tables, exactly as the draw
        # page sources them. Elo is read from the LATEST snapshot here rather
        # than one pinned to a tournament's ranking week: the schedule only ever
        # shows play happening now, so "now" is the right reference.
        te_ids = [r[6] for r in rows if r[6]]
        dobs, elos = {}, {}
        if te_ids:
            for row in (await db.execute(
                    select(TePlayer.id, TePlayer.date_of_birth)
                    .where(TePlayer.id.in_(te_ids)))).all():
                if row[1]:
                    dobs[row[0]] = row[1]
            newest = select(func.max(TeRankingsSnapshot.week_date)).where(
                TeRankingsSnapshot.player_id.in_(te_ids))
            for row in (await db.execute(
                    select(TeRankingsSnapshot.player_id, TeRankingsSnapshot.elo_rank)
                    .where(TeRankingsSnapshot.player_id.in_(te_ids),
                           TeRankingsSnapshot.elo_rank.isnot(None),
                           TeRankingsSnapshot.week_date == newest.scalar_subquery()))).all():
                if row[1]:
                    elos[row[0]] = row[1]
        ent_extra = {
            r[0]: {
                "ranking": r[5],
                "elo_rank": elos.get(r[6]) if r[6] else None,
                "date_of_birth": dobs.get(r[6]) if r[6] else None,
                "entry_name": r[7],
            } for r in rows
        }

    draw_meta = {r[0]: (r[1], r[2]) for r in (await db.execute(
        select(Draw.id, Draw.surface, Draw.gender).where(
            Draw.tournament_id.in_(t_ids)))).all()}

    tz_rows = (await db.execute(
        select(Draw.tournament_id, Draw.venue_timezone).where(
            Draw.tournament_id.in_(t_ids), Draw.venue_timezone.isnot(None)))).all()
    tzs = {r[0]: r[1] for r in tz_rows}

    match_ids = {e.match_id for e in entries if e.match_id}
    matches = {}
    if match_ids:
        rows = (await db.execute(
            select(Match).where(Match.id.in_(match_ids)))).scalars().all()
        matches = {m.id: m for m in rows}

    # Status from the match where we have one, then filled in from ORDERING.
    #
    # ESPN covers neither doubles nor qualifying, so those slots have no match
    # and would sit at "scheduled" all day. But a court runs in order: if a
    # later slot is under way, everything above it on that court has finished.
    # That is a fact about the running order rather than a guess, which is the
    # only basis on which a status is worth showing for a match we cannot see.
    statuses = {e.id: _status_of(e, matches.get(e.match_id) if e.match_id else None)
                for e in entries}
    court_groups: dict[str, list] = {}
    for e in entries:
        court_groups.setdefault(e.court or '', []).append(e)
    for slots in court_groups.values():
        # Only a STRICTLY later slot proves an earlier one finished. Positions
        # can collide — a sheet revised during the day renumbers only the
        # matches it still lists, so an entry carried over from an earlier
        # revision can share a position with a current one. Treating equal
        # positions as "later" marked a match that had not started as
        # completed, because the match beside it had.
        highest_started = None
        for e in sorted(slots, key=lambda x: x.court_order):
            if statuses[e.id] in ("live", "completed"):
                highest_started = e.court_order
        if highest_started is None:
            continue
        for e in slots:
            if e.court_order < highest_started and statuses[e.id] == "scheduled":
                statuses[e.id] = "completed"

    out: list[ScheduleEntryOut] = []
    courts: list[str] = []
    for e in entries:
        if e.court and e.court not in courts:
            courts.append(e.court)
        m = matches.get(e.match_id) if e.match_id else None
        players = [
            _player_out(p, nats, ent_seeds, ent_types,
                        e.discipline == "singles" and e.stage == "main",
                        ent_slugs, ent_extra)
            for p in sorted(e.players, key=lambda x: (x.side, x.position))
        ]
        out.append(ScheduleEntryOut(
            id=e.id, tournament_id=e.tournament_id,
            tournament_name=t_names.get(e.tournament_id),
            draw_id=e.draw_id, match_id=e.match_id, play_date=e.play_date,
            tour=e.tour, stage=e.stage, discipline=e.discipline,
            round_label=e.round_label, court=e.court, court_order=e.court_order,
            start_type=e.start_type, start_time_local=e.start_time_local,
            start_note=e.start_note,
            printed_start_at=_printed_instant(e, tzs.get(e.tournament_id)),
            expected_start_at=_utc(e.expected_start_at), expected_source=e.expected_source,
            # Singles reads it off the match; doubles has none and carries its
            # own, so the field means the same thing either way.
            started_at=_utc(getattr(m, "started_at", None) if m else e.started_at),
            is_tbd=e.is_tbd, tbd_side=e.tbd_side, status=statuses[e.id], players=players,
            # Singles reads through the match; doubles has none and carries its
            # own result on the row. Same field names either way, so the client
            # needs no idea which kind of match it is looking at.
            live_scores=(m.live_scores_json if m else e.live_scores_json),
            live_point=(live_point_for(m) if m else _doubles_point(e)),
            scores=(m.scores_json if m else e.scores_json),
            surface=(draw_meta.get(e.draw_id) or (None, None))[0],
            gender=(draw_meta.get(e.draw_id) or (None, None))[1],
        ))

    # The official PDF stays one tap away — the page replaces it as the primary
    # destination, it does not hide it.
    pdf_rows = (await db.execute(
        select(Draw.tournament_id, Draw.oop_url).where(
            Draw.tournament_id.in_(t_ids), Draw.oop_url.isnot(None)))).all()
    pdfs = {r[0]: r[1] for r in pdf_rows}


    return ScheduleDayOut(
        play_date=day, entries=out, courts=courts,
        tournaments=[{"id": i, "name": t_names.get(i), "oop_url": pdfs.get(i),
                      "venue_timezone": tzs.get(i)}
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
