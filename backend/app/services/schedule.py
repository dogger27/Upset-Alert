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
import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, or_, select, update

from app.services.sofascore_doubles import _sheet_surnames
from app.models.schedule import (ScheduleChange, ScheduleDocument,
                                 ScheduleEntry, ScheduleEntryPlayer)
from app.models.tournament import Draw, DrawEntry, Match
from app.services.oop_parser import COUNTRY_CODES, parse_pdf
from app.services.rankings import _norm

logger = logging.getLogger(__name__)

# Seeds for the chain. No historical durations exist to fit these to —
# `matches.completed_at` is populated but there is no start time to subtract —
# so they are deliberate constants, replaceable once this feature has generated
# a season of its own data. They only affect slots with no stated time, and
# every live result collapses the error for everything after it on that court.
_DURATION_MIN = {("singles", 3): 105, ("singles", 5): 170, ("doubles", 3): 80}
_DEFAULT_DURATION = 105

# Minutes between one match finishing on a court and the next starting: warm-up,
# the players walking on, the court being swept.
#
# 21 is measured, not assumed — from the first four changeovers we could time at
# Cincinnati 2026 (20, 21, 21, 23). Without it the chain had every match
# starting the instant the previous one ended, so a court's estimates ran
# progressively early through the day.
#
# Superseded per tournament by _observed_changeover() once enough real gaps have
# been recorded there; this is only the starting point.
_DEFAULT_CHANGEOVER_MIN = 21

# Below this many observations a median says more about luck than the venue.
_MIN_CHANGEOVER_SAMPLES = 4

# Seeding and entry status — [1], [WC], [Q], [LL]. Removed wherever they sit,
# not just at the front: the tours disagree about where they go, and the ATP
# puts them AFTER the country ("Tristan MCCORMICK USA [1]"), which leaves the
# country no longer final and so no longer strippable. A player's name never
# contains brackets, so there is nothing else here to lose.
_SEED_RE = re.compile(r'\[[^\]]*\]')
_TRAILING_CODE_RE = re.compile(r'\s+([A-Z]{3})\s*$')
_CLOCK_RE = re.compile(r'^(\d{1,2})[:.](\d{2})\s*(am|pm)?$', re.I)

# Country codes are recognised from a list, not from their shape. The previous
# test was `\b[A-Z]{3}\b`, and the sheets print surnames in capitals — so it
# deleted the surname from "Orlando LUZ BRA" and left a player identified only
# as "Orlando", which then matched every other Orlando in the draw. Any
# three-letter surname hits this: LUZ, KIM, LEE, WOO, ONS.
#
# The list itself lives in oop_parser, which needs the same one to tell a
# wrapped nationality from the sheet's own furniture. One copy: two country
# tables drift, and a name keeps its country on one screen and loses it on the
# next with nothing logged either way.
_COUNTRY_CODES = COUNTRY_CODES

# "QS" is qualifying singles, "MD" men's doubles — the sheet states both
# dimensions in one code, which is exactly how they are filtered.
_EVENT_CODE_RE = re.compile(r'\b([MWQXBG])([SD])\b')

# The qualifying rounds, spelled out, because "starts with Q" also catches QF
# and stamped every quarter-final as qualifying. These are exhaustive against
# what the parser can produce: oop_parser.ROUND_RE emits only F, SF, QF, R\d+,
# Q, Q1..Q9, FQ and 1R..4R, of which Q/Q\d/FQ are the qualifying ones.
_QUALI_ROUND_RE = re.compile(r'^(?:Q\d?|FQ)$', re.I)


def _clean_name(raw: str) -> str:
    """Strip the seeding and country the sheet lays out around a name.

    The country is only ever a name's LAST token, so only the last token is
    considered — and only when it is a code we recognise. A doubles slot puts
    two names in one string ("O. LUZ BRA / R. MATOS BRA"), so each side of the
    slash is trimmed on its own.
    """
    parts = []
    for part in _SEED_RE.sub(' ', raw or '').split('/'):
        part = ' '.join(part.split())
        m = _TRAILING_CODE_RE.search(part)
        if m and m.group(1) in _COUNTRY_CODES:
            part = part[:m.start()].strip()
        parts.append(part)
    return ' / '.join(p for p in parts if p).strip()


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


def _classify(match, *, before_main: bool = False, resolved: bool = True,
              seen_qualifying: bool = False) -> tuple[str, str]:
    """(stage, discipline) — from the event code when present, else the parse.

    `before_main` and `resolved` are the last resort, for sheets that say
    nothing at all. See the note on the fallback below.
    """
    blob = ' '.join([match.court or '', match.round or '', match.discipline or ''])
    m = _EVENT_CODE_RE.search(blob)
    if m:
        first, second = m.group(1), m.group(2)
        stage = 'qualifying' if first == 'Q' else 'main'
        discipline = 'doubles' if second == 'D' else 'singles'
        if first == 'X':
            discipline = 'mixed'
        return stage, discipline
    stage = 'qualifying' if _QUALI_ROUND_RE.match((match.round or '').strip()) else 'main'
    # Some sheets carry NEITHER an event code nor a round. A tournament whose
    # qualifying has a day to itself has nothing to disambiguate, so it prints
    # nothing: Winston-Salem's Saturday is eight matches under three court
    # headings and a date, with no "QS", no "Q1" and no "Qualifying" anywhere on
    # the page. Read literally that is a main-draw day, which is how eight
    # qualifying matches came to be filed as main draw with no round at all.
    #
    # Two facts settle it without the sheet's help: the day is BEFORE the main
    # draw starts, and not one player on it is in the main draw's entry list.
    # Both, never either alone — a main-draw slot on an early sheet still
    # resolves to entries, and a name we merely failed to match is not thereby a
    # qualifier. Deliberately silent about WHICH qualifying round: nothing here
    # knows, and a wrong Q2 is worse than an honest Q.
    # ...or the same players were on a qualifying row earlier this week.
    #
    # `before_main` alone misses the last qualifying round, which is played ON
    # the main draw's first day — Winston-Salem ran Q2 on the morning of its
    # R64, and every one of those four rows came through as main draw with no
    # round at all. The date cannot separate them because they share it.
    #
    # Having played qualifying here two days ago can. It is a fact about these
    # players at this tournament, it needs no sheet to state it, and it cannot
    # be true of a main-draw entrant — nobody plays qualifying after they are in
    # the draw. Still requires the row to resolve to no main-draw entry, so a
    # qualifier who has since come through is read as the main-draw player they
    # now are.
    #
    # SINGLES ONLY — hence discipline being settled first, below. Both signals
    # are facts about the SINGLES draw and neither survives the trip to a
    # doubles row. `resolved` asks whether these players are in `draw_entries`,
    # which holds no doubles draw at all, so EVERY doubles slot ever printed is
    # unresolved: the evidence half is vacuously true and the test collapses to
    # the surname half alone. And that half is not a collision here, it is the
    # ordinary case — losing singles qualifying on Saturday and playing
    # main-draw doubles on Monday is what doubles players and qualifiers do,
    # so "nobody plays qualifying after they are in the draw" is simply false
    # across events. Winston-Salem 2026-08-24 printed three main-draw doubles
    # matches and the page badged two of them "Q": the two holding Polmans and
    # Oberleitner, both of whom had played singles qualifying that week.
    # Krajicek/Mektic shared a surname with nobody and stayed main — so three
    # identical rows off one sheet rendered two different ways.
    #
    # A doubles row can still BE qualifying: the event code (QD) and a printed
    # Q round both say so above, and both are the sheet stating it rather than
    # us guessing.

    # AN UNRESOLVED SINGLES SLOT IS NOT DOUBLES. The parser calls a row doubles
    # when a side carries two names, which is true of a doubles team and equally
    # true of "Pascual Ferra OR Suresh" — so every TBD singles slot came through
    # as doubles. That is not cosmetic: discipline is part of pairing_key, and
    # _dedupe_day refuses to merge rows of different disciplines, so when the
    # slot settled the resolved row could never absorb the unresolved one. Both
    # stayed, and the sheet showed a doubles match that does not exist.
    #
    # A doubles alternative names a PAIR — "O. Luz / R. Matos" — so the slash is
    # what tells them apart, not the count.
    tbd = bool(getattr(match, 'tbd', False))
    two_up = any('/' in n for n in list(match.side_a) + list(match.side_b))
    discipline = 'doubles' if (match.is_doubles and (not tbd or two_up)) else 'singles'

    if (discipline == 'singles' and stage == 'main' and not resolved
            and (before_main or seen_qualifying)):
        stage = 'qualifying'
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


def _match_tokens(raw: str) -> tuple[set, set]:
    """The two token sets one name may be matched under, in priority order.

    The sheet and the draw do not spell umlauts the same way and neither is
    wrong. `rankings._norm` expands them the German way (o-umlaut -> "oe"),
    which is how Wikipedia and Tennis Explorer write them and therefore how
    `draw_entries.name` is stored; the ATP/WTA order-of-play sheets print
    plain ASCII. So "Mees Roettgering" in the draw and "ROTTGERING" on the
    sheet never met: no draw_entry_id, no match_id, and on 2026-08-25 a
    main-draw R32 sat on the live page with no round badge, no player links
    and no scores, while the bracket had known the pairing for a day.
    `_ascii_fold` is the fold under which both spellings agree. It already
    existed here as half of `_fold`, whose own docstring names this bug —
    the ingest's two matchers were simply never moved onto it, which is the
    usual shape of a fix applied to one copy of two.

    The ASCII fold is a FALLBACK, never the first test, because it is
    strictly looser: a draw holding both "Mueller" and "Muller" folds them
    together, so the exact spelling has to get first refusal.
    """
    cleaned = _clean_name(raw or '')
    # `_clean_name`, NOT `_fold`, owns the stripping — it gates the trailing
    # code on _COUNTRY_CODES, and _fold takes any three capitals. Folding a
    # cleaned name stripped twice and turned "[WC] Luca POW GBR" into "Luca",
    # which is a subset of "Luca Van Assche": a confidently wrong player.
    # Three capitals are a surname as often as a country — LUZ, GUO, POW.
    return ({t for t in _norm(cleaned).split() if len(t) > 2},
            {t for t in _ascii_fold(cleaned).split() if len(t) > 2})


async def _resolve_players(db, draws: list, tour: Optional[str], names: list) -> list:
    """Map printed names onto draw_entries. Closed-set matching, not extraction:
    the entrants are already known, so every token from the sheet must appear in
    the candidate. Measured at 100% on main-draw singles; qualifying cannot
    resolve at all, because losing qualifiers never reach draw_entries."""
    out = []
    for raw in names:
        probes = _match_tokens(raw)
        found = None
        for idx, probe in enumerate(probes):
            if not probe:
                continue
            for draw in draws:
                for eid, ent_tokens in ((e[0], e[1 + idx]) for e in draw['entries']):
                    if probe <= ent_tokens:
                        found = eid if found is None else found
            if found is not None:
                break
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
        for idx, probe in enumerate(_match_tokens(raw)):
            if not probe:
                continue
            # Same two-fold priority as _resolve_players: take the ASCII fold
            # only when the exact one names nobody, so the looser test can
            # never widen a set the strict one had already narrowed.
            hits = {e[0] for draw in draws for e in draw['entries']
                    if probe <= e[1 + idx]}
            if hits:
                out |= hits
                break
    return out


async def _sync_players(db, entry, na: list, nb: list, ids: list) -> list:
    """Make a slot's stored players say exactly what THIS sheet prints.

    Write-once was the bug. `raw_name` used to be written only in the
    `if entry is None` branch, so whatever the FIRST revision printed was
    frozen into the row for good — and the bracket resolution in
    `ingest_document` deliberately rewrites the names of a slot it settles.
    Winston-Salem 2026-08-25: an early sheet printed the Medvedev slot as an
    unresolved choice, the resolver replaced both players with their DRAW
    names, and when the next two revisions printed the settled pair the way
    every other row is printed ("[WC] Martin DAMM USA") the matched row kept
    "Martin Damm" — Title Case, so no country, so no flag, and no [WC] badge,
    beside sixteen rows carrying all three. Four rows across three
    tournaments were stuck that way. Anything re-derived from the sheet on
    every pass belongs in the UPDATE path too, exactly like `stage` and
    `start_note`.

    Safe against undoing `resolve_settled_alternatives`, which deletes the
    losing alternative of a side the bracket has already decided: a revision
    that still prints "A or B" re-adds it here, and that same resolver runs
    again at the end of this ingest and collapses it again before anything
    reads the day.

    Returns the (old, new) pairs that actually changed, for the log.
    """
    rows = (await db.execute(
        select(ScheduleEntryPlayer).where(
            ScheduleEntryPlayer.schedule_entry_id == entry.id))).scalars().all()
    by_slot = {(p.side, p.position): p for p in rows}
    changed = []
    for side, names in (('a', na), ('b', nb)):
        base = 0 if side == 'a' else len(na)
        for pos, nm in enumerate(names, 1):
            eid = ids[base + pos - 1] if base + pos - 1 < len(ids) else None
            row = by_slot.pop((side, pos), None)
            if row is None:
                db.add(ScheduleEntryPlayer(
                    schedule_entry_id=entry.id, side=side, position=pos,
                    raw_name=nm, draw_entry_id=eid))
                continue
            if row.raw_name != nm:
                changed.append((row.raw_name, nm))
                row.raw_name = nm
            # Never trade an id already proved for a None this pass could not
            # resolve: a qualifier reaches draw_entries days after the sheet
            # first names them.
            if eid is not None:
                row.draw_entry_id = eid
    # A side that SHRANK — the phantom "DAMM / SHELBAYH" settling to one name.
    for row in by_slot.values():
        await db.delete(row)
    return changed


def _printed_name(printed: dict, draw_names: dict, eid, fallback: str) -> str:
    """The sheet's own spelling of the player the bracket says came through.

    A settled slot must read like every other row on the page: SURNAME in
    capitals, nationality, seeding marker. The draw's name is a different
    rendering of the same person and carries none of those. Only when the
    printed alternatives cannot be pinned to this player does the draw name
    stand in.
    """
    hits = printed.get(eid) or []
    return hits[0] if len(hits) == 1 else (draw_names.get(eid) or fallback)


def _queue_verification(doc, tournament, play_date, url, pdf_bytes, entries):
    """Drop the PDF and a work order where the host's verifier cron finds them.

    The verifier is a headless Claude Code run OUTSIDE this container (the CLI
    lives on the host, not in the image), so the handoff is the mounted data
    dir: /data/oop_pdfs holds the PDF, queue/ the marker. Its verdict comes
    back the same way — results/*.json, swept into app_log by the scheduler —
    because this app has been burned by second writers on the DB before.

    Best-effort by design: a verification that cannot be queued must never
    cost the ingest, so failures land in the ordinary log and nothing raises.
    """
    try:
        base = "/data/oop_pdfs"
        os.makedirs(f"{base}/queue", exist_ok=True)
        with open(f"{base}/{doc.id}.pdf", "wb") as f:
            f.write(pdf_bytes)
        marker = {
            "doc_id": doc.id, "tournament_id": tournament.id,
            "tournament": tournament.name, "play_date": str(play_date),
            "url": url, "entries": entries,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(f"{base}/queue/{doc.id}.json", "w") as f:
            json.dump(marker, f)
    except Exception:
        logging.getLogger(__name__).exception(
            "could not queue OOP verification for doc %s", doc.id)


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
        # An OOP revision that parsed to NOTHING is exactly the revision most
        # worth independent eyes — a parser regression looks like this.
        await db.commit()
        _queue_verification(doc, tournament, play_date, url, pdf_bytes, 0)
        return {'document_id': doc.id, 'kind': meta.get('kind'), 'entries': 0}

    # Roster for resolution: every draw of this tournament.
    draw_rows = (await db.execute(
        select(Draw).where(Draw.tournament_id == tournament.id))).scalars().all()
    draws = []
    for d in draw_rows:
        ents = (await db.execute(
            select(DrawEntry.id, DrawEntry.name).where(DrawEntry.draw_id == d.id))).all()
        # Each entry carries BOTH folds — see _match_tokens. Built once here
        # rather than per name, because every slot on the sheet probes it.
        draws.append({'draw': d,
                      'entries': [(e[0], set(_norm(e[1] or '').split()),
                                   set(_ascii_fold(e[1] or '').split()))
                                  for e in ents],
                      'names': {e[0]: e[1] for e in ents}})

    # entry id -> draw id, so a resolved player also tells us which draw the
    # slot belongs to.
    entry_draw = {}
    draw_by_id = {}
    entry_name = {}
    for d in draws:
        draw_by_id[d['draw'].id] = d['draw']
        entry_name.update(d['names'])
        for eid, _tokens, _ascii in d['entries']:
            entry_draw[eid] = d['draw'].id

    seen_keys = []
    per_court: dict[str, list] = {}
    # The earliest main draw starts here. A slot printed before it, by players
    # none of whom are in it, is qualifying — see _classify.
    main_start = min((d['draw'].start_date for d in draws if d['draw'].start_date),
                     default=None)
    before_main = bool(main_start and play_date < main_start)

    # Surnames already seen on a qualifying row of this tournament. One query,
    # and it is what lets the LAST qualifying round be recognised on a day it
    # shares with the main draw.
    quali_names: set = set()
    for row in (await db.execute(
            select(ScheduleEntryPlayer.raw_name)
            .join(ScheduleEntry, ScheduleEntry.id == ScheduleEntryPlayer.schedule_entry_id)
            .where(ScheduleEntry.tournament_id == tournament.id,
                   ScheduleEntry.stage == 'qualifying',
                   ScheduleEntry.play_date >= play_date - timedelta(days=14),
                   ScheduleEntry.play_date < play_date))).scalars().all():
        quali_names |= _sheet_surnames([row])

    for m in matches:
        names_a = list(m.side_a)
        names_b = list(m.side_b)
        # Resolved BEFORE classifying now, because whether these players are in
        # the main draw is one of the two things that identifies a qualifying
        # sheet which names itself nothing.
        ids = await _resolve_players(db, draws, m.tour, names_a + names_b)
        stage, discipline = _classify(
            m, before_main=before_main, resolved=any(ids),
            seen_qualifying=bool(quali_names
                                 & _sheet_surnames(names_a + names_b)))
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
    renamed: list = []
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
            else:
                for field, new in (('court', court), ('court_order', order),
                                   ('start_time_local', m.time), ('start_type', start_type)):
                    old = getattr(entry, field)
                    if str(old) != str(new) and old is not None:
                        db.add(ScheduleChange(
                            schedule_entry_id=entry.id, document_id=doc.id,
                            field=field, old_value=str(old), new_value=str(new)))

            # ONE path for players, new row or old — see _sync_players for why
            # the create-only version froze a stale rendering into four rows.
            renamed += await _sync_players(db, entry, na, nb, ids)

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
                    # Keep the SHEET's spelling of whoever came through: the
                    # alternatives are printed right here in the same form as
                    # every settled row, and the draw's rendering is not.
                    printed: dict = {}
                    for nm, eid in zip(na + nb, ids):
                        if eid is not None:
                            printed.setdefault(eid, []).append(nm)
                    na = [_printed_name(printed, entry_name, found.player1_id, na[0])]
                    nb = [_printed_name(printed, entry_name, found.player2_id, nb[0])]
                    ids = [found.player1_id, found.player2_id]
                    entry.is_tbd = False
                    entry.tbd_side = None
                    renamed += await _sync_players(db, entry, na, nb, ids)
                    # The row's identity has to move with its content. This key
                    # was derived from the alternatives just replaced ("Tien OR
                    # Tiafoe"); leaving it there means the NEXT revision, which
                    # prints the settled pair, hashes to something else, matches
                    # nothing, and inserts the same match a second time. That is
                    # exactly how Tiafoe/Auger-Aliassime came to be listed twice.
                    #
                    # But only if the key is FREE. An earlier revision may have
                    # printed the settled pair and already stored a row under
                    # it, which is the ordinary case for a slot that resolves
                    # mid-day: this row and that one are then the same slot, and
                    # taking the key is a unique-constraint violation, not a
                    # merge. It does not even fail here — the next query's
                    # autoflush raises it, so the traceback lands on an
                    # unrelated statement and the WHOLE DAY's ingest rolls back
                    # over one duplicated slot. Cincinnati lost a full revision
                    # that way on 2026-08-22.
                    #
                    # Leaving the old key is safe: it is still unique, and the
                    # two rows now carry identical players and the same
                    # match_id, which is the first relation _dedupe_day tests a
                    # few lines below. Merging is its job; this only has to
                    # avoid making the merge impossible to reach.
                    settled_key = _pairing_key(
                        tournament.id, play_date, discipline, na, nb, ids)
                    taken = (await db.execute(
                        select(ScheduleEntry.id).where(
                            ScheduleEntry.pairing_key == settled_key,
                            ScheduleEntry.id != entry.id))).scalars().first()
                    if taken is None:
                        entry.pairing_key = settled_key
            elif side_a_ids or side_b_ids:
                any_id = (side_a_ids + side_b_ids)[0]
                entry.draw_id = entry_draw.get(any_id)

            entry.court = court
            entry.court_order = order
            # Re-stamped rather than set once at creation, so a correction to
            # _classify reaches the rows it already got wrong. Safe to move on an
            # existing row precisely because it is NOT part of pairing_key:
            # discipline is, and so cannot change under a matched entry, but
            # stage is free to be re-derived from the sheet on every pass.
            entry.stage = stage
            entry.start_type = start_type
            entry.start_time_local = m.time
            entry.start_note = getattr(m, 'start_raw', None)
            # A row created THIS pass always takes the sheet's word for it.
            # The guard below protects an EXISTING row that already settled
            # from being re-marked unresolved by a stale revision — but on a
            # fresh row it meant a slot that resolved to a bracket match kept
            # the default False, and an "A or B" side rendered as a team.
            if entry.id is None or found is None or not m.tbd:
                entry.is_tbd = bool(m.tbd)
                entry.tbd_side = getattr(m, 'tbd_side', None)
            entry.round_label = (m.round or entry.round_label
                                 or unanimous.get((stage, discipline)))
            entry.printed_score = getattr(m, 'printed_score', None)
            entry.last_seen_at = datetime.now(timezone.utc)
            entry.last_document_id = doc.id
            written += 1

    await db.flush()
    await _dedupe_day(db, tournament.id, play_date)
    await _renumber_courts(db, tournament.id, play_date)
    await db.commit()

    if renamed:
        # A slot's printed identity changing is worth a line: it is either the
        # tournament substituting a player, or a stale rendering healing.
        #
        # AFTER the commit, and that is not a style choice. `app_log` opens its
        # OWN session, and SQLite allows exactly one writer: called while this
        # ingest still held uncommitted writes it blocked on the lock the same
        # task was holding, so the log either failed with "database is locked"
        # or stalled the whole ingest waiting for itself. Every other writer in
        # this function's tail — the resolver, the invariants — is here for the
        # same reason.
        from app.services.system_log import app_log
        await app_log(
            "info", "order_of_play",
            f"{len(renamed)} schedule player name(s) re-stamped from the sheet "
            f"for {tournament.name} on {play_date}: "
            + "; ".join(f"{o!r}->{n!r}" for o, n in renamed[:5]),
            {"tournament_id": tournament.id, "play_date": str(play_date),
             "renamed": [[o, n] for o, n in renamed[:20]]})

    # AFTER the commit, in this order: the LAW first, then the verifier queue.
    # The invariants (schedule_invariants.py) are the deterministic record of
    # every schedule bug ever shipped; they run on what the day ACTUALLY
    # stored, alert on their own, and the verifier's runner re-checks them
    # after its verdict — so an LLM "clean" cannot stand against them.
    try:
        # A sheet released AFTER a result must not print a choice the draw has
        # already made — collapse before the law looks, so a PDF-release-time
        # "or" over a decided match never even exists on the site.
        await resolve_settled_alternatives(db, tournament.id)
        from app.services.schedule_invariants import check_and_log
        await check_and_log(db, tournament, play_date)
    except Exception:
        logging.getLogger(__name__).exception(
            "invariant check failed for %s %s", tournament.id, play_date)
    _queue_verification(doc, tournament, play_date, url, pdf_bytes, written)
    return {'document_id': doc.id, 'entries': written, 'kind': meta.get('kind')}


async def _renumber_courts(db, tournament_id: int, play_date: date) -> None:
    """Give every slot on a court a distinct position, in running order.

    A sheet revised mid-day lists only what is still to come, so enumerating
    within one document renumbers those matches from 1 while entries carried
    over from an earlier revision keep their original positions — and the two
    sets collide. Two matches at position 2 on the same court then make "which
    came first" unanswerable, which is what let a match that had not started be
    reported as completed because its position-mate had finished.

    Existing order is preserved where it is unambiguous; first_seen_at breaks
    ties, since a slot recorded earlier was printed earlier.
    """
    rows = (await db.execute(
        select(ScheduleEntry).where(
            ScheduleEntry.tournament_id == tournament_id,
            ScheduleEntry.play_date == play_date,
        ))).scalars().all()

    by_court: dict[str, list] = {}
    for r in rows:
        by_court.setdefault(r.court or '', []).append(r)

    for slots in by_court.values():
        # _aware on every value: the fallback below is tz-aware, so a row read
        # back from SQLite (naive) sorted against a row with no first_seen_at
        # would compare naive with aware and raise.
        slots.sort(key=lambda r: (r.court_order,
                                  _aware(r.first_seen_at)
                                  or datetime.min.replace(tzinfo=timezone.utc)))
        for position, entry in enumerate(slots, 1):
            if entry.court_order != position:
                entry.court_order = position


def _name_tokens(raw: str) -> set:
    """The tokens of one printed name worth matching on. Mirrors the closed-set
    matching in `_resolve_players`: initials and country codes are dropped by
    length, so "O. Luz" and "Orlando LUZ BRA" both reduce to {luz}."""
    return {t for t in _norm(_clean_name(raw or '')).split() if len(t) > 2}


def _side_tokens(entry, side: str) -> list:
    """One side as printed, name by name — either the partners of a settled
    side or the competing alternatives of an unresolved one."""
    return [_name_tokens(p.raw_name)
            for p in sorted(entry.players, key=lambda x: x.position)
            if p.side == side]


def _printed_pairing(entry) -> str:
    """The row as the sheet printed it, for log lines a human has to read."""
    by = {'a': [], 'b': []}
    for p in sorted(entry.players or [], key=lambda x: (x.side, x.position)):
        by[p.side].append(p.raw_name or '?')
    return f"{' / '.join(by['a']) or '?'} vs {' / '.join(by['b']) or '?'}"


def _side_resolves(printed: list, alternatives: bool, settled: set) -> bool:
    """Does this side of a TBD slot correspond to this side of a settled one?

    Containment runs one way only. The sheet abbreviates alternatives ("O. Luz
    / R. Matos") where it spells settled names out ("Orlando LUZ BRA"), so the
    printed tokens must appear in the settled side, never the reverse.

    A side of alternatives needs ONE of them to match — that is what being
    decided means. A side that was already settled needs all of its names,
    since nothing about it was in question.
    """
    if not printed:
        return False
    if alternatives:
        return any(toks and toks <= settled for toks in printed)
    return all(toks and toks <= settled for toks in printed)


def _resolves(tbd, settled) -> bool:
    """True when `settled` is `tbd` with its alternatives decided — i.e. the
    two rows are the same slot, printed either side of a result.

    Only a row that declared itself unresolved can be absorbed this way, which
    is what keeps the test from collapsing genuinely different matches. The
    structural guarantee is that a feeding match puts both its players on the
    SAME side of the next round: an R16 "Melo/Zverev vs Luz/Matos" therefore
    cannot satisfy both sides of the QF slot it feeds, however much its names
    overlap.
    """
    if not tbd.is_tbd:
        return False
    # `settled` need not be fully settled — only MORE settled. A sheet reissued
    # while one feeder match is still on court decides one side and leaves the
    # other, and that row is the same slot as the one that had both undecided.
    # Requiring a strict subset is what keeps this from collapsing two genuinely
    # different pending slots: one of them has to have decided something.
    if not set(settled.tbd_side or "") < set(tbd.tbd_side or ""):
        return False
    alt = tbd.tbd_side or ''
    done = {s: set().union(set(), *_side_tokens(settled, s)) for s in ('a', 'b')}
    still_open = set(settled.tbd_side or "")
    # Sides swap between revisions often enough to be worth trying both ways.
    for x, y in (('a', 'b'), ('b', 'a')):
        # A side the other row has ALSO left open is compared as alternatives
        # against alternatives, so one name landing is enough on both counts.
        if (_side_resolves(_side_tokens(tbd, 'a'), 'a' in alt or x in still_open, done[x])
                and _side_resolves(_side_tokens(tbd, 'b'), 'b' in alt or y in still_open, done[y])):
            return True
    return False


def _same_pairing(a, b) -> bool:
    """Two settled rows describing the same match.

    Compared on the players themselves rather than on `pairing_key`, so it
    still holds when the key formula changes underneath stored rows — which it
    does whenever name cleaning is corrected. The same two teams cannot meet
    twice on one day, so equality on both sides is conclusive.
    """
    if a.is_tbd or b.is_tbd:
        return False
    A = {s: set().union(set(), *_side_tokens(a, s)) for s in ('a', 'b')}
    B = {s: set().union(set(), *_side_tokens(b, s)) for s in ('a', 'b')}
    if not all((A['a'], A['b'], B['a'], B['b'])):
        return False

    def agree(x, y):
        """Equal, or one a subset of the other.

        A CORRECTED PARSER MAKES A ROW GAIN A PLAYER, and the old row is then a
        strict subset of the new one rather than equal to it — so plain
        equality could not see that they are the same slot, and both stayed on
        the page. That is how "KRAJICEK / MEKTIC vs CABRAL" ended up printed
        beside "KRAJICEK / MEKTIC vs CABRAL / TRACY" the moment the sheet was
        re-read with the all-caps name fix in place.

        Subset is safe here for the reason equality was: the same team cannot
        meet the same opponents twice in a day. For two DIFFERENT matches to
        satisfy this, one side would have to be a sub-team of the other and the
        opposing side identical — which is a player entered twice against the
        same opponents, in the same discipline (disciplines are checked by the
        caller), on the same day.
        """
        return x == y or x < y or y < x

    return ((agree(A['a'], B['a']) and agree(A['b'], B['b']))
            or (agree(A['a'], B['b']) and agree(A['b'], B['a'])))


def _superseded(old, new, latest_pool: list) -> bool:
    """True when `new` is `old`'s slot with one side replaced — a withdrawal.

    A lucky loser stepping in for a late withdrawal reprints the slot with one
    player swapped: Winston-Salem's Monday sheet turned "SONEGO vs KOPRIVA"
    into "SONEGO vs [LL] HERBERT". That is the same slot, but no other
    relation can see it: the pairing key moved (a player changed), neither row
    is TBD, and the new row has no match_id because draw_entries still list
    the player who withdrew — the bracket only learns of the substitution when
    the wiki scrape catches up. So the dead pairing stayed on the page as a
    sixteenth match and shifted the court order under every real one.

    The look-alike to keep out is a player printed twice on one day (rain
    backlog: R1 done, R2 to come). Three guards separate them:

    * `old` must be strictly older by document — its pairing fell off a later
      revision. Two rows on the same revision are never each other's
      replacement.
    * the caller must have established that `old` was never played (no start,
      no result, bracket match undecided) — a backlog row that dropped off
      the sheet dropped off because it FINISHED.
    * the replaced player must appear nowhere on the latest revision. A
      player still in the tournament is on the sheet somewhere; one who
      withdrew is not.
    """
    if old.is_tbd or new.is_tbd:
        return False
    if (old.last_document_id or 0) >= (new.last_document_id or 0):
        return False
    # Two rows pinned to different bracket matches are different slots, full
    # stop — no amount of name overlap overrides the draw.
    if old.match_id and new.match_id and old.match_id != new.match_id:
        return False
    if old.stage != new.stage:
        return False
    # The generic preference in _dedupe_day keeps whichever row names more
    # players. The newer row must win here, so never claim a supersede the
    # preference would resolve the other way.
    if len(old.players or []) > len(new.players or []):
        return False

    A = {s: _side_tokens(old, s) for s in ('a', 'b')}
    B = {s: _side_tokens(new, s) for s in ('a', 'b')}

    def union(sides):
        return set().union(set(), *sides)

    def agree(x, y):
        # Same subset-or-equal test as _same_pairing, for the same reason:
        # one revision abbreviates ("V. Kopriva") what another spells out.
        return bool(x and y) and (x == y or x < y or y < x)

    # Sides swap between revisions, and the replaced player can be on either
    # side — so try both mappings, and within each let either pair be the one
    # that stayed.
    for pairs in ((('a', 'a'), ('b', 'b')), (('a', 'b'), ('b', 'a'))):
        for (so, sn), (co, cn) in (pairs, pairs[::-1]):
            if not agree(union(A[so]), union(B[sn])):
                continue
            old_gone, new_come = union(A[co]), union(B[cn])
            # Wholly replaced, not partially: a doubles team that changed one
            # partner shares tokens, and that case is not decided here.
            if not old_gone or not new_come or (old_gone & new_come):
                continue
            if any(p and any(agree(p, q) for q in latest_pool)
                   for p in A[co]):
                continue
            return True
    return False


async def _absorb(db, keep, drop) -> None:
    """Fold one row into another: the surviving row inherits the earlier
    first_seen_at (it is when the slot was first printed, and _renumber_courts
    breaks ties on it) and every change ever recorded against the loser."""
    # Compared through _aware because these two rows reliably differ in kind: a
    # row loaded from SQLite is naive, while one written earlier in this same
    # session still holds the aware value it was assigned. Comparing them raised
    # TypeError and, since _dedupe_day runs first, took the whole ingest with it
    # — the schedule silently stopped updating rather than losing one row.
    drop_first, keep_first = _aware(drop.first_seen_at), _aware(keep.first_seen_at)
    if drop_first and (not keep_first or drop_first < keep_first):
        keep.first_seen_at = drop.first_seen_at
    # A doubles result lives on the ROW — there is no match to read it back
    # from, because doubles draws have no rows in `matches` at all. So folding
    # two doubles rows together can delete the only record that the match was
    # played, and the survivor goes back to reading "scheduled" with the court
    # behind it stuck waiting on a match that finished hours ago. Singles is
    # unaffected either way: everything it shows comes through match_id.
    # Only fills gaps — whatever the survivor already knows about itself wins.
    # Bracket linkage moves with the slot: a withdrawal's replacement row has
    # match_id NULL (its new player is not in draw_entries yet), while the row
    # it retires holds the link — and the bracket match is positional, so it
    # will BE the replacement's match once the draw scrape catches up. Without
    # the hand-over the surviving row has no live or completed scores until
    # then, which is the whole feature.
    for field in ("sofa_event_id", "live_scores_json", "scores_json",
                  "live_point_json", "winner_side", "started_at", "completed_at",
                  "match_id", "draw_id", "round_label"):
        if getattr(keep, field, None) is None and getattr(drop, field, None) is not None:
            setattr(keep, field, getattr(drop, field))
    await db.execute(
        update(ScheduleChange)
        .where(ScheduleChange.schedule_entry_id == drop.id)
        .values(schedule_entry_id=keep.id))
    await db.delete(drop)       # players cascade off the relationship


async def _dedupe_day(db, tournament_id: int, play_date: date) -> int:
    """Collapse rows that are the same slot recorded twice.

    Two revisions of a sheet can describe one match in ways that hash to
    different pairing keys, and then it appears twice on the page:

    * a slot printed "Tien OR Tiafoe" on one revision and "[17] Frances TIAFOE
      USA" on the next — the identity moved when the alternatives resolved;
    * doubles, where the same thing happens with no bracket match to fall back
      on, because doubles draws are not in `matches` at all.

    Run as a pass over the day rather than inline at write time, so it also
    repairs rows already stored under a key no future revision will produce.
    The most recently confirmed row wins, except that a settled row always
    beats an unresolved one — its names are the real ones.
    """
    rows = (await db.execute(
        select(ScheduleEntry).where(
            ScheduleEntry.tournament_id == tournament_id,
            ScheduleEntry.play_date == play_date,
        ))).scalars().all()
    if len(rows) < 2:
        return 0

    rows.sort(key=lambda r: (r.last_document_id or 0, r.id), reverse=True)

    # Context for _superseded. Both pieces exist to tell a withdrawn player
    # (gone from the sheet, match never played) from a finished one (gone from
    # the sheet because the match is over): every name the latest revision
    # still prints, and whether each linked bracket match has a result.
    latest_doc = rows[0].last_document_id or 0
    latest_pool = [toks for r in rows
                   if (r.last_document_id or 0) == latest_doc
                   for s in ('a', 'b') for toks in _side_tokens(r, s)]
    linked = [r.match_id for r in rows if r.match_id]
    match_played: dict[int, bool] = {}
    if linked:
        for mid, winner, done in (await db.execute(
                select(Match.id, Match.winner_id, Match.completed_at)
                .where(Match.id.in_(linked)))).all():
            match_played[mid] = bool(winner or done)

    kept: list = []
    dropped = 0
    for row in rows:
        twin = None
        replaced = False
        # Any trace of having been on court disqualifies a row from being a
        # withdrawal ghost — a played match is history, however stale its
        # document. This guard is what keeps _superseded off rain-backlog
        # days, where a player legitimately appears on two rows at once.
        row_played = bool(row.started_at or row.completed_at or row.winner_side
                          or row.live_scores_json
                          or match_played.get(row.match_id))
        for k in kept:
            # Disciplines must agree — EXCEPT where one side is still
            # unresolved, which is exactly the case that used to be
            # misclassified. Rows stored before that fix still carry the wrong
            # value, and refusing to look at them would strand them forever.
            if k.discipline != row.discipline and not (k.is_tbd or row.is_tbd):
                continue
            # Same bracket match on the same day is the same slot; only ever
            # non-null for singles that resolved.
            if k.match_id and row.match_id and k.match_id == row.match_id:
                twin = k
                break
            if _resolves(row, k) or _resolves(k, row) or _same_pairing(row, k):
                twin = k
                break
            # `row` is the older of the two by construction — rows are sorted
            # newest-first and `k` was kept on an earlier pass — so the
            # direction is fixed: only the older row can be the ghost.
            if not row_played and _superseded(row, k, latest_pool):
                twin = k
                replaced = True
                break
        if twin is None:
            kept.append(row)
            continue
        # Prefer whichever of the two is settled, regardless of which sheet
        # confirmed it last — and, between two settled rows, whichever NAMES
        # MORE PLAYERS. The fuller row is the one parsed by the better parser;
        # letting document order decide would let a row that lost a player to
        # an old bug outlive the row that has them all, and the next sweep
        # would simply re-create the pair.
        # Captured before _absorb deletes the loser's players.
        gone, stays = _printed_pairing(row), _printed_pairing(twin)
        twin_n = len(twin.players or [])
        row_n = len(row.players or [])
        if (twin.is_tbd and not row.is_tbd) or (
                twin.is_tbd == row.is_tbd and row_n > twin_n):
            kept[kept.index(twin)] = row
            await _absorb(db, keep=row, drop=twin)
        else:
            await _absorb(db, keep=twin, drop=row)
        dropped += 1
        if replaced:
            # Info, not warning: a lucky loser stepping in is ordinary tennis
            # and self-heals here — but the retired pairing should be on the
            # record when someone asks where a match went.
            from app.services.system_log import app_log
            await app_log(
                "info", "order_of_play",
                f"Withdrawal supersede on {play_date}: retired '{gone}' "
                f"for '{stays}'",
                {"tournament_id": tournament_id, "play_date": str(play_date),
                 "kept_entry_id": twin.id, "court": twin.court})

    if dropped:
        await db.flush()
    return dropped


def _ascii_fold(s: str) -> str:
    """Lowercase, combining marks dropped. The character half of `_fold`,
    split out so a caller that has already stripped the seeding and country
    (via `_clean_name`) can fold without stripping a second time."""
    import unicodedata
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _fold(name: str) -> frozenset:
    """Name tokens under a plain ASCII fold, for matching a sheet's spelling
    to a draw's.

    NOT rankings._norm, deliberately: that maps o-umlaut to "oe" (the German
    transliteration), while the sheets print plain ASCII — so "Roettgering"
    vs "ROTTGERING" never matched, the draw_entry_id was never stamped, and
    every downstream consumer that keyed on the id silently skipped the row.
    NFD + drop-combining folds both spellings to "rottgering". Bracketed
    prefixes ([Q], [7], [Alt]) and a trailing IOC code are stripped first.
    """
    import re as _re
    s = _re.sub(r"^(?:\[[^\]]*\]\s*)+", "", (name or "").strip())
    s = _re.sub(r"\s+[A-Z]{3}$", "", s)
    return frozenset(t for t in _ascii_fold(s).split() if t)


async def resolve_settled_alternatives(db, tournament_id: int) -> int:
    """Collapse every "A or B" slot whose deciding match is already over.

    The moment a feeder match has a winner, a schedule row still offering the
    choice is WRONG — it asserts an open question the draw has closed. Until
    now the collapse only happened when a LATER sheet revision was ingested
    and dedupe merged the rows; between the match ending and the next
    revision (hours, sometimes a day) the site showed "CHOINSKI or
    ROTTGERING" beside a bracket that already knew. This runs from every path
    that writes winners — the ESPN and Sofascore sweeps, the ingest itself
    for a PDF released after the result, and the 2-minute estimate tick as
    the backstop — so the answer is minutes at worst, not revisions.

    Strict on identity: a side collapses only when every alternative maps to
    exactly one draw entry, those entries form exactly one real match, and
    that match's winner is one of them. Anything ambiguous is left alone —
    a wrong collapse would assert the WRONG player, which is far worse than
    a stale "or".
    """
    from datetime import timedelta as _td

    today = date.today()
    entries = (await db.execute(
        select(ScheduleEntry).where(
            ScheduleEntry.tournament_id == tournament_id,
            ScheduleEntry.is_tbd.is_(True),
            ScheduleEntry.play_date >= today - _td(days=1),
        ))).scalars().all()
    if not entries:
        return 0

    draw_ids = (await db.execute(
        select(Draw.id).where(Draw.tournament_id == tournament_id))).scalars().all()
    if not draw_ids:
        return 0
    dents = (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id.in_(draw_ids)))).scalars().all()
    by_fold: dict[frozenset, list] = {}
    for de in dents:
        by_fold.setdefault(_fold(de.name), []).append(de)
    matches = (await db.execute(
        select(Match).where(Match.draw_id.in_(draw_ids),
                            Match.winner_id.isnot(None)))).scalars().all()
    by_pair = {frozenset((m.player1_id, m.player2_id)): m
               for m in matches
               if m.player1_id is not None and m.player2_id is not None}

    collapsed = 0
    for entry in entries:
        sides_left = ""
        for side_key in (entry.tbd_side or "ab"):
            rows = [p for p in (entry.players or []) if p.side == side_key]
            if len(rows) < 2:
                continue
            ids = []
            for r in rows:
                if r.draw_entry_id:
                    ids.append(r.draw_entry_id)
                    continue
                cand = by_fold.get(_fold(r.raw_name)) or []
                if len(cand) == 1:
                    ids.append(cand[0].id)
                else:
                    ids = None
                    break
            feeder = by_pair.get(frozenset(ids)) if ids and len(set(ids)) == len(rows) else None
            if feeder is None or feeder.winner_id not in (ids or []):
                sides_left += side_key
                continue
            # The winner stays; the alternative that lost goes.
            for r, rid in zip(rows, ids):
                if rid == feeder.winner_id:
                    r.draw_entry_id = rid
                    r.position = 1
                else:
                    await db.delete(r)
            collapsed += 1
        new_side = sides_left or None
        if new_side != entry.tbd_side or (not sides_left and entry.is_tbd):
            entry.tbd_side = new_side
            entry.is_tbd = bool(sides_left)
    if collapsed:
        await db.commit()
        logger.info("Collapsed %d settled alternative side(s) for tournament %s",
                    collapsed, tournament_id)
    return collapsed


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


async def _observed_changeover(db, tournament_id: int) -> tuple[int, int]:
    """(minutes, sample count) — the real changeover at this tournament.

    Measured from what actually happened: for consecutive slots on the same
    court, the gap between the earlier match finishing and the later one
    starting. Only pairs where BOTH timestamps exist can be used, which means
    main-draw singles that ESPN reported, so the sample builds slowly.

    The median rather than the mean: one suspended match, or a slot the crowd
    was cleared for, would otherwise drag the figure for the whole day.

    Both sides of the pair are returned by tour as well, because a cross-tour
    changeover plausibly runs longer — banners and signage change over. The
    first measurement showed no difference (21.3 cross against 21.2 same), but
    on a single cross-tour observation that is not evidence either way, so the
    two are still treated alike. The query keeps the dimension so the question
    can be settled once the data exists.
    """
    rows = (await db.execute(
        select(ScheduleEntry.court, ScheduleEntry.court_order, ScheduleEntry.play_date,
               Match.started_at, Match.completed_at)
        .join(Match, Match.id == ScheduleEntry.match_id)
        .where(ScheduleEntry.tournament_id == tournament_id)
        .order_by(ScheduleEntry.play_date, ScheduleEntry.court,
                  ScheduleEntry.court_order))).all()

    by_court: dict[tuple, list] = {}
    for court, order, day, started, completed in rows:
        by_court.setdefault((day, court), []).append((order, started, completed))

    gaps = []
    for slots in by_court.values():
        slots.sort(key=lambda x: x[0])
        for (o1, _s1, c1), (o2, s2, _c2) in zip(slots, slots[1:]):
            if o2 != o1 + 1 or not c1 or not s2:
                continue
            mins = (_aware(s2) - _aware(c1)).total_seconds() / 60
            # A negative gap means overlapping courts or a clock problem; a huge
            # one means rain, a curfew or a suspension. Neither is a changeover.
            if 0 <= mins <= 90:
                gaps.append(mins)

    if len(gaps) < _MIN_CHANGEOVER_SAMPLES:
        return _DEFAULT_CHANGEOVER_MIN, len(gaps)
    gaps.sort()
    mid = len(gaps) // 2
    median = gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2
    return int(round(median)), len(gaps)


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

    # Before the rows are read, for the same reason _renumber_courts runs here
    # rather than only at ingest: ingest returns early when the PDF has not
    # changed, so a duplicate left by an earlier revision would otherwise sit
    # on the page until the sheet happened to change again.
    await _dedupe_day(db, tournament_id, play_date)

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

    # Before anything is chained: positions must be distinct or "which came
    # first" has no answer. Done here rather than only at ingest, because ingest
    # returns early when the PDF has not changed — so a collision introduced by
    # an earlier revision would never be cleaned up.
    await _renumber_courts(db, tournament_id, play_date)

    changeover, samples = await _observed_changeover(db, tournament_id)
    gap = timedelta(minutes=changeover)

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

            # Doubles has no draw match — that is the whole reason it is not in
            # the brackets — so `m` is None for every doubles slot, and both
            # tests below used to come back False no matter what had happened on
            # court. A finished doubles match was therefore indistinguishable
            # from one that had not started, the court never freed, and the
            # chain carried guessed durations forward from the printed start all
            # day: a semi-final whose court had stood empty for an hour was
            # still being announced for the middle of the afternoon.
            # The row carries its own state for exactly this case. Asked only
            # when there is no match to ask, so singles is untouched.
            if m is not None:
                finished_at = _aware(getattr(m, 'completed_at', None))
                is_live = bool(getattr(m, 'live_scores_json', None)
                               and not getattr(m, 'winner_id', None))
            else:
                finished_at = _aware(s.completed_at) if s.status == 'completed' else None
                is_live = s.status == 'live'
                # Completed before this column existed, or by some path that does
                # not stamp it. It is over either way, which is all the chain
                # needs — see below.
                if s.status == 'completed' and finished_at is None:
                    finished_at = now

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
                # The court is not free the instant a match ends.
                # A doubles row keeps its live score on itself, so read the
                # remaining time from whichever of the two is actually carrying
                # the match.
                live_json = (getattr(m, 'live_scores_json', None) if m is not None
                             else s.live_scores_json)
                prev_end = (finished_at if finished_at else now + timedelta(
                    minutes=_remaining_minutes(live_json, s.discipline))) + gap
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
                prev_end = expected + timedelta(minutes=dur) + gap

    await db.commit()
    return touched
