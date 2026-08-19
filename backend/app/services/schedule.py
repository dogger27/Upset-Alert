"""
Turn a parsed order-of-play PDF into stored schedule rows.

Two things here are not obvious and carry the design:

**Identity.** A re-parse must recognise a slot it has already stored, or every
revision duplicates or clobbers. Court and order cannot identify it — inserting
one match renumbers every slot below it. The pairing does: these players, this
day, this tournament. `_pairing_key` prefers resolved draw_entry ids and falls
back to normalised names when a side is still "X or Y".

**Expected start.** 12% of slots print no clock time ("Followed by"), so the
time view cannot sort on the sheet alone. Times are chained per court:

    fixed       -> as printed
    not_before  -> MAX(printed, predecessor's expected end)
    followed_by -> predecessor's expected end

`not_before` taking the max is the interesting one: it is a lower bound, not a
time, so when the preceding match overruns the printed time is simply wrong and
the page can say "expected ~4:15pm (not before 3:00)". Anything ESPN reports as
live or finished re-anchors the chain to reality, so estimates sharpen through
the day instead of drifting.
"""

import hashlib
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, delete, or_, select

from app.models.schedule import (ScheduleChange, ScheduleDocument,
                                 ScheduleEntry, ScheduleEntryPlayer)
from app.models.tournament import Draw, DrawEntry, Match
from app.services.oop_parser import parse_pdf
from app.services.rankings import _norm

# Seeds for the chain. No historical durations exist to fit these to —
# `matches.completed_at` is populated but there is no start time to subtract —
# so they are deliberate constants, replaceable once this feature has generated
# a season of its own data. They only affect slots with no stated time, and
# every live result collapses the error for everything after it on that court.
_DURATION_MIN = {("singles", 3): 105, ("singles", 5): 170, ("doubles", 3): 80}
_DEFAULT_DURATION = 105

_SEED_RE = re.compile(r'^\s*(?:\[[^\]]*\]\s*)+')
_NAT_RE = re.compile(r'\b[A-Z]{3}\b')
_CLOCK_RE = re.compile(r'^(\d{1,2})[:.](\d{2})\s*(am|pm)?$', re.I)

# "QS" is qualifying singles, "MD" men's doubles — the sheet states both
# dimensions in one code, which is exactly how they are filtered.
_EVENT_CODE_RE = re.compile(r'\b([MWQXBG])([SD])\b')


def _clean_name(raw: str) -> str:
    return _NAT_RE.sub('', _SEED_RE.sub('', raw or '')).strip()


def _duration_for(discipline: str, best_of: int = 3) -> int:
    return _DURATION_MIN.get((discipline, best_of), _DEFAULT_DURATION)


def _parse_clock(value: Optional[str]) -> Optional[time]:
    if not value:
        return None
    m = _CLOCK_RE.match(value.strip())
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2)), (m.group(3) or '').lower()
    if ampm == 'pm' and hour != 12:
        hour += 12
    elif ampm == 'am' and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def _classify(match) -> tuple[str, str]:
    """(stage, discipline) — from the event code when present, else the parse."""
    blob = ' '.join([match.court or '', match.round or '', match.discipline or ''])
    m = _EVENT_CODE_RE.search(blob)
    if m:
        first, second = m.group(1), m.group(2)
        stage = 'qualifying' if first == 'Q' else 'main'
        discipline = 'doubles' if second == 'D' else 'singles'
        if first == 'X':
            discipline = 'mixed'
        return stage, discipline
    stage = 'qualifying' if (match.round or '').upper().startswith('Q') else 'main'
    discipline = 'doubles' if match.is_doubles else 'singles'
    return stage, discipline


def _round_label(round_number: Optional[int], num_rounds: Optional[int]) -> Optional[str]:
    """R128 / R64 / ... / QF / SF / F from a match's position in the bracket.

    The sheet only prints a round on a minority of slots, so deriving it from
    the mapped match is what makes it present on all of them. Mirrors the
    frontend's own labelling (TournamentDraw.jsx navLabel) so a schedule row and
    the bracket never disagree about what round something is.
    """
    if not round_number or not num_rounds or round_number > num_rounds:
        return None
    remaining = 2 ** (num_rounds - round_number)   # matches left in this round
    if remaining == 1:
        return 'F'
    if remaining == 2:
        return 'SF'
    if remaining == 4:
        return 'QF'
    return f'R{remaining * 2}'


def _pairing_key(tournament_id: int, play_date: date, discipline: str,
                 side_a: list, side_b: list, entry_ids: list) -> str:
    """Stable across court, time and order changes — those are what we detect."""
    if entry_ids and all(entry_ids):
        ident = 'e:' + ','.join(str(i) for i in sorted(entry_ids))
    else:
        names = sorted(_norm(_clean_name(n)) for n in (side_a + side_b) if n)
        ident = 'n:' + '|'.join(names)
    raw = f'{tournament_id}:{play_date.isoformat()}:{discipline}:{ident}'
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def _resolve_players(db, draws: list, tour: Optional[str], names: list) -> list:
    """Map printed names onto draw_entries. Closed-set matching, not extraction:
    the entrants are already known, so every token from the sheet must appear in
    the candidate. Measured at 100% on main-draw singles; qualifying cannot
    resolve at all, because losing qualifiers never reach draw_entries."""
    out = []
    for raw in names:
        tokens = {t for t in _norm(_clean_name(raw)).split() if len(t) > 2}
        found = None
        if tokens:
            for draw in draws:
                for entry in draw['entries']:
                    if tokens <= entry[1]:
                        found = entry[0] if found is None else found
        out.append(found)
    return out


def _candidates(draws, names) -> set:
    """Every draw entry any of these printed names could refer to.

    Unlike _resolve_players this keeps all possibilities rather than the first.
    An unresolved slot lists the players of the match feeding it — abbreviated,
    so "J. M. Cerundolo" matches both Cerundolos — and the ambiguity resolves
    itself once we look for a bracket match pairing one candidate from each
    side.
    """
    out = set()
    for raw in names:
        tokens = {t for t in _norm(_clean_name(raw)).split() if len(t) > 2}
        if not tokens:
            continue
        for draw in draws:
            for eid, ent_tokens in draw['entries']:
                if tokens <= ent_tokens:
                    out.add(eid)
    return out


async def ingest_document(db, tournament, play_date: date, url: str,
                          pdf_bytes: bytes, tour: Optional[str] = None) -> dict:
    """Parse one PDF revision and reconcile it into schedule_entries."""
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    existing = (await db.execute(
        select(ScheduleDocument).where(
            ScheduleDocument.tournament_id == tournament.id,
            ScheduleDocument.play_date == play_date,
            ScheduleDocument.sha256 == digest,
        ))).scalars().first()
    if existing:
        return {'skipped': 'unchanged', 'document_id': existing.id}

    matches, meta = parse_pdf(pdf_bytes)
    doc = ScheduleDocument(
        tournament_id=tournament.id, play_date=play_date, source_url=url,
        tour=tour, sha256=digest, revision_label=meta.get('date_line'),
        parse_status=meta.get('kind') or 'ok', match_count=len(matches),
    )
    db.add(doc)
    await db.flush()

    if not matches:
        return {'document_id': doc.id, 'kind': meta.get('kind'), 'entries': 0}

    # Roster for resolution: every draw of this tournament.
    draw_rows = (await db.execute(
        select(Draw).where(Draw.tournament_id == tournament.id))).scalars().all()
    draws = []
    for d in draw_rows:
        ents = (await db.execute(
            select(DrawEntry.id, DrawEntry.name).where(DrawEntry.draw_id == d.id))).all()
        draws.append({'draw': d,
                      'entries': [(e[0], set(_norm(e[1] or '').split())) for e in ents],
                      'names': {e[0]: e[1] for e in ents}})

    # entry id -> draw id, so a resolved player also tells us which draw the
    # slot belongs to.
    entry_draw = {}
    draw_by_id = {}
    entry_name = {}
    for d in draws:
        draw_by_id[d['draw'].id] = d['draw']
        entry_name.update(d['names'])
        for eid, _tokens in d['entries']:
            entry_draw[eid] = d['draw'].id

    seen_keys = []
    per_court: dict[str, list] = {}
    for m in matches:
        stage, discipline = _classify(m)
        names_a = list(m.side_a)
        names_b = list(m.side_b)
        ids = await _resolve_players(db, draws, m.tour, names_a + names_b)
        key = _pairing_key(tournament.id, play_date, discipline, names_a, names_b, ids)
        per_court.setdefault(m.court or '', []).append(
            (m, stage, discipline, names_a, names_b, ids, key))
        seen_keys.append(key)

    # Doubles has no bracket row to derive a round from, and the sheet prints
    # one on only some slots — today's Cincinnati file labels four of eleven.
    # Fill the blanks from the labelled ones, but ONLY when every printed round
    # for that discipline agrees: a day that spans two doubles rounds shows both
    # labels, and guessing there would be wrong rather than merely missing.
    printed_rounds: dict[tuple, set] = {}
    for slots in per_court.values():
        for (m, stage, discipline, _na, _nb, _ids, _key) in slots:
            if m.round:
                printed_rounds.setdefault((stage, discipline), set()).add(m.round.upper())
    unanimous = {k: next(iter(v)) for k, v in printed_rounds.items() if len(v) == 1}

    written = 0
    for court, slots in per_court.items():
        for order, (m, stage, discipline, na, nb, ids, key) in enumerate(slots, 1):
            entry = (await db.execute(
                select(ScheduleEntry).where(ScheduleEntry.pairing_key == key))).scalars().first()
            start_type = _start_type_of(m)
            if entry is None:
                entry = ScheduleEntry(
                    # NOT `or tour`: the source is where the file is hosted, not
                    # whose match it is. A combined event's file lives on the WTA
                    # site, so that fallback stamped men's doubles as WTA.
                    tournament_id=tournament.id, play_date=play_date, tour=m.tour,
                    stage=stage, discipline=discipline, round_label=m.round,
                    pairing_key=key,
                )
                db.add(entry)
                await db.flush()
                for side, names in (('a', na), ('b', nb)):
                    base = 0 if side == 'a' else len(na)
                    for pos, nm in enumerate(names, 1):
                        db.add(ScheduleEntryPlayer(
                            schedule_entry_id=entry.id, side=side, position=pos,
                            raw_name=nm, draw_entry_id=ids[base + pos - 1]
                                if base + pos - 1 < len(ids) else None))
            else:
                for field, new in (('court', court), ('court_order', order),
                                   ('start_time_local', m.time), ('start_type', start_type)):
                    old = getattr(entry, field)
                    if str(old) != str(new) and old is not None:
                        db.add(ScheduleChange(
                            schedule_entry_id=entry.id, document_id=doc.id,
                            field=field, old_value=str(old), new_value=str(new)))

            # Link the slot to the draw and the bracket match. This is what the
            # whole feature turns on: without match_id there are no live scores
            # and no completed scores, and the page is just a nicer PDF. Only
            # singles can resolve — qualifying has no rows in `matches` and
            # doubles has no draw at all.
            side_a_ids = [i for i in ids[:len(na)] if i]
            side_b_ids = [i for i in ids[len(na):] if i]

            # Candidate sets, which handles a settled slot and an unresolved one
            # with the same code: a settled side has one candidate, an "X OR Y"
            # side has the players of the match feeding it.
            cand_a = _candidates(draws, na)
            cand_b = _candidates(draws, nb)
            found = None
            if discipline == 'singles' and cand_a and cand_b:
                found = (await db.execute(
                    select(Match).where(
                        Match.player1_id.isnot(None), Match.player2_id.isnot(None),
                        or_(and_(Match.player1_id.in_(cand_a), Match.player2_id.in_(cand_b)),
                            and_(Match.player1_id.in_(cand_b), Match.player2_id.in_(cand_a))),
                    ))).scalars().first()

            if found is not None:
                entry.match_id = found.id
                entry.draw_id = found.draw_id
                derived = _round_label(found.round_number,
                                       draw_by_id[found.draw_id].num_rounds
                                       if found.draw_id in draw_by_id else None)
                if derived:
                    entry.round_label = derived

                # A sheet printed before the feeding matches finished still says
                # "Tien OR Tiafoe". The bracket knows who actually came through,
                # so replace the alternatives with the real pair rather than
                # showing a choice whose answer we already hold.
                if m.tbd:
                    na = [entry_name.get(found.player1_id) or na[0]]
                    nb = [entry_name.get(found.player2_id) or nb[0]]
                    ids = [found.player1_id, found.player2_id]
                    entry.is_tbd = False
                    entry.tbd_side = None
                    await db.execute(
                        delete(ScheduleEntryPlayer).where(
                            ScheduleEntryPlayer.schedule_entry_id == entry.id))
                    for side, nm, eid in (('a', na[0], ids[0]), ('b', nb[0], ids[1])):
                        db.add(ScheduleEntryPlayer(
                            schedule_entry_id=entry.id, side=side, position=1,
                            raw_name=nm, draw_entry_id=eid))
            elif side_a_ids or side_b_ids:
                any_id = (side_a_ids + side_b_ids)[0]
                entry.draw_id = entry_draw.get(any_id)

            entry.court = court
            entry.court_order = order
            entry.start_type = start_type
            entry.start_time_local = m.time
            entry.start_note = getattr(m, 'start_raw', None)
            if found is None or not m.tbd:
                entry.is_tbd = bool(m.tbd)
                entry.tbd_side = getattr(m, 'tbd_side', None)
            entry.round_label = (m.round or entry.round_label
                                 or unanimous.get((stage, discipline)))
            entry.printed_score = getattr(m, 'printed_score', None)
            entry.last_seen_at = datetime.now(timezone.utc)
            entry.last_document_id = doc.id
            written += 1

    await db.commit()
    return {'document_id': doc.id, 'entries': written, 'kind': meta.get('kind')}


def _start_type_of(m) -> str:
    """The printed wording decides, NOT the presence of a clock time.

    "Not before 3:00 PM" carries a time but is a lower bound — treating it as
    fixed because a time is present would discard exactly the distinction the
    expected-start chain exists to model.
    """
    raw = (getattr(m, 'start_raw', '') or '').lower()
    if 'not before' in raw or 'not bef' in raw:
        return 'not_before'
    if 'followed by' in raw:
        return 'followed_by'
    if 'after' in raw or 'arranged' in raw:
        return 'after_event'
    if m.time:
        return 'fixed'
    return 'tba'


def _aware(dt):
    """SQLite hands datetimes back naive; treat them as the UTC they were stored as."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _remaining_minutes(live, discipline: str, sets_to_win: int = 2) -> int:
    """Roughly how much longer a match in progress has to run.

    live_scores_json carries games per set for both players, so we know how far
    through it is rather than only that it started.

    The count that matters is how many COMPLETE sets can still follow the one
    being played. Getting that wrong is what made a match at 4-3 in the third
    report an hour left: with two sets decided the score is one-all, the third
    set decides it and nothing follows — but the formula added a whole further
    set anyway, and the next match on court inherited the error.

        additional = sets_to_win - 1 - decided/2

    which is 0 once the deciding set is under way, and a half-set where either
    outcome is still possible (one-nil, where the current set may or may not
    end it). Progress through the current set comes from its game count, a set
    being about twelve games at its longest before a breaker.
    """
    total = _duration_for(discipline)
    per_set = total / 2.5          # a best-of-3 averages about two and a half sets
    try:
        a_sets, b_sets = live[0] or [], live[1] or []
        decided = max(max(len(a_sets), len(b_sets)) - 1, 0)   # last entry is in play
        games = int(a_sets[-1] or 0) + int(b_sets[-1] or 0) if a_sets or b_sets else 0
        part = min(games / 12.0, 1.0)
        additional = max(sets_to_win - 1 - decided / 2.0, 0.0)
        remaining_sets = additional + (1.0 - part)
    except Exception:
        remaining_sets = 1.0
    return max(int(remaining_sets * per_set), 5)


async def recompute_expected_starts(db, tournament_id: int, play_date: date,
                                    venue_tz: Optional[str] = None) -> int:
    """Chain expected starts per court, anchored on what has actually happened.

    Three things decide a slot, in order of how much they are trusted:

    * a FINISHED match ends the guesswork for everything behind it — the next
      slot starts at its recorded completed_at, not at a constant added to a
      constant;
    * a LIVE match has not finished, so everything after it is at least now plus
      whatever that match has left to run;
    * a slot whose estimate has already passed, while nothing on that court has
      started it, is wrong on its face — it cannot be in the past, so it is
      clamped to now.

    Without these the chain re-ran every 15 minutes from unchanged inputs and
    produced the same numbers all day: a static projection wearing the clothes
    of a live one.
    """
    from zoneinfo import ZoneInfo

    now = datetime.now(timezone.utc)

    rows = (await db.execute(
        select(ScheduleEntry).where(
            ScheduleEntry.tournament_id == tournament_id,
            ScheduleEntry.play_date == play_date,
        ).order_by(ScheduleEntry.court, ScheduleEntry.court_order))).scalars().all()
    if not rows:
        return 0

    match_ids = {r.match_id for r in rows if r.match_id}
    matches = {}
    if match_ids:
        found = (await db.execute(
            select(Match).where(Match.id.in_(match_ids)))).scalars().all()
        matches = {m.id: m for m in found}

    tz = None
    if venue_tz:
        try:
            tz = ZoneInfo(venue_tz)
        except Exception:
            tz = None
    tz = tz or timezone.utc

    by_court: dict[str, list] = {}
    for r in rows:
        by_court.setdefault(r.court or '', []).append(r)

    touched = 0
    for court, slots in by_court.items():
        prev_end: Optional[datetime] = None
        for s in sorted(slots, key=lambda x: x.court_order):
            m = matches.get(s.match_id) if s.match_id else None
            dur = _duration_for(s.discipline)
            before = (s.expected_start_at, s.expected_source)

            # Resolve the printed clock FIRST, so every branch below can write a
            # start rather than leaving whatever was there before. The live and
            # finished branches used to skip this, which meant a value stored
            # under an older, buggier version was never corrected — a match that
            # began at 11:00 kept a stale naive-local 11:00 and, once read as
            # UTC, displayed as 7:00 AM.
            #
            # Normalised to UTC on the way in: the column is naive on SQLite, so
            # an aware venue-local value loses its offset and lands on a
            # different clock from anything derived from now().
            printed = _parse_clock(s.start_time_local)
            printed_dt = (datetime.combine(play_date, printed, tzinfo=tz)
                          .astimezone(timezone.utc) if printed else None)

            finished_at = _aware(getattr(m, 'completed_at', None)) if m else None
            is_live = bool(m and getattr(m, 'live_scores_json', None)
                           and not getattr(m, 'winner_id', None))

            if finished_at or is_live:
                # Already under way or done. Its start is history — the printed
                # time is the best record of it — so do not re-estimate it. What
                # the chain needs from here is when the court frees up.
                if printed_dt:
                    s.expected_start_at = printed_dt
                    s.expected_source = 'printed'
                elif prev_end:
                    s.expected_start_at = s.expected_start_at or prev_end
                    s.expected_source = s.expected_source or 'estimated'
                prev_end = finished_at if finished_at else now + timedelta(
                    minutes=_remaining_minutes(
                        getattr(m, 'live_scores_json', None), s.discipline))
                s.estimated_duration_min = dur
                if before != (s.expected_start_at, s.expected_source):
                    touched += 1
                continue

            if s.start_type == 'fixed' and printed_dt:
                expected, source = printed_dt, 'printed'
            elif s.start_type == 'not_before' and printed_dt:
                expected = max(printed_dt, prev_end) if prev_end else printed_dt
                source = 'printed' if expected == printed_dt else 'estimated'
            elif prev_end:
                expected, source = prev_end, 'estimated'
            else:
                expected, source = printed_dt, ('printed' if printed_dt else None)

            # Clamp only a CHAINED estimate, never a printed start.
            #
            # A time the tournament printed is a fact about the schedule: the
            # first match on a court began when the sheet said it would,
            # whether or not we can see it. We often cannot — ESPN does not
            # cover doubles or qualifying, so those slots have no match row, no
            # live score and no completed_at, and clamping on that silence
            # reported an 11:00 AM doubles match as starting at 4:27 PM purely
            # because the hour had passed.
            #
            # A chained estimate is different: it is our own guess, and a guess
            # that has already expired cannot be right.
            if expected and expected < now and source == 'estimated':
                expected = now

            s.expected_start_at = expected
            s.expected_source = source
            s.estimated_duration_min = dur
            if before != (expected, source):
                touched += 1
            if expected:
                prev_end = expected + timedelta(minutes=dur)

    await db.commit()
    return touched
