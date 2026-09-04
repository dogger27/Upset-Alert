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
from datetime import date, datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_optional_user
from app.database import get_db
from app.models.schedule import ScheduleEntry, ScheduleEntryPlayer
from app.models.rankings import TePlayer, TeRankingsSnapshot
from app.services.schedule import settle_from_result_rows, settled_sides_index
from app.services.rankings import _norm
from app.models.tournament import Draw, DrawEntry, Match, Tournament
from app.models.prediction import UserPrediction
from app.services.system_log import app_log
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
    # The INFERRED seed — where this player sits once the whole field is
    # ordered, which is what the bracket's grey badge shows. Main-draw singles
    # only, for the same reason `seed` is: see _player_out.
    draw_rank: Optional[int] = None
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
    # WHEN PLAY CAME BACK, for a match that was suspended and picked up again.
    # started_at stays at the first point of the match, because that is what it
    # means; a row on the day of the resumption needs this instead, or it
    # prints yesterday afternoon as its start time.
    resumed_at: Optional[datetime] = None
    # When it FINISHED, for clients that want to react to a result rather than
    # merely display one. A phone discards a backgrounded tab and reloads it, so
    # "we watched the status change" is a fact the browser is often not around
    # to observe; a timestamp is one the page can check on arrival. Only set
    # where a real result was recorded — a status inferred from the court order
    # below leaves this null rather than guessing an instant.
    completed_at: Optional[datetime] = None
    is_tbd: bool = False
    tbd_side: Optional[str] = None
    status: str = "scheduled"
    players: list[SchedulePlayerOut] = []
    # ESPN only. Absent for doubles and qualifying, which it does not cover.
    live_scores: Optional[list] = None
    scores: Optional[list] = None
    # WHO WON, stated rather than inferred. The client used to count sets, so
    # a result with no sets to count — a walkover — showed no winner at all.
    # Singles reads it off the bracket match, doubles off the row.
    winner_side: Optional[int] = None
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
    # THE SIGNED-IN USER'S PICK for this match: the draw_entry_id they chose to
    # win, or null (nobody signed in, no pick, or a match nobody predicts —
    # doubles and qualifying have no bracket match). The card marks that
    # player. Everyone picks every match, so on a main-draw day this is set on
    # nearly every singles row.
    pick_entry_id: Optional[int] = None


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


_NAME_TAGS = _re.compile(r"\[[^\]]*\]")
_TRAILING_CAPS = _re.compile(r"[A-Z]{3}$")


def _name_key(raw: str) -> str:
    """A sheet name reduced to something a Tennis Explorer name can be compared to.

    "[1] Maya JOINT AUS" -> "maya joint". The sheet prints an entry tag, given
    names normally, the surname in capitals and a country code; TE prints
    "Maya Joint". Only the words are common to both.

    The trailing three-letter capital is a COUNTRY only when a surname already
    precedes it — the same rule the order-of-play parser and the frontend use,
    and for the same reason: strip every one of them and "Luca POW GBR" loses
    the player, along with LUZ, GUO, RAM and LEE.
    """
    toks = [t for t in _NAME_TAGS.sub(" ", raw or "").split() if len(t) >= 2]
    if (len(toks) >= 2 and _TRAILING_CAPS.match(toks[-1])
            and any(t.isupper() for t in toks[:-1])):
        toks = toks[:-1]
    return _norm(" ".join(toks))


async def _profiles_by_name(db, raws: list) -> dict:
    """Rank, Elo rank and date of birth for players the bracket does not know.

    Same matching rule as _slugs_by_name and for the same reason — the whole
    name, one candidate or nothing — because attaching another player's ranking
    is the same mistake as attaching their head-to-head.

    Without this the H2H panel opened from the ORDER OF PLAY showed a
    qualifying match with its comparison rows blank: the panel reads rank, Elo
    and age off the player object, and those were only ever filled in from a
    draw_entries row. Qualifying has none — a 128-draw stores rounds 1-7, and
    players who fail to qualify never reach it at all — so every qualifying
    match rendered a thinner panel with no explanation. The head-to-head record
    itself was already resolving by name, which is what made the gap look
    arbitrary rather than absent.
    """
    keys = {k for k in (_name_key(r) for r in raws) if k}
    if not keys:
        return {}
    surnames = {k.split()[-1] for k in keys if k.split()}
    rows = (await db.execute(
        select(TePlayer.id, TePlayer.name_display, TePlayer.date_of_birth)
        .where(func.lower(TePlayer.last_name).in_(surnames)))).all()
    by_key: dict = {}
    for te_id, display, dob in rows:
        k = _norm(display or "")
        if k not in keys:
            continue
        by_key[k] = None if k in by_key else (te_id, dob)
    matched = {k: v for k, v in by_key.items() if v}
    if not matched:
        return {}

    te_ids = [v[0] for v in matched.values()]
    # Newest week we hold, same reference the bracket-linked players use.
    newest = select(func.max(TeRankingsSnapshot.week_date)).where(
        TeRankingsSnapshot.player_id.in_(te_ids))
    ranks, elos = {}, {}
    for pid, rank, elo in (await db.execute(
            select(TeRankingsSnapshot.player_id, TeRankingsSnapshot.rank,
                   TeRankingsSnapshot.elo_rank)
            .where(TeRankingsSnapshot.player_id.in_(te_ids),
                   TeRankingsSnapshot.week_date == newest.scalar_subquery()))).all():
        if rank:
            ranks[pid] = rank
        if elo:
            elos[pid] = elo
    return {
        k: {"ranking": ranks.get(te_id), "elo_rank": elos.get(te_id),
            "date_of_birth": dob}
        for k, (te_id, dob) in matched.items()
    }


async def _slugs_by_name(db, raws: list) -> dict:
    """te_slug for players the bracket does not know, matched on the WHOLE name.

    Whole name, never a surname: te_slug is not unique, the table holds both
    tours, and "Joint" alone is the kind of match that quietly attaches one
    player's head-to-head record to another. A full-name match that finds
    exactly one candidate is safe; anything else is left unresolved, which is
    the honest answer and the state this replaces anyway.
    """
    keys = {k for k in (_name_key(r) for r in raws) if k}
    if not keys:
        return {}
    surnames = {k.split()[-1] for k in keys if k.split()}
    rows = (await db.execute(
        select(TePlayer.te_slug, TePlayer.name_display).where(
            func.lower(TePlayer.last_name).in_(surnames),
            TePlayer.te_slug.isnot(None)))).all()
    hits: dict = {}
    for slug, display in rows:
        k = _norm(display or "")
        if k not in keys:
            continue
        # Two people spelled the same way is exactly the case to walk away from.
        hits[k] = None if k in hits else slug
    return {k: v for k, v in hits.items() if v}


def _player_out(p, nats: dict, seeds: dict, types: dict, ranks: dict, from_bracket: bool,
                slugs: dict = None, extra: dict = None, by_name: dict = None,
                extra_by_name: dict = None):
    """One player, preferring what the bracket knows over what the sheet printed.

    `from_bracket` is false for anything but main-draw singles. A doubles
    player still resolves to a draw_entries row — their own singles entry, the
    only one this tournament has — and reading a seeding off it puts a SINGLES
    seed on a DOUBLES team: Siniakova/Townsend are the [1] seeds in the doubles
    and she is [33] in the singles. Qualifying is seeded separately again. In
    both, the sheet is the only source that is about the event being played.
    """
    seed, etype = _printed_mark(p.raw_name)
    draw_rank = None
    if from_bracket:
        seed = seeds.get(p.draw_entry_id) or seed
        etype = types.get(p.draw_entry_id) or etype
        # Behind the SAME guard as `seed`, and for the same reason: a doubles
        # or qualifying row resolves to the player's SINGLES draw_entries row,
        # so an inferred seed read off it would describe a different event
        # entirely — the exact mistake the seeding guard above exists to stop.
        draw_rank = ranks.get(p.draw_entry_id)
    return SchedulePlayerOut(
        side=p.side, position=p.position,
        name=p.raw_name,
        draw_entry_id=p.draw_entry_id,
        nationality=nats.get(p.draw_entry_id) or p.nationality,
        seed=seed,
        draw_rank=draw_rank,
        entry_type=etype,
        # By draw entry where there is one; by NAME where there is not.
        # Qualifying has no draw_entries row — a 128-draw stores rounds 1-7 and
        # players who fail to qualify never reach it at all — so every
        # qualifying row reported "no Tennis Explorer profile" for players who
        # plainly have one. Maya Joint is te_players 2322.
        te_slug=((slugs or {}).get(p.draw_entry_id)
                 or (by_name or {}).get(_name_key(p.raw_name))),
        # By draw entry where there is one, by NAME where there is not — the
        # same fallback te_slug above already had.
        **((extra or {}).get(p.draw_entry_id)
           or (extra_by_name or {}).get(_name_key(p.raw_name))
           or {}),
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


def _is_suspended(entry, match) -> bool:
    """Has play on this match STOPPED, wherever the fact is recorded?

    Two spellings, because two feeds write it. ESPN parks the word in the fifth
    slot of a match's live_scores_json; the point payload carries its own flag,
    which is the only one a doubles row has. A match carried overnight has the
    first and no live point at all, so testing either alone misses half of them.
    """
    ls = getattr(match, "live_scores_json", None) if match is not None else None
    if isinstance(ls, (list, tuple)) and len(ls) > 4 and ls[4] == "suspended":
        return True
    return bool((_doubles_point(entry) or {}).get("suspended"))


def _doubles_point(entry):
    """The live point for a doubles row, which has no bracket match to carry it.

    Same rules as singles, and literally the same code — see renderable_point.
    The two were separate copies until the doubles one fell behind by a field.
    """
    from app.services.sofascore_live import ENTRY_FRESH_SECONDS, renderable_point

    return renderable_point(getattr(entry, "live_point_json", None),
                            bool(getattr(entry, "winner_side", None)),
                            max_age=ENTRY_FRESH_SECONDS)


def _has_games(live_scores) -> bool:
    """Has anybody won a game in this match yet?

    live_scores is [p1 games, p2 games, serving, set winners]; a match that
    has begun has a non-zero entry in one of the first two.
    """
    for side in (live_scores or [])[:2]:
        for cell in (side or []):
            try:
                if int(str(cell).strip() or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _flip_sides(out: dict) -> dict:
    """The same snapshot read from the other end of the sheet.

    Snapshots are stored in the orientation of the ROW that recorded them, and
    two days' sheets are free to print a pairing in opposite order. Merging a
    match's days without this would hand the popup a timeline that swaps ends
    partway through.
    """
    g = out.get("games")
    if isinstance(g, list) and len(g) == 2:
        out["games"] = [g[1], g[0]]
    p = out.get("point")
    if isinstance(p, list) and len(p) == 2:
        out["point"] = [p[1], p[0]]
    if out.get("serving") in (1, 2):
        out["serving"] = 3 - out["serving"]
    return out


def _carried_point(src: dict):
    """The abandoned day's point, rendered for a row that is inheriting it.

    Same shape the live path produces, minus the freshness test: this score is
    deliberately old — it is where play stopped — so ageing it out would empty
    the very row the reader came to see.
    """
    from app.services.sofascore_live import _render_snapshot
    snap = src.get("point")
    if not snap:
        return None
    out = _render_snapshot(snap)
    if out is not None:
        # Normally this score is frozen at the abandonment — but the moment the
        # source row's claim sees play restart, the very same borrowed score is
        # a LIVE one. Take the source's word for it instead of asserting it:
        # hardcoding True left resumed matches reading "Suspended" over a score
        # that was visibly ticking. Absent flag keeps the old meaning, so
        # payloads written before the flag existed still read as suspended.
        out["suspended"] = bool(snap.get("suspended", True))
    return out


def _pairing_surname(raw_name: str) -> str:
    """The surname as both sheets spell it, so one day's row and the next
    day's row for the same match produce the same signature."""
    return _norm(raw_name or "").split()[-1] if (raw_name or "").strip() else ""


def _aware_dt(dt):
    """SQLite hands datetimes back naive; treat them as the UTC they were."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _venue_today(tz_name: Optional[str]) -> date:
    """Today's date AT THE VENUE. A UTC date would call a night session's
    matches postponed from 8pm local, while they are still being played."""
    now = datetime.now(timezone.utc)
    try:
        return now.astimezone(ZoneInfo(tz_name)).date() if tz_name else now.date()
    except Exception:
        return now.date()


def _status_of(entry, match) -> str:
    """Live state comes from the MATCH, not from the schedule row.

    schedule_entries.status was only ever written as "scheduled" — the ingest
    has no idea what is happening on court. ESPN does, and it already writes
    both of these onto the match every 60 seconds.
    """
    if match is not None:
        if getattr(match, "winner_id", None):
            return "completed"
        # ESPN's field, or a FRESH Sofascore point (live_point_for returns
        # None once the snapshot is stale, so this cannot resurrect a match
        # the feed has forgotten). Either is a match being played.
        if getattr(match, "live_scores_json", None) or live_point_for(match):
            return "live"
    else:
        # Doubles: the row IS the record, so its own columns decide.
        if getattr(entry, "winner_side", None):
            return "completed"
        if getattr(entry, "live_scores_json", None):
            return "live"
    return entry.status or "scheduled"


def _winner_side(entry, match, players) -> Optional[int]:
    """0 or 1 — the side that won, or None while undecided.

    Singles carries the result on its bracket match, so the winning draw
    entry is matched against the row's own side-a players; doubles and
    qualifying carry `winner_side` on the row itself. Either way the answer
    is stated by the record, not reconstructed from a scoreline that a
    walkover or a retirement may not have.
    """
    if match is not None and getattr(match, "winner_id", None) is not None:
        # `players` are SchedulePlayerOut models here, not dicts — reading them
        # with .get() raised AttributeError and 500'd the whole day endpoint
        # the moment a linked singles match finished. Attribute access works
        # for either shape.
        def _field(p, key):
            return p.get(key) if isinstance(p, dict) else getattr(p, key, None)
        a_ids = {_field(p, "draw_entry_id") for p in players
                 if _field(p, "side") == "a" and _field(p, "draw_entry_id")}
        if a_ids:
            return 0 if match.winner_id in a_ids else 1
        return None
    ws = getattr(entry, "winner_side", None)
    return {"a": 0, "b": 1}.get(ws) if isinstance(ws, str) else None


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

    # An inferred seed is a player's place once the ENTIRE field is ordered, so
    # unlike everything else here it cannot be looked up per player — the whole
    # draw has to be loaded. Two draws of 128 on a Slam day; cheap enough, and
    # the alternative is a badge that only appears for seeds.
    ent_ranks: dict[int, int] = {}
    draw_ids = {e.draw_id for e in entries if getattr(e, "draw_id", None)}
    if draw_ids:
        from collections import defaultdict as _dd
        from app.services.upsets import _compute_draw_ranks
        field = (await db.execute(
            select(DrawEntry).where(DrawEntry.draw_id.in_(draw_ids)))).scalars().all()
        by_draw = _dd(list)
        for de in field:
            by_draw[de.draw_id].append(de)
        for _did, _es in by_draw.items():
            ent_ranks.update(_compute_draw_ranks(_es))

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

    # Players the bracket does not know — qualifying, in practice. Resolved by
    # name so their head-to-head and form work like everyone else's; one query
    # for the whole day, keyed on surname and confirmed on the full name.
    unlinked = [p.raw_name for e in entries for p in e.players
                if not p.draw_entry_id and e.discipline == "singles"]
    slugs_by_name = await _slugs_by_name(db, unlinked) if unlinked else {}
    extra_by_name = await _profiles_by_name(db, unlinked) if unlinked else {}

    match_ids = {e.match_id for e in entries if e.match_id}
    # The user's own picks, one query for the day. A failure here must not
    # cost the schedule: the mark is decoration on a page that has to load.
    picks: dict[int, int] = {}
    if user is not None and match_ids:
        try:
            pick_rows = (await db.execute(
                select(UserPrediction.match_id, UserPrediction.predicted_winner_id)
                .where(UserPrediction.user_id == user.id,
                       UserPrediction.match_id.in_(match_ids),
                       UserPrediction.predicted_winner_id.isnot(None)))).all()
            picks = {mid: wid for mid, wid in pick_rows}
        except Exception as exc:  # noqa: BLE001 — decoration, never a 500
            await app_log("warning", "schedule",
                          f"pick lookup failed for user {user.id}: {exc}")
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
        # A SUSPENDED MATCH IS NOT PROOF THAT TODAY'S ORDER HAS BEGUN.
        # It reads as "live" because it still carries a score — but that score
        # is yesterday's, and the row is on today's sheet only because the
        # match has to be finished sometime. On 2026-08-31 every affected court
        # ran 11:00 AM first and the carried match second, so a carry sitting
        # at position 2 marked the 11:00 AM match above it COMPLETED before it
        # had been played, with no score to show because there was none.
        # Play that happened on another day cannot say what happened on this
        # one.
        highest_started = None
        for e in sorted(slots, key=lambda x: x.court_order):
            if (statuses[e.id] in ("live", "completed")
                    and not _is_suspended(e, matches.get(e.match_id) if e.match_id else None)):
                highest_started = e.court_order
        if highest_started is None:
            continue
        for e in slots:
            if e.court_order < highest_started and statuses[e.id] == "scheduled":
                statuses[e.id] = "completed"

    # ── A DAY THAT RAN OUT, AND THE DAY THAT INHERITS IT ─────────────────────
    # Rain takes matches off the schedule without finishing them, and the two
    # days involved need different words. On the day it was ABANDONED the match
    # is postponed — whether it was mid-set or never called at all; on the day
    # it is picked up again it is a match to be completed, not a fresh one.
    # Without this the old day kept showing "In progress" for matches nobody
    # was playing, and the new day showed its carried-over matches as if they
    # were starting from love.
    # THE TOURNAMENT'S OWN ANSWER, NOT THE CLOCK'S. Waiting for the venue's
    # date to roll over would leave a rained-off evening reading "in progress"
    # for hours. The sheet says it plainly instead: a match that reappears on a
    # LATER day was abandoned on this one, and a match that appeared on an
    # EARLIER day is being picked up rather than started. Both sides of that
    # come from one query over the neighbouring days.
    sig_rows = (await db.execute(
        select(ScheduleEntry.id, ScheduleEntry.play_date,
               ScheduleEntry.tournament_id, ScheduleEntry.live_scores_json,
               ScheduleEntry.live_point_json, ScheduleEntry.started_at,
               # A FINISHED match empties its live columns — the final score
               # moves to scores_json and the result to winner_side. Reading
               # only the live ones made a completed match indistinguishable
               # from one that never got on court.
               ScheduleEntry.scores_json, ScheduleEntry.status,
               ScheduleEntry.winner_side, ScheduleEntry.completed_at,
               # SINGLES KEEPS ITS STATE ON THE MATCH, not on the row. Every
               # column above is written by the doubles/qualifying sweep, so a
               # singles row reads as never-started however long it was on
               # court — which is why a suspended singles match never reached
               # the "to be completed" branch and sat at "In progress" all day.
               ScheduleEntry.match_id,
               ScheduleEntryPlayer.raw_name)
        .join(ScheduleEntryPlayer,
              ScheduleEntryPlayer.schedule_entry_id == ScheduleEntry.id)
        .where(ScheduleEntry.tournament_id.in_(t_ids),
               ScheduleEntry.play_date.in_([day - timedelta(days=1), day,
                                            day + timedelta(days=1)])))).all()
    names_by_row: dict = {}
    row_meta: dict = {}
    for (rid, pd, tid, live_scores, live_point, started,
         final, st, winner, done_at, mid, raw) in sig_rows:
        names_by_row.setdefault(rid, set()).add(_pairing_surname(raw))
        row_meta[rid] = (tid, pd, live_scores, live_point, started,
                         final, st, winner, done_at, mid)
    elsewhere: dict = {}
    for rid, names in names_by_row.items():
        (tid, pd, live_scores, live_point, started,
         final, st, winner, done_at, mid) = row_meta[rid]
        # The bracket match behind this row, where singles keeps everything.
        # Present for a neighbouring day because a carried match is the SAME
        # match on both rows, so today's lookup already loaded it.
        m = matches.get(mid) if mid else None
        elsewhere.setdefault((tid, frozenset(names)), []).append(
            {"date": pd, "scores": live_scores, "point": live_point,
             "final": final, "winner": winner, "done_at": done_at,
             # The instant a poller first saw it on court. For a match picked
             # up on a later day this is restamped to the RESUMPTION, so a
             # borrowing row can print "Started at" instead of "In progress".
             "started_at": started,
             "done": (st == "completed" or done_at is not None
                      or getattr(m, "winner_id", None) is not None),
             # A finished match plainly started, even though completion has
             # since emptied the live column that used to prove it. Read off
             # the match as well as the row, so this is true for singles too.
             "started": (started is not None or bool(live_scores) or bool(final)
                         or getattr(m, "started_at", None) is not None
                         or bool(getattr(m, "live_scores_json", None))
                         or getattr(m, "winner_id", None) is not None)})

    venue_today = {tid: _venue_today(tzs.get(tid)) for tid in t_ids}
    carried_from: dict = {}
    # Rows this day no longer owns, because the match moved on to another one.
    dropped: set = set()

    def m_of(entry):
        return matches.get(entry.match_id) if entry.match_id else None

    carried_done: dict = {}
    for e in entries:
        siblings = elsewhere.get(
            (e.tournament_id, frozenset(names_by_row.get(e.id, ()))), [])
        later = [r for r in siblings if r["date"] > e.play_date]
        earlier = [r for r in siblings if r["date"] < e.play_date]

        # ONCE IT HAS RESUMED ELSEWHERE, THIS DAY NO LONGER OWNS IT.
        # A postponed row is the record of a day that ran out, and it earns its
        # place while the match is still waiting — that day is where it
        # stopped. But the moment play restarts on another sheet, this row is a
        # second copy of a match being played somewhere else, frozen at a score
        # that will never move again, and the day it belongs to is the day it
        # is on court. Two rows for one match is the thing that reads as the
        # site being wrong.
        #
        # Placed BEFORE the status branches below, because several of them
        # `continue` — a match that has since been won leaves through the
        # completed guard and would never reach a check made further down.
        #
        # Gated on resumed_at alone. A later sheet listing the match is a PLAN,
        # and a match scheduled to resume tomorrow and rained off again still
        # belongs to the day it stopped; and "a later row that is done" cannot
        # be used either, because a sheet printed early lists matches that were
        # finished on THIS day, which would drop the very row that played them.
        # The stamp is the only thing that says play actually restarted later.
        if later and getattr(m_of(e), "resumed_at", None) is not None:
            dropped.add(e.id)
            continue
        # ONLY A MATCH THAT ACTUALLY STARTED is "to be completed" — one that
        # never got on court is simply playing today, and saying otherwise
        # would put a resumption badge on a match with nothing to resume.
        #
        # Evidence of a start can sit on either row. Usually it is the
        # abandoned day's; but once the new day's row claims the event itself
        # it carries the games, while its started_at is stamped with TODAY's
        # announced slot — so a match resuming at 3-6, 6-6 looked like a
        # fresh one and read "Suspended" instead of "To be completed".
        earlier_started = [r for r in earlier if r["started"]]
        started_before = bool(earlier_started) or (
            bool(earlier) and _has_games(e.live_scores_json))
        # A row being PLAYED right now says so; the resumption is over.
        # Suspended is not playing. This tested only the doubles point flag, so
        # a suspended SINGLES match — whose stoppage is recorded on the match's
        # live_scores instead — counted as under way, and the row never reached
        # the "to be completed" branch below. It sat at "In progress" all day
        # beside a score that could not move.
        playing_now = (statuses[e.id] == "live"
                       and not _is_suspended(e, matches.get(e.match_id) if e.match_id else None))
        # THE MATCH IS OVER, WHEREVER IT FINISHED. A sheet printed before the
        # resumption still lists the match today, and it goes on saying so
        # after it has been won. The result is a fact and the sheet is only a
        # plan, so the result wins — including over a `later` row, which is
        # just another sheet printed even earlier.
        earlier_done = [r for r in earlier if r["done"]]
        if earlier_done:
            statuses[e.id] = "completed"
            src = max(earlier_done, key=lambda r: r["date"])
            # Its score and result live on the row that owned the claim, so
            # this row shows them the same way it would show a carried
            # suspension — from scores_json, where completion put them.
            if not (e.scores_json or _has_games(e.live_scores_json)):
                carried_done[e.id] = src
            continue
        # Only NOW may an already-completed row bow out. This guard used to sit
        # at the top of the loop, where it swallowed the branch above: the
        # court heuristic ("everything before a started match has finished")
        # marks a carried row completed the moment the next match on its court
        # gets on, and the row then skipped the very code that fetches the
        # score it should be showing — Completed, with nothing under it.
        if statuses[e.id] == "completed":
            continue
        # A MATCH BEING PLAYED RIGHT NOW IS NEVER "POSTPONED", whatever any
        # sheet says. A later sheet is a plan; the venue's date rolling over is
        # a clock. Neither outranks a live score. Zverev–Sonego on 2026-09-01
        # was in its fourth set at 00:22 New York time and read POSTPONED for
        # the rest of the night, because the branch below decided the day was
        # over and nothing unfinished could still be in play.
        if later and not playing_now:
            statuses[e.id] = "postponed"
        elif started_before and not playing_now:
            statuses[e.id] = "to_be_completed"
            # The score stands where play stopped. It lives on the row for the
            # day it was abandoned — that row holds the claim, and an event can
            # only be claimed once — so this row shows it rather than owning it.
            src = (max(earlier_started, key=lambda r: r["date"])
                   if earlier_started else None)
            # ONLY BORROW FROM A ROW THAT HAS SOMETHING TO LEND. The abandoned
            # day's row carries the score for doubles and qualifying; for
            # singles the score is on the match, which this row already reads
            # through the ordinary path. Borrowing an empty row would blank a
            # score that was on screen a moment ago.
            if (src and not _has_games(e.live_scores_json)
                    and (_has_games(src.get("scores")) or src.get("final"))):
                carried_from[e.id] = src
                # AND IF PLAY HAS RESTARTED, SAY SO. The claim stays with the
                # abandoned day's row, so this row learns the match is back on
                # only through what it is borrowing: a source whose point is
                # no longer flagged suspended is a match being played now.
                # Without this the resumed match would sit under "To be
                # completed" for the rest of the afternoon.
                if (src.get("point") or {}).get("suspended") is False:
                    statuses[e.id] = "live"
        elif (not playing_now
              and e.play_date < (venue_today.get(e.tournament_id) or date.today())):
            # No later sheet yet — but this day is over at the venue, so
            # whatever is still unfinished did not get played. Unless it is
            # being played: a night session runs past midnight every Slam.
            statuses[e.id] = "postponed"

    # ── Who actually came through ────────────────────────────────────────────
    # The sheet is printed before the matches feeding it have been played, so a
    # semi-final slot reads "Fritz OR Nakashima" from the moment it is published
    # — and goes on reading that for the rest of the day, long after the
    # quarter-final settled it. The bracket knows the answer; only the PDF does
    # not, and it will not until somebody reprints it.
    #
    # An unresolved side lists the players of the match feeding it, so the pair
    # of candidates IS a match — and in a knockout draw two players meet at most
    # once, so a completed match between exactly those two can only be the
    # feeder. Its winner is who is standing in the slot.
    #
    # Resolved at the point of SERVING, not written back. The row keeps the
    # alternatives it was ingested with, so the next revision still reconciles
    # against what the sheet says rather than against something we decided —
    # being right today this way costs nothing tomorrow.
    alt_ids = {p.draw_entry_id for e in entries if e.is_tbd
               for p in e.players if p.draw_entry_id}
    decided: dict[frozenset, int] = {}
    if alt_ids:
        decided = {
            frozenset((r[0], r[1])): r[2]
            for r in (await db.execute(
                select(Match.player1_id, Match.player2_id, Match.winner_id).where(
                    Match.winner_id.isnot(None),
                    Match.player1_id.in_(alt_ids),
                    Match.player2_id.in_(alt_ids)))).all()
        }

    # ── The same question for doubles ───────────────────────────────────────
    # Doubles has no bracket row, so the singles path above — which finds the
    # completed Match between two candidates — can never answer it. Its result
    # lives on the SCHEDULE ROW: the semi-final that fed this final is another
    # entry, with its own two sides and a winner_side stamped by the Sofascore
    # sweep.
    #
    # So the feeder is found the same way, by identity rather than by id: the
    # four surnames on a TBD side are the four surnames of the match that
    # decides it. Keyed on that set, the answer is which pair won.
    # The lookup and the rule both live in services/schedule.py, because
    # schedule_invariants runs them too: the settled side exists only in what
    # is SERVED — the stored row stays honestly unresolved — so a law that
    # cannot run this code cannot see the shape it produces. One
    # implementation, policed rather than mirrored.
    dbl_settled: dict = {}
    if any(e.is_tbd for e in entries):
        since = day - timedelta(days=14)
        dbl_settled = settled_sides_index((await db.execute(
            select(ScheduleEntry).where(
                ScheduleEntry.tournament_id.in_(t_ids),
                ScheduleEntry.winner_side.isnot(None),
                ScheduleEntry.play_date >= since,
                ScheduleEntry.play_date <= day))).scalars().all())

    def _settle_rows(side_players):
        return settle_from_result_rows(side_players, dbl_settled)

    def _settle(side_players):
        """(players, resolved) — the winner alone once the candidates have met.

        Only the clean case: exactly two candidates, both matched to bracket
        rows, who have played each other and one of them won. A slot listing a
        qualifier, an unmatched name or a match still in progress falls through
        unchanged, which is the honest answer — the alternatives really are
        still the alternatives.
        """
        ids = [p.draw_entry_id for p in side_players]
        if len(ids) != 2 or None in ids:
            return side_players, False
        won = decided.get(frozenset(ids))
        if won is None:
            return side_players, False
        return [p for p in side_players if p.draw_entry_id == won], True

    out: list[ScheduleEntryOut] = []
    courts: list[str] = []
    for e in entries:
        if e.id in dropped:
            continue
        if e.court and e.court not in courts:
            courts.append(e.court)
        m = matches.get(e.match_id) if e.match_id else None

        unresolved = e.tbd_side or ""
        ordered = []
        for side in ("a", "b"):
            sp = sorted((p for p in e.players if p.side == side),
                        key=lambda x: x.position)
            if side in unresolved:
                # ONE PATH, WHATEVER THE ROW IS.
                #
                # There is no branch on discipline or stage here, and there must
                # never be one again. Three times this was fixed for one
                # combination and broke for the next — main-draw singles, then
                # doubles, then qualifying singles — because the CODE was
                # organised around the kind of match while the PROBLEM is not.
                #
                # A TBD side names the participants of the match that decides
                # it. That match recorded its result in one of exactly two
                # places: a bracket row, if it has one, or its own schedule row,
                # if it does not. So ask both, in that order, for every row.
                # Qualifying doubles needs no new code; nor does anything else,
                # because there is nowhere else for a result to be.
                sp, settled = _settle(sp)
                if not settled:
                    sp, settled = _settle_rows(sp)
                if settled:
                    unresolved = unresolved.replace(side, "")
            ordered.extend(sp)

        players = [
            _player_out(p, nats, ent_seeds, ent_types, ent_ranks,
                        e.discipline == "singles" and e.stage == "main",
                        ent_slugs, ent_extra, slugs_by_name, extra_by_name)
            for p in ordered
        ]
        # A row whose match finished on another day holds no result of its
        # own; what it borrows is the only true answer it has.
        ws = _winner_side(e, m, players)
        done_at = _utc(getattr(m, "completed_at", None) if m else e.completed_at)
        # A carried row owns no claim, so nothing ever stamped it as started —
        # and the time column fell back to the literal words "In progress"
        # while every other live row named an hour. The row it borrows its
        # score from was stamped when play restarted; borrow that too.
        began = _utc(getattr(m, "started_at", None) if m else e.started_at)
        if began is None:
            src_row = carried_from.get(e.id) or carried_done.get(e.id)
            if src_row and src_row.get("started_at"):
                began = _utc(src_row["started_at"])
        if e.id in carried_done:
            if ws is None:
                ws = {"a": 0, "b": 1}.get(carried_done[e.id]["winner"])
            if done_at is None:
                done_at = _utc(carried_done[e.id]["done_at"])
        out.append(ScheduleEntryOut(
            id=e.id, tournament_id=e.tournament_id,
            tournament_name=t_names.get(e.tournament_id),
            draw_id=e.draw_id, match_id=e.match_id, play_date=e.play_date,
            pick_entry_id=picks.get(e.match_id) if e.match_id else None,
            tour=e.tour, stage=e.stage, discipline=e.discipline,
            round_label=e.round_label, court=e.court, court_order=e.court_order,
            start_type=e.start_type, start_time_local=e.start_time_local,
            start_note=e.start_note,
            printed_start_at=_printed_instant(e, tzs.get(e.tournament_id)),
            expected_start_at=_utc(e.expected_start_at), expected_source=e.expected_source,
            # Singles reads it off the match; doubles has none and carries its
            # own, so the field means the same thing either way.
            started_at=began,
            # Only when it is genuinely later than the start — a match that has
            # never been suspended has no resumption to report, and one
            # resumed within the same session should not claim a second start.
            resumed_at=(_utc(getattr(m, "resumed_at", None)) if m else None),
            # Same read-through as started_at: singles carries the result on the
            # match, doubles on the row itself.
            completed_at=done_at,
            # What is STILL unresolved after the substitution above, so a slot
            # settled by the bracket renders as the ordinary match it now is —
            # H2H included, which is gated on the row naming one player a side.
            is_tbd=bool(unresolved), tbd_side=unresolved or None,
            status=statuses[e.id], players=players,
            # Singles reads through the match; doubles has none and carries its
            # own result on the row. Same field names either way, so the client
            # needs no idea which kind of match it is looking at.
            # A carried-over row shows the abandoned day's score — see
            # carried_from. Its own columns are empty because the claim, and
            # therefore the scoring, belongs to the row that was abandoned.
            live_scores=((carried_from[e.id]["scores"] if e.id in carried_from
                          else None)
                         or (m.live_scores_json if m else e.live_scores_json)),
            live_point=(_carried_point(carried_from[e.id])
                        if e.id in carried_from
                        else (live_point_for(m) if m else _doubles_point(e))),
            scores=((carried_done[e.id]["final"] if e.id in carried_done
                     else None)
                    or (m.scores_json if m else e.scores_json)),
            winner_side=ws,
            surface=(draw_meta.get(e.draw_id) or (None, None))[0],
            gender=(draw_meta.get(e.draw_id) or (None, None))[1],
        ))

    # The official PDF stays one tap away — the page replaces it as the primary
    # destination, it does not hide it.
    pdf_rows = (await db.execute(
        select(Draw.tournament_id, Draw.oop_url).where(
            Draw.tournament_id.in_(t_ids), Draw.oop_url.isnot(None)))).all()
    pdfs = {r[0]: r[1] for r in pdf_rows}

    # Which revision of THIS DAY's sheet the site currently reflects — the
    # same ordinal the status emails carry ("OOP rev.3"), counted the same
    # way: real revisions only, a force-reparse's 'forced-*' leftovers
    # excluded, so re-ingests of identical content never inflate it.
    from app.models.schedule import ScheduleDocument
    rev_rows = (await db.execute(
        select(ScheduleDocument.tournament_id, func.count()).where(
            ScheduleDocument.tournament_id.in_(t_ids),
            ScheduleDocument.play_date == day,
            ScheduleDocument.parse_status == "oop",
            ScheduleDocument.sha256.notlike("forced%"),
        ).group_by(ScheduleDocument.tournament_id))).all()
    revs = {r[0]: r[1] for r in rev_rows}

    return ScheduleDayOut(
        play_date=day, entries=out, courts=courts,
        tournaments=[{"id": i, "name": t_names.get(i), "oop_url": pdfs.get(i),
                      "oop_revision": revs.get(i),
                      "venue_timezone": tzs.get(i)}
                     for i in sorted(t_ids)],
    )


@router.get("/entries/{entry_id}/score-history")
async def entry_score_history(entry_id: int, db: AsyncSession = Depends(get_db)):
    """The match endpoint's twin for rows with no bracket match — qualifying
    singles and doubles, whose only record is the schedule entry itself.
    Same response shape, so the popup renders both through one path.
    Snapshots are stored in the SHEET's orientation: side 1 IS side a, and
    player1_name is side a's first printed name so the client's orientation
    check lines up. An empty list is a normal answer, not an error."""
    from app.models.score_history import ScheduleScoreSnapshot
    from app.services.sofascore_live import renderable_history

    entry = await db.get(ScheduleEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Schedule entry not found")

    # EVERY SNAPSHOT OF THIS MATCH, whichever row recorded it. A match picked
    # up on a later day is scored against the row holding the claim — the day
    # it was abandoned — so the carried row has none of its own, and its popup
    # opened on a bare current score with no timeline to scrub. The same
    # pairing signature that carries the score across days finds them here.
    day = entry.play_date
    cand = (await db.execute(
        select(ScheduleEntry.id, ScheduleEntryPlayer.raw_name,
               ScheduleEntryPlayer.side, ScheduleEntryPlayer.position)
        .join(ScheduleEntryPlayer,
              ScheduleEntryPlayer.schedule_entry_id == ScheduleEntry.id)
        .where(ScheduleEntry.tournament_id == entry.tournament_id,
               ScheduleEntry.play_date.in_(
                   [day - timedelta(days=1), day,
                    day + timedelta(days=1)])))).all()
    sig: dict = {}
    lead: dict = {}
    for rid, raw, side, pos in cand:
        sig.setdefault(rid, set()).add(_pairing_surname(raw))
        if side == "a" and (rid not in lead or (pos or 0) < lead[rid][0]):
            lead[rid] = ((pos or 0), _pairing_surname(raw))
    mine = sig.get(entry_id) or set()
    my_lead = (lead.get(entry_id) or (0, ""))[1]
    # Same tournament, same surnames: in a knockout draw two players meet at
    # most once, so that is this match on whatever day the sheet gave it.
    kin = {rid for rid, names in sig.items() if names == mine and names} or {entry_id}
    flipped = {rid for rid in kin if (lead.get(rid) or (0, ""))[1] != my_lead}

    rows = (await db.execute(
        select(ScheduleScoreSnapshot)
        .where(ScheduleScoreSnapshot.schedule_entry_id.in_(kin))
        .order_by(ScheduleScoreSnapshot.at, ScheduleScoreSnapshot.id)
    )).scalars().all()
    snapshots = []
    for r in rows:
        out = renderable_history(r.snap)
        if out is not None:
            snapshots.append(_flip_sides(out)
                             if r.schedule_entry_id in flipped else out)

    # The result lives with the claim too, so a finished carried match would
    # otherwise scrub through its whole timeline to a blank final score.
    final = entry.scores_json
    if final is None and len(kin) > 1:
        sib = (await db.execute(
            select(ScheduleEntry.id, ScheduleEntry.scores_json)
            .where(ScheduleEntry.id.in_(kin - {entry_id}),
                   ScheduleEntry.scores_json.isnot(None)))).first()
        if sib:
            final = sib[1]
            if sib[0] in flipped and isinstance(final, list) and len(final) == 2:
                final = [final[1], final[0]]

    side_a = (await db.execute(
        select(ScheduleEntryPlayer.raw_name)
        .where(ScheduleEntryPlayer.schedule_entry_id == entry_id,
               ScheduleEntryPlayer.side == "a")
        .order_by(ScheduleEntryPlayer.position)
    )).scalars().first()
    # "Prev Point: Ace" — see the twin in tournaments.py. These rows already
    # carry the Sofascore event id (they are the ones with no bracket match,
    # which is exactly where the claim is stored), so nothing extra is needed.
    from app.services.sofascore_points import labels_for
    for _snap, _label in zip(
            snapshots,
            await labels_for(db, snapshots, entry.sofa_event_id,
                             finished=final is not None)):
        # ON the snapshot, not a parallel array: the client drops snapshots it
        # judges to be feed corrections (sanitizeSnapshots), and an index-based
        # list would silently shift a label onto the wrong point.
        if _label:
            _snap["point_label"] = _label
    return {
        "status": entry.status,
        "completed_at": None,
        "player1_id": None,
        "player1_name": side_a,
        "snapshots": snapshots,
        "final": final,
    }


@router.get("/dates")
async def schedule_dates(
    tournament_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Days that actually have a schedule — drives the date stepper so it can
    skip straight to the next real day instead of walking through blanks.

    `open_counts` says how many matches on each day are still to be decided,
    which is what lets the page land on the day with tennis left in it rather
    than on the last sheet published.

    A row counts as DECIDED when anything says so: its own status, its own
    completion stamp, its own winner, or the bracket match behind it. That last
    one is not redundant — a sheet row whose Sofascore claim never landed sits
    at "scheduled" for ever while the match it points at has a winner and a
    score, which is exactly what both of yesterday's finals did during the
    2026-08-29 block. Reading only the row would have called a finished day
    unfinished and parked the page on it.
    """
    q = (select(ScheduleEntry.play_date,
                func.count(),
                func.sum(
                    case((or_(ScheduleEntry.status == "completed",
                              ScheduleEntry.completed_at.isnot(None),
                              ScheduleEntry.winner_side.isnot(None),
                              Match.winner_id.isnot(None)), 0),
                         else_=1)))
         .select_from(ScheduleEntry)
         .outerjoin(Match, Match.id == ScheduleEntry.match_id)
         .group_by(ScheduleEntry.play_date))
    if tournament_id:
        q = q.where(ScheduleEntry.tournament_id == tournament_id)
    rows = (await db.execute(q.order_by(ScheduleEntry.play_date))).all()
    return {"dates": [r[0].isoformat() for r in rows],
            "open_counts": {r[0].isoformat(): int(r[2] or 0) for r in rows}}
