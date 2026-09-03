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

import asyncio
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
from app.services.live_state import is_suspended
from app.services.oop_parser import COUNTRY_CODES, parse_pdf
from app.services.rankings import _norm

logger = logging.getLogger(__name__)

# A DAY'S SHEET IS WRITTEN IN TWO TRANSACTIONS — the ingest, then the estimates
# — because one that held SQLite's lock across both once wedged the site. For a
# few seconds between them a row can carry a NEW printed time beside an OLD
# expected_start_at, and the invariant sweep, a separate job, read exactly that
# window twice on 2 Sep 2026 ("expected_contradicts_printed" — printed 5:00 PM,
# expected 4:30) and paged the user for an estimate nobody ever served. Every
# writer of the pair holds this while it writes; the sweep holds it while it
# reads. In-process only, which is all there is: one worker.
day_write_lock = asyncio.Lock()

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


def _played(scores) -> bool:
    """Did this result take court time?

    A WALKOVER DID NOT. Nobody hit a ball: the slot is announced, the winner
    advances, and the court is free at the moment the previous match ends. The
    chain treated one as an ordinary completed match and pushed everything
    after it back by its supposed finish — Stadium 17's next match read
    "Fol. by ~11:35 AM" off a walkover that never occupied the court.
    A retirement is the opposite case and IS play: it used the court until the
    moment it stopped.
    """
    for side in (scores or []):
        for cell in (side or []):
            if re.fullmatch(r"w/?o", str(cell or "").strip(), re.I):
                return False
    return True


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
    # The PARSE's own word is next. Both parsers state a discipline in
    # canonical form when their source does — the PDF's slot line ("Doubles /
    # Not Before 7:00 PM"), the US Open feed's event code mapped by uso_feed —
    # and the text fallbacks below exist for sheets that say NOTHING. Running
    # a stated 'mixed' through those fallbacks filed Williams/Alcaraz as
    # main-draw singles: the blob regex knows event codes, not words.
    if match.discipline in ('doubles', 'mixed'):
        stage = 'qualifying' if _QUALI_ROUND_RE.match(
            (match.round or '').strip()) else 'main'
        return stage, match.discipline
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


# A token is an INITIAL — and so worth nothing to match on — when it carries a
# single letter: "d.", "a", "m-". Everything longer is part of a name,
# INCLUDING a two-letter surname.
#
# The test used to be the token's LENGTH (`len(t) > 2`), which silently threw
# away every short surname the tours actually print — LI, TU, XU, BU, HO, JI,
# MA, WU, NG. `sofascore_doubles._sheet_surnames` had already been taught this
# ("Li TU AUS is a real entry and TU is a real surname"); this was the copy of
# two that was never fixed. `schedule_invariants._INITIAL_RE` states the rule a
# third time on purpose — the law must not be blinded by a change made here.
_NON_ALPHA_RE = re.compile(r'[^a-z]')


def _is_initial(token: str) -> bool:
    """One letter standing in for a name, however it happens to be punctuated."""
    return len(_NON_ALPHA_RE.sub('', token)) < 2


def _names_a_team(name: str) -> bool:
    """A WHOLE TEAM in one printed string — "S. Aoyama / E. Liang".

    An unresolved doubles side offers a choice between two PAIRS, and each pair
    reaches us as a single printed name. Two people can never be one
    `draw_entries` row, so any id stamped on one of these necessarily describes
    a single partner while the page speaks for both.
    """
    return '/' in (name or '')


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

    A two-letter SURNAME is a name, not noise. Monterrey 2026-08-29 printed
    the women's final as "D. Parry OR A. Li" and the old length filter reduced
    "A. Li" to the EMPTY set — a probe that matches nobody. [5] Ann Li sat on
    the page with no flag, no ranking and no link to her own draw entry, and
    the row could never have absorbed the settled sheet that follows it, since
    `_resolves` needs her tokens on both sides of the comparison. See
    `_is_initial`.
    """
    cleaned = _clean_name(raw or '')
    # A team names two people and no single draw entry can be it, so there is
    # nothing here to probe with. Monterrey 2026-08-29 stamped
    # "M. Joint / Y. Xu" with Maya Joint's SINGLES entry — the pair then flew
    # her nationality, her ranking and her flag, while the alternative beside
    # it ("S. Aoyama / E. Liang") carried none, purely because only one of that
    # team's two surnames had survived the length filter. Nothing errors; the
    # row simply speaks for a person who is half of it.
    if _names_a_team(cleaned):
        return set(), set()
    # `_clean_name`, NOT `_fold`, owns the stripping — it gates the trailing
    # code on _COUNTRY_CODES, and _fold takes any three capitals. Folding a
    # cleaned name stripped twice and turned "[WC] Luca POW GBR" into "Luca",
    # which is a subset of "Luca Van Assche": a confidently wrong player.
    # Three capitals are a surname as often as a country — LUZ, GUO, POW.
    return ({t for t in _norm(cleaned).split() if not _is_initial(t)},
            {t for t in _ascii_fold(cleaned).split() if not _is_initial(t)})


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


async def _sync_players(db, entry, na: list, nb: list, ids: list,
                        nats: Optional[list] = None) -> list:
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
            i = base + pos - 1
            eid = ids[i] if i < len(ids) else None
            nat = nats[i] if nats and i < len(nats) else None
            row = by_slot.pop((side, pos), None)
            if row is None:
                db.add(ScheduleEntryPlayer(
                    schedule_entry_id=entry.id, side=side, position=pos,
                    raw_name=nm, draw_entry_id=eid, nationality=nat))
                continue
            if row.raw_name != nm:
                changed.append((row.raw_name, nm))
                row.raw_name = nm
            # Like draw_entry_id below: a code the source states wins, a
            # None never erases one already known.
            if nat is not None:
                row.nationality = nat
            # Never trade an id already proved for a None this pass could not
            # resolve: a qualifier reaches draw_entries days after the sheet
            # first names them.
            #
            # A TEAM is the one name for which None is not "could not resolve"
            # but "cannot be resolved, ever" — two people are not one entry —
            # so it has to be able to erase. Without this exception the wrong
            # id survives its own fix: Monterrey 2026-08-29 stamped
            # "M. Joint / Y. Xu" with Maya Joint's singles entry, and
            # re-ingesting the corrected parse would have left the pair still
            # wearing her flag and her ranking, because the corrected pass
            # resolves to None and None used to be ignored here.
            if eid is not None:
                row.draw_entry_id = eid
            elif _names_a_team(nm):
                row.draw_entry_id = None
    # A side that SHRANK — the phantom "DAMM / SHELBAYH" settling to one name.
    for row in by_slot.values():
        await db.delete(row)
    return changed


# Order-of-play sheets print the SURNAME in capitals, every tour, every tier.
# A stored name with no capitalised run therefore is not a sheet rendering.
# `schedule_invariants` keeps its own copy of this deliberately — the law must
# not be able to be blinded by a change made here to the code it polices.
_SHEET_CAPS_RE = re.compile(r'(?<![A-Za-z])[A-Z]{2,}(?![a-z])')


def _is_sheet_form(name: str) -> bool:
    return bool(name and _SHEET_CAPS_RE.search(name))


def _sheet_form(person, seeded: bool = True) -> Optional[str]:
    """Render a draw entry the way a sheet prints a SETTLED row.

    `(name, nationality, seed, entry_type)`, in the format every other row on
    the page carries: "[8] Cristina BUCSA ESP". Only the last token of the
    draw's name is capitalised — the surname is the last word, the same
    reading `splitPlayerName` uses on the frontend. A two-word surname
    ("BAUTISTA AGUT") loses its first word to the given names, which shortens
    the name and never misidentifies it; capitalising everything after the
    first token instead would turn "Juan Manuel Cerundolo" into the surname
    "MANUEL CERUNDOLO".

    `seeded=False` for anything but main-draw singles: a doubles player's
    draw_entry_id points at their SINGLES row, so its seed belongs to a
    different event (Siniakova is [1] in the doubles and [33] in the singles).
    The name and the nationality are properties of the person and stay.
    """
    if person is None:
        return None
    name, nationality, seed, entry_type = person
    words = (name or '').split()
    if not words:
        return None
    words[-1] = words[-1].upper()
    marker = None
    if seeded:
        marker = f"[{seed}]" if seed else (f"[{entry_type}]" if entry_type else None)
    return ' '.join([p for p in (marker, ' '.join(words), nationality) if p])


def _printed_name(printed: dict, people: dict, eid, fallback: str) -> str:
    """The sheet's own spelling of the player the bracket says came through.

    A settled slot must read like every other row on the page: SURNAME in
    capitals, nationality, seeding marker. The draw's name is a different
    rendering of the same person and carries none of those. Only when the
    printed alternatives cannot be pinned to this player does the draw name
    stand in.

    **A printed alternative is not automatically a settled rendering.** This
    took the printed spelling whenever it identified one player, on the
    assumption that "the alternatives are printed right here in the same form
    as every settled row" — true of the ATP sheets it was written against,
    false of the WTA's, which abbreviate: Monterrey 2026-08-25 printed the
    7:30 PM Estadio slot as "D. Parry or D. Vekic", so resolving it stored
    "D. Parry" and the live page showed an initial beside eight rows reading
    "Firstname SURNAME NAT". It healed only because the WTA reissued the sheet
    15 minutes later with the settled pair; on the last revision of a day,
    which is the ordinary case once play starts, it would have stood all
    evening. `name_not_sheet_form` in schedule_invariants.py alerted (06:00:35,
    entry 162) and could not heal. So the printed form has to EARN its place:
    keep it when it reads like a sheet row, otherwise build one from the draw.

    Seeded by default because the only caller is a singles slot the BRACKET
    matched, which is main draw by construction — the seed there is this
    event's.
    """
    hits = printed.get(eid) or []
    if len(hits) == 1 and _is_sheet_form(hits[0]):
        return hits[0]
    person = people.get(eid)
    return _sheet_form(person) or (person[0] if person else None) or fallback


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


async def _log_parse_violations(tournament, play_date, violations: list) -> None:
    """A slot the parse threw away, in the admin log where a person will see it.

    ERROR, not warning: this is a match the sheet prints and the site does not
    show, which is the same severity as the whole ingest dying — and it is far
    quieter, because nothing raises. Winston-Salem 2026-08-26 published 11 of
    12 matches for a day and only the PDF-vs-page verifier noticed.
    """
    if not violations:
        return
    from app.services.system_log import app_log
    await app_log(
        "error", "order_of_play",
        f"{len(violations)} order-of-play slot(s) printed on the "
        f"{tournament.name} sheet for {play_date} were dropped by the parser: "
        + "; ".join(x["detail"][:90] for x in violations[:4]),
        {"tournament_id": tournament.id, "play_date": str(play_date),
         "violations": violations[:20]},
        dedup_key=f"sched_parse_dropped_{tournament.id}_{play_date}",
        dedup_hours=6)


async def ingest_document(db, tournament, play_date: date, url: str,
                          pdf_bytes: bytes, tour: Optional[str] = None,
                          parser=None, queue_verify: bool = True) -> dict:
    """Parse one document revision and reconcile it into schedule_entries.

    `parser` defaults to the PDF parser; the US Open's JSON feed passes its
    own (uso_feed.parse_uso_day) with the same (matches, meta) contract, and
    hands NORMALIZED bytes here so the sha256 revision check keeps meaning
    "the schedule changed" rather than "a live score moved". Those JSON docs
    also pass queue_verify=False — the verifier's whole toolchain (pdfplumber,
    the PDF-vs-page prompt) assumes a PDF, and a queued JSON would only make
    every run fail its parse step.
    """
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    existing = (await db.execute(
        select(ScheduleDocument).where(
            ScheduleDocument.tournament_id == tournament.id,
            ScheduleDocument.play_date == play_date,
            ScheduleDocument.sha256 == digest,
        ))).scalars().first()
    if existing:
        return {'skipped': 'unchanged', 'document_id': existing.id}

    # OFF THE EVENT LOOP, same incident as scraper.parse_draw: pdfplumber is
    # seconds of sync CPU per sheet, and a burst of revisions parsed inline
    # froze every request in flight.
    matches, meta = await asyncio.to_thread(parser or parse_pdf, pdf_bytes)
    # The law, applied to the parse itself. Computed here and LOGGED AFTER THE
    # COMMIT, both below: a slot the parse threw away leaves no row for
    # check_day to judge, and `app_log` opens its own session — awaiting it
    # while this one holds uncommitted writes deadlocks the ingest against
    # itself on SQLite's single writer.
    from app.services.schedule_invariants import check_parse
    parse_violations = check_parse(meta, len(matches), [m.round for m in matches])

    # A REPUBLISH IS NOT A REVISION. The tours' systems regenerate the sheet
    # continuously — the only diff between two of Winston-Salem's overnight
    # "revisions" was the footer clock ("8:17:57 PM Keith Crossland" →
    # "8:34:03 PM"). Byte identity (above) still short-circuits an unchanged
    # file; content identity here stops a changed file whose SLOTS are
    # unchanged from minting a document, a rev.N email that says "No slot
    # changes", and a verifier run. Everything a reader would call a change —
    # court, order, wording, round, tour, sides — is in the fingerprint;
    # printed scores and statuses are deliberately not.
    content_fp = hashlib.sha256(repr([
        (m.court, m.time, m.start_raw, m.tour, m.round, m.discipline,
         m.tbd, m.tbd_side, tuple(m.side_a), tuple(m.side_b))
        for m in matches
    ]).encode()).hexdigest()
    prev = (await db.execute(
        select(ScheduleDocument).where(
            ScheduleDocument.tournament_id == tournament.id,
            ScheduleDocument.play_date == play_date,
        ).order_by(ScheduleDocument.id.desc()))).scalars().first()
    if (matches and prev is not None and prev.content_sha == content_fp
            and not str(prev.sha256 or '').startswith('forced')):
        return {'skipped': 'republished', 'document_id': prev.id}

    doc = ScheduleDocument(
        tournament_id=tournament.id, play_date=play_date, source_url=url,
        tour=tour, sha256=digest, revision_label=meta.get('date_line'),
        parse_status=meta.get('kind') or 'ok', match_count=len(matches),
        content_sha=content_fp,
    )
    db.add(doc)
    await db.flush()

    if not matches:
        # An OOP revision that parsed to NOTHING is exactly the revision most
        # worth independent eyes — a parser regression looks like this.
        await db.commit()
        await _log_parse_violations(tournament, play_date, parse_violations)
        if queue_verify:
            _queue_verification(doc, tournament, play_date, url, pdf_bytes, 0)
        return {'document_id': doc.id, 'kind': meta.get('kind'), 'entries': 0}

    # Roster for resolution: every draw of this tournament.
    draw_rows = (await db.execute(
        select(Draw).where(Draw.tournament_id == tournament.id))).scalars().all()
    draws = []
    for d in draw_rows:
        ents = (await db.execute(
            select(DrawEntry.id, DrawEntry.name, DrawEntry.nationality,
                   DrawEntry.seed, DrawEntry.entry_type)
            .where(DrawEntry.draw_id == d.id))).all()
        # Each entry carries BOTH folds — see _match_tokens. Built once here
        # rather than per name, because every slot on the sheet probes it.
        draws.append({'draw': d,
                      'entries': [(e[0], set(_norm(e[1] or '').split()),
                                   set(_ascii_fold(e[1] or '').split()))
                                  for e in ents],
                      # Everything a sheet prints about a player, for a slot
                      # the bracket settles — see _sheet_form.
                      'people': {e[0]: (e[1], e[2], e[3], e[4]) for e in ents}})

    # entry id -> draw id, so a resolved player also tells us which draw the
    # slot belongs to.
    entry_draw = {}
    draw_by_id = {}
    entry_people = {}
    for d in draws:
        draw_by_id[d['draw'].id] = d['draw']
        entry_people.update(d['people'])
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
            printed_start = getattr(m, 'start_raw', None)
            # THE SHEET SAYING NOTHING IS NOT THE SHEET SAYING "NO TIME".
            # A box whose match is over loses its time band on the next
            # revision while keeping its place on the court — Monterrey's
            # 2026-08-26 walkover sat at the top of ESTADIO with the band
            # removed and a bare "WO" in it. Re-stamping that silence would
            # replace the 3:00 PM an earlier revision printed with "TBA" on a
            # row the reader can still see, losing the only record of when the
            # slot was called for. A slot that says "TBC" is the opposite case
            # — it HAS wording, so it comes through here and clears the clock
            # like any other change.
            keep_start = bool(entry is not None and not printed_start
                              and entry.start_note)
            if keep_start:
                start_type, printed_time = entry.start_type, entry.start_time_local
            else:
                printed_time = m.time
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
                                   ('start_time_local', printed_time),
                                   ('start_type', start_type)):
                    old = getattr(entry, field)
                    if str(old) != str(new) and old is not None:
                        db.add(ScheduleChange(
                            schedule_entry_id=entry.id, document_id=doc.id,
                            field=field, old_value=str(old), new_value=str(new)))

            # ONE path for players, new row or old — see _sync_players for why
            # the create-only version froze a stale rendering into four rows.
            renamed += await _sync_players(
                db, entry, na, nb, ids,
                nats=(getattr(m, 'nations_a', None) or []) + (getattr(m, 'nations_b', None) or []) or None)

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
                    # Keep the SHEET's spelling of whoever came through — but
                    # only when the alternative was printed in the same form as
                    # a settled row. The WTA abbreviates them ("D. Parry or
                    # D. Vekic") and that is not a rendering this page can
                    # show; see _printed_name.
                    printed: dict = {}
                    for nm, eid in zip(na + nb, ids):
                        if eid is not None:
                            printed.setdefault(eid, []).append(nm)
                    na = [_printed_name(printed, entry_people, found.player1_id, na[0])]
                    nb = [_printed_name(printed, entry_people, found.player2_id, nb[0])]
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
            elif discipline != 'singles':
                # A doubles row can never belong to a draw, because we store no
                # doubles draw: `draws` holds singles only. Its players still
                # resolve to draw_entries — their SINGLES rows — so the fallback
                # below happily filed a men's doubles match under the men's
                # singles draw (Winston-Salem 2026-08-26, FRANTZEN/HAASE vs
                # HALYS/HERBERT, draw 121; 31 rows across four tournaments).
                # `surface` and `gender` are served straight off draw_id, so the
                # row asserted a draw, a surface and a gender belonging to a
                # different event. Same leak the seed had, one field over — see
                # _player_out's `discipline == "singles" and stage == "main"`.
                #
                # Cleared, not merely skipped: draw_id is written nowhere else,
                # so a row stamped before this gate existed would carry the
                # wrong draw for the life of the tournament.
                entry.draw_id = None
            elif side_a_ids or side_b_ids:
                # Singles that matched no bracket row — qualifying, which has
                # draw entries but no rows in `matches`.
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
            entry.start_time_local = printed_time
            # Not written back when the sheet printed no wording at all — see
            # keep_start above. `start_note` is the flag that says so, so it
            # has to be the one field the silent pass leaves alone.
            if not keep_start:
                entry.start_note = printed_start
            # A row created THIS pass always takes the sheet's word for it.
            # The guard below protects an EXISTING row that already settled
            # from being re-marked unresolved by a stale revision — but on a
            # fresh row it meant a slot that resolved to a bracket match kept
            # the default False, and an "A or B" side rendered as a team.
            if entry.id is None or found is None or not m.tbd:
                # TWO NAMES ON A SINGLES SIDE MEAN THAT SIDE IS UNRESOLVED.
                # The sheet writes a pending semi-final winner as "Parry / Li",
                # and the parser only reads a slash as "or" on a side it has
                # ALREADY marked unresolved — so a final with both semis still
                # to play stored one side as a phantom doubles pairing (and
                # tripped singles_side_stacked; Monterrey, 2026-08-29). The law
                # says two names are legal only on a declared-unresolved side,
                # so declare it here rather than only complain about it later.
                tbd_side = getattr(m, 'tbd_side', None)
                if discipline == "singles":
                    stacked = "".join(
                        k for k, side in (("a", getattr(m, "side_a", None)),
                                          ("b", getattr(m, "side_b", None)))
                        if side and len(side) > 1)
                    if stacked:
                        tbd_side = "".join(sorted(set((tbd_side or "") + stacked)))
                entry.is_tbd = bool(m.tbd) or bool(tbd_side)
                entry.tbd_side = tbd_side or None
            entry.round_label = (m.round or entry.round_label
                                 or unanimous.get((stage, discipline)))
            entry.printed_score = getattr(m, 'printed_score', None)
            entry.last_seen_at = datetime.now(timezone.utc)
            entry.last_document_id = doc.id
            written += 1

    await db.flush()
    await _fill_tbd_rounds(db, tournament.id, play_date, entry_draw, draw_by_id)
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
        # And the mirror case: a slot whose bracket match did not exist when
        # the loop above looked for it. Run BEFORE the law, so a link the
        # bracket can now support is made rather than merely reported.
        await relink_bracket_matches(db, tournament.id)
        from app.services.schedule_invariants import check_and_log
        await check_and_log(db, tournament, play_date)
        await _log_parse_violations(tournament, play_date, parse_violations)
    except Exception:
        logging.getLogger(__name__).exception(
            "invariant check failed for %s %s", tournament.id, play_date)
    if queue_verify:
        _queue_verification(doc, tournament, play_date, url, pdf_bytes, written)
    return {'document_id': doc.id, 'entries': written, 'kind': meta.get('kind')}


async def describe_revision_changes(db, doc, prev_doc) -> list[str]:
    """What this revision changed, as short lines for the status email.

    Deterministic, from what the ingest already recorded: ScheduleChange rows
    stamped with this document (court, order, time, start wording) plus slots
    that appeared or disappeared between the two fetches. A player swap shows
    as its removed/added pair, which reads plainly ("- Kopriva vs Machac /
    + Herbert vs Machac") without any swap-detection cleverness. Capped by the
    CALLER — this returns everything and the email keeps the first few.
    """
    lines: list[str] = []

    def _who(entry) -> str:
        names = []
        for side in ("a", "b"):
            ps = sorted((p for p in (entry.players or []) if p.side == side),
                        key=lambda x: x.position or 0)
            surnames = []
            for pl in ps:
                last = _clean_name(pl.raw_name or "").split()
                surnames.append(next((w for w in reversed(last)
                                      if w == w.upper() and len(w) > 1), last[-1] if last else "?"))
            names.append("/".join(surnames) or "TBD")
        return f"{names[0]} vs {names[1]}"

    FIELD_WORDS = {"court": "court", "court_order": "order",
                   "start_time_local": "time", "start_type": "start"}

    rows = (await db.execute(
        select(ScheduleChange, ScheduleEntry)
        .join(ScheduleEntry, ScheduleEntry.id == ScheduleChange.schedule_entry_id)
        .where(ScheduleChange.document_id == doc.id))).all()
    by_entry: dict[int, list] = {}
    entries_by_id: dict[int, ScheduleEntry] = {}
    for ch, entry in rows:
        by_entry.setdefault(entry.id, []).append(ch)
        entries_by_id[entry.id] = entry
    for eid, chs in by_entry.items():
        entry = entries_by_id[eid]
        # court+order together is just "moved"; the reader cares where to.
        parts = []
        courts = [c for c in chs if c.field == "court"]
        if courts:
            parts.append(f"{courts[0].old_value} \u2192 {courts[0].new_value}")
        for c in chs:
            if c.field in ("start_time_local", "start_type") and not courts:
                parts.append(f"{FIELD_WORDS[c.field]} {c.old_value} \u2192 {c.new_value}")
            elif c.field == "start_time_local" and courts:
                parts.append(f"{c.old_value} \u2192 {c.new_value}")
        if not parts and all(c.field == "court_order" for c in chs):
            continue  # pure renumbering is a consequence, not news
        if parts:
            lines.append(f"{_who(entry)}: " + "; ".join(parts))

    if prev_doc is not None:
        prev_t = prev_doc.fetched_at
        this_t = doc.fetched_at
        day_rows = (await db.execute(
            select(ScheduleEntry).where(
                ScheduleEntry.tournament_id == doc.tournament_id,
                ScheduleEntry.play_date == doc.play_date))).scalars().all()
        for e in day_rows:
            if e.first_seen_at and prev_t and e.first_seen_at > prev_t:
                lines.append(f"+ {_who(e)}")
            elif (e.last_seen_at and this_t and prev_t
                  and prev_t <= e.last_seen_at < this_t):
                lines.append(f"\u2212 {_who(e)}")
    return lines


async def _fill_tbd_rounds(db, tournament_id: int, play_date: date,
                           entry_draw: dict, draw_by_id: dict) -> None:
    """The round of a slot the sheet leaves unresolved AND unlabelled.

    Winston-Salem's sheets print no round on any slot; settled rows get theirs
    from the bracket match they link to, but a "KOVACEVIC or TSITSIPAS" slot
    links to nothing yet and sat with no round chip at all. The candidates
    themselves say what it is: an alternative side's two players are exactly
    the two players of one pending bracket match in round k, so the slot is
    k+1 — and a settled side's player has already been propagated into their
    pending next-round row, which IS the slot, so their furthest match's round
    is the answer directly. Where both sides answer, they agree; take the max
    so a settled side's direct placement wins over a feeder's +1.
    """
    rows = (await db.execute(
        select(ScheduleEntry).where(
            ScheduleEntry.tournament_id == tournament_id,
            ScheduleEntry.play_date == play_date,
            # Either derivation missing re-qualifies the row: gating on the
            # label alone left a slot that got its round in one pass
            # invisible to the match-linking added later.
            or_(ScheduleEntry.round_label.is_(None),
                ScheduleEntry.match_id.is_(None)),
            ScheduleEntry.discipline == 'singles',
        ))).scalars().all()
    if not rows:
        return
    players = {}
    for pl in (await db.execute(
            select(ScheduleEntryPlayer).where(
                ScheduleEntryPlayer.schedule_entry_id.in_([e.id for e in rows])
            ))).scalars().all():
        players.setdefault(pl.schedule_entry_id, []).append(pl)
    for e in rows:
        side_rounds = []
        # The PARENT each side implies: bracket arithmetic makes the slot's
        # own match certain before its players are — the feeder at
        # (k, n) feeds exactly (k+1, ceil(n/2)), and a settled side's player
        # is already propagated into that very row. With the match known, the
        # draw can show the slot's time even though an opponent is not.
        parents = []
        for side in ('a', 'b'):
            ids = [pl.draw_entry_id for pl in players.get(e.id, [])
                   if pl.side == side and pl.draw_entry_id]
            if not ids:
                continue
            ms = (await db.execute(
                select(Match).where(
                    or_(Match.player1_id.in_(ids), Match.player2_id.in_(ids)),
                    Match.is_bye == False,
                ))).scalars().all()
            if not ms:
                continue
            top = max(m.round_number for m in ms)
            top_matches = [m for m in ms if m.round_number == top]
            feeder = next((m for m in top_matches
                           if len(ids) >= 2
                           and m.player1_id in ids and m.player2_id in ids), None)
            if feeder is not None:
                side_rounds.append(top + 1)
                parent = (await db.execute(
                    select(Match).where(
                        Match.draw_id == feeder.draw_id,
                        Match.round_number == top + 1,
                        Match.match_number == (feeder.match_number + 1) // 2,
                    ))).scalars().first()
                if parent is not None:
                    parents.append(parent)
            else:
                m_top = top_matches[0] if len(top_matches) == 1 else None
                if (m_top is not None and m_top.winner_id is not None
                        and m_top.winner_id not in ids):
                    # A LOST alternative — the sheet still names them because
                    # it printed before their feeder finished (Parry on the
                    # Monterrey QF slot after Vekic beat her). They were
                    # playing INTO the slot, so their match's parent is the
                    # slot, not the match they lost.
                    side_rounds.append(top + 1)
                    parent = (await db.execute(
                        select(Match).where(
                            Match.draw_id == m_top.draw_id,
                            Match.round_number == top + 1,
                            Match.match_number == (m_top.match_number + 1) // 2,
                        ))).scalars().first()
                    if parent is not None:
                        parents.append(parent)
                else:
                    side_rounds.append(top)
                    if m_top is not None:
                        parents.append(m_top)
        if not side_rounds:
            continue
        draw = draw_by_id.get(entry_draw.get(
            next((pl.draw_entry_id for pl in players.get(e.id, [])
                  if pl.draw_entry_id), None)))
        if e.round_label is None:
            label = _round_label(max(side_rounds),
                                 getattr(draw, 'num_rounds', None))
            if label:
                e.round_label = label
        # Link only on an unambiguous answer: every side that named a parent
        # named the same one. A disagreement means a mis-resolution somewhere,
        # and a wrong link is worse than a missing time.
        if e.match_id is None and parents and len({m.id for m in parents}) == 1:
            e.match_id = parents[0].id
            if e.draw_id is None:
                e.draw_id = parents[0].draw_id


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
    matching in `_resolve_players`: `_clean_name` takes the seeding and the
    country, initials carry no name, so "O. Luz" and "Orlando LUZ BRA" both
    reduce to {luz}.

    Same `_is_initial` test as `_match_tokens`, and it had the same bug — a
    two-letter surname was dropped by length and "A. Li" became the EMPTY set.
    That blinds the whole dedupe layer, not just the matcher: `_side_resolves`
    requires `toks and toks <= settled`, so an empty alternative can satisfy
    nothing, and Monterrey's women's final would have been published TWICE the
    moment the settled sheet arrived naming the winner.

    A team string keeps its tokens here, unlike in `_match_tokens` — the
    relations in `_dedupe_day` compare printed side against printed side, where
    "S. Aoyama / E. Liang" is exactly the text that has to agree.
    """
    return {t for t in _norm(_clean_name(raw or '')).split() if not _is_initial(t)}


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


def _same_pending(a, b) -> bool:
    """Two rows that are BOTH still unresolved and print the same slot.

    The hole this closes sat exactly between the other three relations.
    `_resolves` only fires when one row is MORE decided than the other (a
    strict subset of the alternatives), `_same_pairing` returns False the
    moment either row is `is_tbd`, and `_superseded` wants one side wholly
    replaced by new players. So two revisions that BOTH printed a slot
    unresolved — the ordinary case for a sheet reissued while the feeder match
    is still on court — were matched by nothing, and the later revision
    inserted a second row beside the first.

    Winston-Salem 2026-08-26: document 77 reprinted "DAMM vs KECMANOVIC or
    MAROZSAN", "CERUNDOLO vs GRENIER or BAEZ" and "MANNARINO or SONEGO vs
    DUCKWORTH" exactly as document 61 had — same players, same undecided side
    — and all three hashed to a NEW pairing_key anyway, because `_pairing_key`
    switches from names to draw-entry ids the moment every printed alternative
    resolves to the bracket. Identical printed rows, different identity. All
    three matches were published twice, and each phantom slot pushed every
    estimated start behind it on that court about two hours late.

    Requiring the undecided side to AGREE is what keeps this off two genuinely
    different pending slots: `_resolves` owns the case where one row decided
    something, and this owns only the case where neither did.
    """
    if not (a.is_tbd and b.is_tbd):
        return False
    A = {s: set().union(set(), *_side_tokens(a, s)) for s in ('a', 'b')}
    B = {s: set().union(set(), *_side_tokens(b, s)) for s in ('a', 'b')}
    if not all((A['a'], A['b'], B['a'], B['b'])):
        return False

    def agree(x, y):
        # Same subset-or-equal test as _same_pairing, for the same reason: a
        # corrected parser makes a row GAIN a player, so the row stored before
        # the fix is a strict subset of the one stored after it rather than
        # equal to it, and plain equality would leave both on the page.
        return x == y or x < y or y < x

    alt_a, alt_b = set(a.tbd_side or ''), set(b.tbd_side or '')
    # Sides swap between revisions often enough to be worth trying both ways,
    # and when they swap the undecided side travels with them — so each
    # orientation has to carry its own tbd_side comparison.
    if agree(A['a'], B['a']) and agree(A['b'], B['b']) and alt_a == alt_b:
        return True
    swapped = {'b' if s == 'a' else 'a' for s in alt_b}
    if agree(A['a'], B['b']) and agree(A['b'], B['a']) and alt_a == swapped:
        return True
    return False


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

    A WITHDRAWAL IS NOT THE ONLY WAY A SIDE GETS REPLACED. Re-reading the same
    sheet with a CORRECTED PARSER does it too, and then the old row's side is
    not a departed player but the old parse's mess. `_same_pairing` was taught
    that for settled rows ("KRAJICEK / MEKTIC vs CABRAL" gaining Tracy); this
    is the unresolved half, and nothing covered it — `_resolves` wants one row
    to be strictly MORE decided than the other, and two printings of the same
    pending slot are equally undecided. Winston-Salem 2026-08-26: the sheet's
    condensed rows re-parsed into clean names, and the day went to 14 rows for
    a 12-match sheet with the unreadable versions sitting beside their fixes.
    So TBD rows are compared too, but only against a row that left EXACTLY the
    same sides open — deciding one is `_resolves`' job, not this one's.
    """
    if old.is_tbd != new.is_tbd or (old.tbd_side or '') != (new.tbd_side or ''):
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
            #
            # `old_gone` may be EMPTY. A side whose names reduce to no usable
            # token names nobody — which is what a name broken up by a failed
            # text extraction looks like once _name_tokens has dropped its
            # one- and two-letter debris ("R i n k y H I JI K A TA" -> {}).
            # That is stronger evidence than a departed player, not weaker: a
            # side naming nobody cannot be a real pairing of its own. The
            # replacement side still has to name someone.
            if not new_come or (old_gone & new_come):
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
    # The survivor was restated by whichever revision restated EITHER row: the
    # two are one slot, so the newest sheet that printed it printed this. The
    # keep/drop choice above is made on how settled and how full a row is, not
    # on document order, so without this a merge can leave the survivor wearing
    # a document id older than every other row on the day — which is exactly
    # what `slot_unconfirmed` reads as a slot the parse lost.
    if (drop.last_document_id or 0) > (keep.last_document_id or 0):
        keep.last_document_id = drop.last_document_id
    drop_seen, keep_seen = _aware(drop.last_seen_at), _aware(keep.last_seen_at)
    if drop_seen and (not keep_seen or drop_seen > keep_seen):
        keep.last_seen_at = drop.last_seen_at
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
            if (_resolves(row, k) or _resolves(k, row)
                    or _same_pairing(row, k) or _same_pending(row, k)):
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
            # record when someone asks where a match went. Says "supersede",
            # not "withdrawal": the same relation now also retires a pairing a
            # corrected parser re-read, and a log line that named a cause it
            # cannot know would send the next reader looking for a player who
            # never withdrew.
            from app.services.system_log import app_log
            await app_log(
                "info", "order_of_play",
                f"Slot supersede on {play_date}: retired '{gone}' "
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


# "j." or "j.j." — single letters separated by dots. Deliberately requires the
# dots: a bare "jj" cannot be told from a short surname.
_INITIALS_RUN_RE = __import__("re").compile(r"(?:[a-z]\.)+")


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
    # A RUN OF INITIALS IS ITS LETTERS. The sheet writes "J.J. WOLF" and the
    # draw entry "J. J. Wolf", which split into "j.j." and "j." — one token
    # against two, so the two spellings never met and J.J. Wolf's schedule row
    # was left with no draw_entry_id and therefore no profile, ranking or form
    # anywhere it appeared.
    #
    # Expanded rather than dropped: discarding initials would fold "A. Zverev"
    # and "M. Zverev" onto the same name, and a wrong link is worse than none.
    out = set()
    for t in _ascii_fold(s).split():
        if t and _INITIALS_RUN_RE.fullmatch(t):
            out |= set(t.replace(".", ""))
        elif t:
            out.add(t)
    return frozenset(out)


class SettledPlayer:
    """A player on a side that has just been decided, detached from the ORM.

    The serve path resolves alternatives WITHOUT writing them back (the row
    keeps what the sheet printed, so the next revision still reconciles
    against the sheet). It therefore cannot re-point `raw_name` or `side` on
    the stored rows to say who came through — a read that assigns to an ORM
    row autoflushes and a GET takes the write lock. This carries the answer
    instead: same five attributes `_player_out` reads, none of them mapped.
    """

    __slots__ = ("side", "position", "raw_name", "nationality", "draw_entry_id")

    def __init__(self, side, position, raw_name, nationality, draw_entry_id):
        self.side = side
        self.position = position
        self.raw_name = raw_name
        self.nationality = nationality
        self.draw_entry_id = draw_entry_id


def settled_sides_index(rows) -> dict:
    """{every surname in a finished match} -> that match's WINNING side's rows.

    Built from schedule entries that carry a `winner_side`, of any discipline
    and any stage — a result is a result, and filtering this by kind is what
    made the resolver need fixing once per kind. Doubles has no bracket row,
    so for a doubles slot this is the only record of who came through.
    """
    idx: dict = {}
    for r in rows:
        sides: dict = {}
        for p in r.players:
            sides.setdefault(p.side, []).append(p)
        a = _sheet_surnames([p.raw_name for p in sides.get("a", [])])
        b = _sheet_surnames([p.raw_name for p in sides.get("b", [])])
        if not a or not b:
            continue
        win = sides.get("a" if r.winner_side == "a" else "b", [])
        if win:
            idx[frozenset(a | b)] = sorted(win, key=lambda p: p.position or 1)
    return idx


def _as_settled_side(kept, win_rows) -> list:
    """The winning alternative, rendered the way a SETTLED side is rendered.

    An alternative is stored as ONE row even when it names two people: on an
    unresolved side a "/" joins the partners of one candidate TEAM, and the
    parser deliberately keeps that team whole so the side can read "team or
    team". The moment the question is answered that row is no longer an
    alternative — it is the side — and a doubles side is two players, each
    with their own name, nationality and flag.

    Nothing taught this path that. Winston-Salem 2026-08-26, Court 3: once
    Schnaitter/Wallner beat Lammons/Withrow the page served Arribage/Guinard
    against a single player called "SCHNAITTER / WALLNER" — surnames only, no
    flags, one player row on a doubles side — while every other doubles row on
    the day showed two flagged players. Invisible to the law, because the
    STORED row is honestly unresolved and `doubles_side_not_two` exempts a
    declared-TBD side; the defect existed only in what was served. It is the
    twin of the fault `resolve_settled_alternatives` already carries a
    `_sheet_form` fix for: both places turn alternatives into a settled side,
    and only one of them had been taught what a settled side looks like.

    The deciding row's own players are the source, not a split of the
    abbreviated string, because they carry the full sheet form ("Jakob
    SCHNAITTER GER") and their `draw_entry_id`. Substituted only when that is
    an improvement and names the same people: every replacement must be one
    person, in the sheet's rendering, and the surnames must agree with the
    alternative being replaced. Anything else keeps what we had.
    """
    if not win_rows:
        return [kept]
    names = [(p.raw_name or "").strip() for p in win_rows]
    if not all(names) or any("/" in n for n in names):
        return [kept]
    if not all(_is_sheet_form(n) for n in names):
        return [kept]
    if _sheet_surnames(names) != _sheet_surnames([kept.raw_name]):
        return [kept]
    return [SettledPlayer(kept.side, i, p.raw_name, p.nationality, p.draw_entry_id)
            for i, p in enumerate(win_rows, 1)]


def settle_from_result_rows(side_players, index) -> tuple:
    """(players, resolved) — who came through, from the row that recorded it.

    Discipline-agnostic and stage-agnostic by construction: it knows only that
    two candidates met and that some row says who won. A doubles final, a
    qualifying second round, and anything not yet invented resolve through the
    same lookup.

    Shared with schedule_invariants so the law tests the shape this actually
    serves rather than a second copy of the rule that can drift from it.
    """
    if len(side_players) != 2:
        return side_players, False
    teams = [_sheet_surnames([p.raw_name]) for p in side_players]
    if not all(teams):
        return side_players, False
    win_rows = index.get(frozenset(teams[0] | teams[1]))
    if not win_rows:
        return side_players, False
    won = _sheet_surnames([p.raw_name for p in win_rows])
    keep = [p for p, t in zip(side_players, teams) if t & won]
    # Exactly one of the two, or we have not identified anything.
    if len(keep) != 1:
        return side_players, False
    return _as_settled_side(keep[0], win_rows), True


# _READ_THE_DAY_AS_STORED
#
# Everything in the tail of `ingest_document` re-reads rows that same session
# loaded MINUTES of work earlier, and `AsyncSessionLocal` is
# `expire_on_commit=False`: a plain `select()` hands back the identity-mapped
# object with its in-memory state intact, and `ScheduleEntry.players` is
# `lazy="selectin"`, so a collection already loaded is never loaded again.
# `_sync_players` adds and deletes player rows through `db.add`/`db.delete`
# rather than through that collection — so by the time these run, the parent's
# view of its own players is whatever the sheet said LAST time.
#
# Monterrey 2026-08-29: the sheet still printed "D. Parry OR A. Li" after the
# draw had recorded Parry's semi-final win. Every ingest re-added the losing
# alternative and re-marked the side unresolved (both correct — the row must
# say what the sheet says), and this resolver then looked at a side that still
# held ONE player in memory, concluded it was already settled, and skipped it.
# Nothing collapsed, nothing committed, and the women's final sat on the page
# offering a choice the bracket had closed. It looked like the resolver was
# broken; the resolver was fine — on a FRESH session it collapses the row in
# one call, which is exactly why the 2-minute backstop tick appeared to work
# and this call never did.
#
# `populate_existing=True` overwrites the loaded state instead of trusting it,
# and re-runs the selectin load for `players`. The `flush()` in front of it is
# what makes that safe for a caller mid-transaction: pending writes reach the
# database first, so the refresh reads them back rather than discarding them.
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
    # `populate_existing`, and it is the difference between this running and
    # this silently doing nothing. See _READ_THE_DAY_AS_STORED.
    await db.flush()
    entries = (await db.execute(
        select(ScheduleEntry).where(
            ScheduleEntry.tournament_id == tournament_id,
            ScheduleEntry.is_tbd.is_(True),
            ScheduleEntry.play_date >= today - _td(days=1),
        ).execution_options(populate_existing=True))).scalars().all()
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
    de_by_id = {de.id: de for de in dents}
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
                    # ...and is now a SETTLED side, so it has to read like
                    # one. The name still on it is the abbreviation the sheet
                    # offered while the question was open, and the WTA
                    # abbreviates: collapsing "D. Parry or D. Vekic" left
                    # "D. Parry" on Monterrey's 7:30 PM Estadio slot on
                    # 2026-08-25, an initial with no country beside eight rows
                    # reading "Firstname SURNAME NAT". This is the same fault
                    # as the one _printed_name carries on the ingest side —
                    # both places turn alternatives into a settled row, and
                    # only one of them had been taught what a settled row
                    # looks like. `name_not_sheet_form` flagged it (06:00:35,
                    # entry 162) and could not heal it; nothing else would
                    # have, because a later revision printing the settled pair
                    # is luck, not a mechanism.
                    de = de_by_id.get(rid)
                    if de is not None and not _is_sheet_form(r.raw_name or ''):
                        # The seed is main-draw singles only: a doubles row's
                        # draw_entry_id names their SINGLES entry, whose seed
                        # is a different event's. See _sheet_form.
                        form = _sheet_form(
                            (de.name, de.nationality, de.seed, de.entry_type),
                            seeded=(entry.discipline == 'singles'
                                    and entry.stage == 'main'))
                        if form:
                            r.raw_name = form
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


async def relink_bracket_matches(db, tournament_id: int) -> int:
    """Attach a bracket match to slots the draw could not identify at ingest.

    `ingest_document` is the ONLY place `match_id` was ever written, and it
    returns early when the PDF has not changed — so the link was decided once,
    against whatever the bracket happened to know at that second, and never
    reconsidered. The sheet leads the bracket by hours: an R16 slot is printed
    while its two feeder matches are still on court, and the next-round pairing
    only exists in `matches` after the WIKI SCRAPE advances the winners
    (routers/tournaments._do_scrape) — a result landing from ESPN or Sofascore
    does not create it.

    Monterrey 2026-08-25: Parry's R32 was recorded at 05:55, the Tuesday sheet
    was ingested at 06:00 with the R16 pairing not yet in the bracket, and
    Oliynykova vs Parry stored `match_id = NULL`. Without live scores, a final
    score or a derived round the row is just a nicer PDF — the whole feature.
    It was rescued only because the WTA happened to reissue the sheet at 06:15;
    on the last revision of a day, which is the ordinary case once play starts,
    nothing would ever have retried and the 7:30 PM match would have sat there
    dead all evening. `bracket_match_missed` in schedule_invariants.py alerted
    and could not heal. This is the retry.

    Same shape and same call sites as `resolve_settled_alternatives`, which
    closed the identical gap on the other side of the sheet/bracket race (a
    slot still offering "A or B" the draw had already decided). Strict on
    identity for the same reason: both sides must name exactly one draw entry
    and that pair must be exactly one real match. A WRONG match_id is worse
    than none — the row would show another match's live score.
    """
    from datetime import timedelta as _td

    today = date.today()
    # Same refresh as the resolver above, and needed for the same reason: this
    # runs from the ingest's own session too. See _READ_THE_DAY_AS_STORED.
    await db.flush()
    entries = (await db.execute(
        select(ScheduleEntry).where(
            ScheduleEntry.tournament_id == tournament_id,
            ScheduleEntry.match_id.is_(None),
            # Only singles can resolve: qualifying has no rows in `matches`
            # and doubles has no draw at all.
            ScheduleEntry.discipline == 'singles',
            ScheduleEntry.stage == 'main',
            ScheduleEntry.is_tbd.is_(False),
            ScheduleEntry.play_date >= today - _td(days=1),
            # See _READ_THE_DAY_AS_STORED.
        ).execution_options(populate_existing=True))).scalars().all()
    if not entries:
        return 0

    draw_rows = (await db.execute(
        select(Draw).where(Draw.tournament_id == tournament_id))).scalars().all()
    if not draw_rows:
        return 0
    draw_by_id = {d.id: d for d in draw_rows}
    dents = (await db.execute(
        select(DrawEntry.id, DrawEntry.name)
        .where(DrawEntry.draw_id.in_(list(draw_by_id))))).all()
    # Keyed on `_fold`, the fold under which the draw's "Mees Röttgering" and
    # the sheet's "ROTTGERING" finally agree — see _match_tokens.
    by_fold: dict = {}
    for eid, name in dents:
        by_fold.setdefault(_fold(name), []).append(eid)
    pair_match = {}
    for m in (await db.execute(
            select(Match).where(Match.draw_id.in_(list(draw_by_id)),
                                Match.player1_id.isnot(None),
                                Match.player2_id.isnot(None)))).scalars().all():
        pair_match.setdefault(frozenset((m.player1_id, m.player2_id)), []).append(m)

    healed = []
    for entry in entries:
        players = list(entry.players or [])
        na = [p for p in players if p.side == 'a']
        nb = [p for p in players if p.side == 'b']
        if not na or not nb:
            continue
        sides = []
        for side in (na, nb):
            ids = set()
            for p in side:
                if p.draw_entry_id:
                    ids.add(p.draw_entry_id)
                else:
                    ids |= set(by_fold.get(_fold(p.raw_name), ()))
            sides.append(ids)
        if not all(len(ids) == 1 for ids in sides):
            # A side naming nobody in the draw is the withdrawal case — the
            # substitute reaches `draw_entries` only when the scrape catches
            # up, and _absorb hands the retired row's link over meanwhile.
            continue
        pair = frozenset((next(iter(sides[0])), next(iter(sides[1]))))
        found = pair_match.get(pair) or []
        if len(pair) != 2 or len(found) != 1:
            continue
        found = found[0]
        # Ids are a ratchet: this pair just proved itself against the bracket,
        # which is stronger evidence than the name match `_sync_players` had at
        # ingest. A player row still holding NULL — their draw_entries row
        # arrived after the sheet did — gets stamped here rather than waiting
        # for a revision, because everything downstream (ranking, seed,
        # nationality, H2H) keys on that id and silently skips the row without.
        for side, ids in zip((na, nb), sides):
            if len(side) == 1 and side[0].draw_entry_id is None:
                side[0].draw_entry_id = next(iter(ids))
        entry.match_id = found.id
        entry.draw_id = found.draw_id
        derived = _round_label(found.round_number,
                               draw_by_id[found.draw_id].num_rounds
                               if found.draw_id in draw_by_id else None)
        if derived:
            entry.round_label = derived
        healed.append((entry, found.id))

    if not healed:
        return 0
    await db.commit()
    # AFTER the commit: app_log opens its own session and SQLite allows one
    # writer, so logging while this one still held writes blocked on a lock
    # the same task was holding. Same rule as the ingest tail.
    from app.services.system_log import app_log
    await app_log(
        "info", "order_of_play",
        f"Linked {len(healed)} schedule slot(s) to a bracket match that did "
        f"not exist at ingest time: "
        + "; ".join(f"entry {e.id} -> match {mid}" for e, mid in healed[:5]),
        {"tournament_id": tournament_id,
         "linked": [[e.id, str(e.play_date), mid] for e, mid in healed[:20]]})
    logger.info("Relinked %d schedule slot(s) for tournament %s",
                len(healed), tournament_id)
    return len(healed)


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

    # LOOKED UP, not defaulted. `venue_tz` used to fall back to UTC when the
    # caller left it out, and that silently reads every printed clock on the
    # sheet as a UTC one: Winston-Salem's "Starts At 2:00 PM" became 14:00Z
    # instead of 18:00Z and the whole day's expected starts — printed rows and
    # the chain behind them alike — moved four hours early, with nothing
    # logged and printed_start_at (computed at serve time from the same
    # venue_timezone) still correct beside them. The three production callers
    # all pass it; a manual re-ingest from a console does not, which is
    # exactly when nobody is watching the clocks.
    #
    # The zone is a property of the tournament, not of the call, so ask the
    # draws for it rather than assuming. UTC remains the last resort for a
    # tournament whose draws carry no zone at all — there the printed time is
    # the only reading available.
    tz = None
    if not venue_tz:
        venue_tz = (await db.execute(
            select(Draw.venue_timezone).where(
                Draw.tournament_id == tournament_id,
                Draw.venue_timezone.isnot(None)))).scalars().first()
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
                walkover = finished_at is not None and not _played(
                    (getattr(m, 'scores_json', None) if m is not None
                     else s.scores_json))
                if walkover:
                    # The court was never occupied, so it is freed by whatever
                    # came BEFORE this row: prev_end is left exactly as it was.
                    s.estimated_duration_min = 0
                elif finished_at:
                    prev_end = finished_at + gap
                    s.estimated_duration_min = dur
                else:
                    # A LIVE SCORE DOES NOT MEAN A MATCH ON COURT. A match
                    # suspended overnight keeps its score, and its row on the
                    # next day's sheet says "Not before 12:30 PM" — yet this
                    # branch read "in progress" and answered "done in about an
                    # hour, from now". At 1 AM in New York that filed every
                    # "followed by" match behind it between 1 and 6 AM, ahead
                    # of the day's first ball, and the time view sorted them
                    # there (US Open R64, 2026-09-02).
                    # The court is busy from whenever the match can actually be
                    # on it: its printed slot today if that is still ahead, or
                    # the end of whatever the chain has in front of it — the
                    # same rule a "Not before" row gets — and only otherwise
                    # now. Two signals say it is waiting rather than playing:
                    # the feed's own suspended flag, or a slot on THIS day that
                    # has not arrived. A match that merely began a few minutes
                    # early trips the second by those few minutes, harmlessly.
                    waiting = (is_suspended(live_json)
                               or (printed_dt is not None and printed_dt > now))
                    anchor = now
                    if waiting:
                        anchor = max(t for t in (now, printed_dt, prev_end) if t)
                        if anchor > now:
                            # Still to come today, so it is a plan like any
                            # other pending row, and reads as one.
                            s.expected_start_at = anchor
                            s.expected_source = ('printed' if anchor == printed_dt
                                                 else 'estimated')
                    prev_end = anchor + timedelta(
                        minutes=_remaining_minutes(live_json, s.discipline)) + gap
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
