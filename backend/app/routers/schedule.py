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

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_optional_user
from app.database import get_db
from app.models.schedule import ScheduleEntry
from app.models.rankings import TePlayer, TeRankingsSnapshot
from app.services.sofascore_doubles import _sheet_surnames
from app.services.rankings import _norm
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


def _player_out(p, nats: dict, seeds: dict, types: dict, from_bracket: bool,
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
    if from_bracket:
        seed = seeds.get(p.draw_entry_id) or seed
        etype = types.get(p.draw_entry_id) or etype
    return SchedulePlayerOut(
        side=p.side, position=p.position,
        name=p.raw_name,
        draw_entry_id=p.draw_entry_id,
        nationality=nats.get(p.draw_entry_id) or p.nationality,
        seed=seed,
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


def _doubles_point(entry):
    """The live point for a doubles row, which has no bracket match to carry it.

    Same rules as singles, and literally the same code — see renderable_point.
    The two were separate copies until the doubles one fell behind by a field.
    """
    from app.services.sofascore_live import renderable_point

    return renderable_point(getattr(entry, "live_point_json", None),
                            bool(getattr(entry, "winner_side", None)))


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

    # Players the bracket does not know — qualifying, in practice. Resolved by
    # name so their head-to-head and form work like everyone else's; one query
    # for the whole day, keyed on surname and confirmed on the full name.
    unlinked = [p.raw_name for e in entries for p in e.players
                if not p.draw_entry_id and e.discipline == "singles"]
    slugs_by_name = await _slugs_by_name(db, unlinked) if unlinked else {}
    extra_by_name = await _profiles_by_name(db, unlinked) if unlinked else {}

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
    dbl_settled: dict[frozenset, frozenset] = {}
    if any(e.is_tbd for e in entries):
        since = day - timedelta(days=14)
        # Every row that recorded a result, of any discipline and any stage.
        # Filtering this by kind is what made the resolver need fixing once per
        # kind; a result is a result.
        rows = (await db.execute(
            select(ScheduleEntry).where(
                ScheduleEntry.tournament_id.in_(t_ids),
                ScheduleEntry.winner_side.isnot(None),
                ScheduleEntry.play_date >= since,
                ScheduleEntry.play_date <= day))).scalars().all()
        for r in rows:
            sides = {}
            for p in r.players:
                sides.setdefault(p.side, []).append(p.raw_name)
            a, b = _sheet_surnames(sides.get("a", [])), _sheet_surnames(sides.get("b", []))
            if not a or not b:
                continue
            dbl_settled[frozenset(a | b)] = frozenset(a if r.winner_side == "a" else b)

    def _settle_rows(side_players):
        """(players, resolved) — who came through, from the row that recorded it.

        Discipline-agnostic and stage-agnostic by construction: it knows only
        that two candidates met and that some row says who won. A doubles final,
        a qualifying second round, and anything not yet invented resolve through
        the same lookup.
        """
        if len(side_players) != 2:
            return side_players, False
        teams = [_sheet_surnames([p.raw_name]) for p in side_players]
        if not all(teams):
            return side_players, False
        won = dbl_settled.get(frozenset(teams[0] | teams[1]))
        if won is None:
            return side_players, False
        keep = [p for p, t in zip(side_players, teams) if t & won]
        # Exactly one of the two, or we have not identified anything.
        return (keep, True) if len(keep) == 1 else (side_players, False)

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
            _player_out(p, nats, ent_seeds, ent_types,
                        e.discipline == "singles" and e.stage == "main",
                        ent_slugs, ent_extra, slugs_by_name, extra_by_name)
            for p in ordered
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
            # Same read-through as started_at: singles carries the result on the
            # match, doubles on the row itself.
            completed_at=_utc(getattr(m, "completed_at", None) if m else e.completed_at),
            # What is STILL unresolved after the substitution above, so a slot
            # settled by the bracket renders as the ordinary match it now is —
            # H2H included, which is gated on the row naming one player a side.
            is_tbd=bool(unresolved), tbd_side=unresolved or None,
            status=statuses[e.id], players=players,
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
