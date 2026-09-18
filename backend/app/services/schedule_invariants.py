"""
The law of the schedule: every shape a day's entries must satisfy, as CODE.

Each rule here exists because a real bug shipped it — the header of every
check names the incident. The LLM verifier judges; this module does not: it
runs on every ingest, on a 15-minute sweep, and UNDER the verifier's verdict
(the runner re-checks and overrides a "clean" that an invariant contradicts).
An LLM checklist has loopholes; a law does not.

THE RATCHET: when a new schedule bug is fixed — by a human or by the
verifier — a check for its class is added HERE in the same commit. That is
what makes the system converge on "never again" instead of on a longer
checklist.
"""

import re
import unicodedata as _ud
from datetime import timedelta as _timedelta, timezone as _tz

from sqlalchemy import select

from app.models.schedule import ScheduleDocument, ScheduleEntry
from app.services.oop_parser import COUNTRY_CODES


# How many of the DAY'S OWN revisions have come and gone without restating a
# slot before it counts as abandoned. One is the window between a sheet
# dropping a row and `_retire_pulled_slots` acting on it at the next ingest,
# which is a fix in progress, not a fault.
UNCONFIRMED_GRACE = 2


def revisions_since(day_doc_ids, last_document_id) -> int:
    """How many of this day's sheets are newer than the one that last printed
    a slot.

    COUNTED, never subtracted. Document ids are global, so
    `latest_doc - last_document_id` counts every other tournament's sheet
    fetched in between and would call a one-revision gap a five-revision one on
    a busy afternoon. The caller passes the ids scoped to this tournament and
    date, which is the only set where the answer means anything.
    """
    return sum(1 for d in day_doc_ids if d > (last_document_id or 0))


def _naive_utc(dt):
    """A timestamp column as naive UTC, whichever end of the session it came
    from. A row read back from SQLite is naive; one written earlier in the
    same session still holds the aware value it was assigned, and comparing
    the two raises TypeError — which, inside `_dedupe_day`, once took a whole
    day's ingest with it (2026-08-20). Every comparison of two of these
    columns goes through here."""
    if dt is None:
        return None
    return dt.astimezone(_tz.utc).replace(tzinfo=None) if dt.tzinfo else dt


# The sheet's own words, in the places a name can pick them up. A slot wording
# printed on its own line sits directly above or below a name and has been
# absorbed by both ends of the parse before now.
_SLOT_WORDING_RE = re.compile(
    r'\b(?:TB[ACD]|followed\s+by|not\s+bef|start(?:s|ing)?\s+at|'
    r'N\s*[./]?\s*B\.?\s*\d{1,2}(?:[:.]\d{2}|\s*[ap]\.?m\.?)|'
    r'to\s+be\s+(?:arranged|confirmed|announced|advised|determined))\b', re.I)
_TRAILING_SEED_RE = re.compile(r'(?:\s*\[[^\]]*\])+\s*$')
_TRAILING_CODE_RE = re.compile(r'\s([A-Z]{3})$')
# Order-of-play sheets print the SURNAME in capitals, every tour, every tier.
# A stored name with no capitalised run therefore did not come from the sheet.
_SHEET_CAPS_RE = re.compile(r'(?<![A-Za-z])[A-Z]{2,}(?![a-z])')
# One letter standing in for a given name — "D." or a bare "D". Two letters is
# a name the sheets really print (JJ TRACY), so the count matters.
_INITIAL_RE = re.compile(r'^[A-Za-z]\.?$')
# The other side of the same coin: a token carrying two or more letters is a
# WORD — a name, not an initial. "Li" and "Tu" are surnames; "A." is not.
_WORDY_RE = re.compile(r'[A-Za-z].*[A-Za-z]', re.S)
# The qualifying round tokens, enumerated — "QF" starts with Q and is not one.
_QUALI_ROUND_RE = re.compile(r'^(?:Q\d?|FQ)$', re.I)
# THE ROLES A SHEET PRINTS WHERE A PERSON WOULD GO — "Qualifier", "LL", "Bye".
# Read here as a TOKEN test over the whole string, where oop_parser._is_placeholder
# matches each "/"-separated segment whole. That disagreement is the point: the
# parser decides what a placeholder IS, and the law decides whether the row it
# produced names anybody, so a line the parser admits as a name while every word
# in it is a role still fails here.
_ROLE_TOKEN_RE = re.compile(
    r'^(?:qualifier|lucky|loser|alternate|special|exempt|'
    r'LL|ALT|SE|Q\d?|BYE|TBD|TBA)$', re.I)
# A leading entry-status marker, "[LL] " / "[WC] " — the mirror of
# _TRAILING_SEED_RE, which only strips the ones printed after the name.
_LEADING_SEED_RE = re.compile(r'^(?:\[[^\]]*\]\s*)+')
# Everything that is not a letter, for counting the letters a token carries —
# "H." is an initial wearing a capital, not a shouted surname.
_ALPHA_RE = re.compile(r'[^A-Za-z]')
# Lone letters standing on their own where a name's letters belong. A name may
# hold ONE ("Alex de Minaur" does not, but an initial-only rendering might);
# three is not a name any tour prints. Measured over all 705 stored player
# rows: fires on the four shredded ones below and on nothing else.
_SHRED_MIN_SINGLES = 3


def _names_nobody(raw: str) -> bool:
    """Is this stored player row a ROLE rather than a person?

    Every word left after the seeding, the country and the punctuation come
    off is a role the tour prints for a seat nobody has taken yet. Sao Paulo
    2026-09-14 printed three R32 slots "[Q/LL] Qualifier/LL"; that is not a
    name, and the two rules below decide what a row holding one may look like.
    """
    s = _LEADING_SEED_RE.sub("", _TRAILING_SEED_RE.sub("", (raw or "").strip()))
    toks = [t for t in re.split(r'[\s/]+', s) if t]
    while toks and toks[-1] in COUNTRY_CODES:
        toks.pop()
    return bool(toks) and all(_ROLE_TOKEN_RE.match(t) for t in toks)


_CLOCK_RE = re.compile(r'^(\d{1,2})[:.](\d{2})\s*(am|pm)?$', re.I)
# A not-before wording as the LAW reads it: spelled out, clipped ("Not Bef."),
# or abbreviated in front of a clock ("NB 3:30 PM", "N/B 2:30"). Stated apart
# from schedule._NOT_BEFORE_RE on purpose — see _printed_instant.
_NOT_BEFORE_WORDING_RE = re.compile(
    r'\bnot\s+bef|(?<![A-Za-z])N\s*[./]?\s*B\.?\s*'
    r'\d{1,2}(?:[:.]\d{2}|\s*[ap]\.?m\.?)', re.I)
# How long a document may lag a result before its silence about that result
# means anything — one poll of `refresh_order_of_play` (scheduler.py, every 15
# minutes). Below it, `fetched_at` cannot even place the sheet's publication.
# See `pending_side_decided_before_document`.
_REISSUE_LATENCY = _timedelta(minutes=15)

# A clock the SHEET printed, as the LAW reads one off a slot note — stated
# here and not imported from oop_parser for the reason _printed_instant gives:
# the reading the law measures the parser against must not be the parser's.
# Deliberately wider, because a check for a clock the parser MISSED cannot be
# written in the parser's own vocabulary of a clock. A meridiem alone is
# enough ("4pm"); minutes alone are enough ("14:30"); a lone number is not, so
# "30 mins after ceremony" and "R16" stay ordinary text.
_NOTE_CLOCK_RE = re.compile(
    r'(?<![\d:.])\d{1,2}(?:[:.]\d{2}\s*(?:[ap]\.?m\.?)?|\s*[ap]\.?m\.?)'
    r'(?![\d:.])', re.I)


def _printed_instant(entry, tz_name):
    """The slot's printed venue-local clock as a UTC instant, or None.

    Its OWN parse, like _SHEET_CAPS_RE above and for the same reason: this is
    the independent reading that `expected_contradicts_printed` measures
    recompute_expected_starts against. Sharing the zone handling with the code
    under test is exactly how the law goes blind.
    """
    from datetime import datetime as _dt, time as _time
    from zoneinfo import ZoneInfo

    if not entry.start_time_local or not tz_name or not entry.play_date:
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
    return _dt.combine(entry.play_date, _time(hour, minute),
                       tzinfo=tz).astimezone(_tz.utc)


def clock_runs_backwards(rows, tz_name) -> list[tuple]:
    """(row, the row above it) wherever a court's printed clock goes BACK in time.

    Down one court, in `court_order`, each printed clock is at or after every
    clock printed above it — that is what an order of play is. A clock earlier
    than one above it was read in the wrong half of the day: SP Open
    2026-09-17 stored "NB 2:30" as 2:30 AM under "Not before 1:00 PM". Read
    through the law's own `_printed_instant`, so it does not share the
    parser's `settle_meridiems`. Measured over every stored court-day when it
    was written (278): those two rows and nothing else.
    """
    courts: dict = {}
    for r in rows:
        if r.court:
            courts.setdefault(r.court, []).append(r)
    out = []
    for court_rows in courts.values():
        court_rows.sort(key=lambda r: (r.court_order is None, r.court_order or 0, r.id))
        latest = latest_row = None
        for r in court_rows:
            when = _printed_instant(r, tz_name)
            if when is None:
                continue
            if latest is not None and (latest - when).total_seconds() > 60:
                out.append((r, latest_row))
            if latest is None or when > latest:
                latest, latest_row = when, r
    return out


# A wording that places its match BEHIND something, and one that says the time
# is unknown — the law's own reading of both, apart from oop_parser's.
_CHAINS_BEHIND_RE = re.compile(r'follow|\bafter\b', re.I)
_TIME_UNKNOWN_RE = re.compile(r'\bTB[ACD]\b|\bto\s+be\s+\w', re.I)


def document_clocks(day_docs) -> dict:
    """-> {document id: when its BYTES were downloaded}.

    Split out from `check_day` so the judgement can be tested without a
    database, like `clock_runs_backwards` and `printed_clock_not_captured`.

    Usually just `fetched_at`. The exception is a forced re-parse: to defeat
    the unchanged-bytes skip it clears the stored `sha256`, and ingest then
    mints a NEW document stamped `now` for a PDF we already held. Nothing
    about the tour happened at that moment, so the re-parse inherits the clock
    of the fetch it re-reads — the cleared sha on the document before it is
    the marker, and a chain of them carries the original clock through.
    """
    out: dict = {}
    carried = None
    for d in sorted(day_docs, key=lambda x: x.id):
        when = _naive_utc(d.fetched_at)
        if carried is not None:
            when, carried = carried, None
        if str(d.sha256 or '').startswith('forced'):
            carried = when
        out[d.id] = when
    return out


def printed_clock_not_captured(rows) -> list:
    """Slots whose printed NOTE states a clock the row did not store.

    -> [(row, the clock the law read)]. Split out from `check_day` so the
    judgement can be tested without a database, like `clock_runs_backwards`
    and `_slot_was_pulled`.

    A "time unknown" wording is exempt: "AFTER REST, TIME TBA" says outright
    that there is no clock, and Cincinnati prints "Not Before 3:00 PM" with
    "TBA" on the line below — neither is a clock the ingest dropped.
    """
    out = []
    for r in rows:
        if r.start_time_local or not r.start_note:
            continue
        if _TIME_UNKNOWN_RE.search(r.start_note):
            continue
        m = _NOTE_CLOCK_RE.search(r.start_note)
        if m:
            out.append((r, m.group(0).strip()))
    return out


def court_opener_untimed(rows) -> list:
    """Rows that OPEN their court with a chaining wording and no clock at all.

    A court's first stored row has nothing ahead of it to chain from, so a
    "Followed by" there, with no clock, names a box the ingest never read. SP
    Open 2026-09-17 (document 277) printed QUADRA 2's first box blank under
    "Starting at 12:00 PM" and the next one "Followed by"; the parser dropped
    the blank box and its noon with it, and Avanesyan/Charaeva went out with no
    time at all, filed after the day's 7:20 PM finish.

    Exempt: a note that SAYS the time is unknown (Guadalajara 2026-09-17,
    "Time TBA - After suitable rest" under a court's blank, unworded first
    band — silence the sheet chose), and a row already on court, whose start
    is history. Read off start_type AND the note, so a misfiled type cannot
    hide it.
    """
    courts: dict = {}
    for r in rows:
        if r.court:
            courts.setdefault(r.court, []).append(r)
    out = []
    for court_rows in courts.values():
        first = min(court_rows, key=lambda r: (r.court_order is None,
                                               r.court_order or 0, r.id))
        note = first.start_note or ""
        if (first.start_time_local
                or (first.start_type not in ("followed_by", "after_event")
                    and not _CHAINS_BEHIND_RE.search(note))
                or _TIME_UNKNOWN_RE.search(note)
                or first.started_at or first.completed_at
                or first.winner_side or first.live_scores_json):
            continue
        out.append(first)
    return out


def _law_person(raw: str) -> str:
    """A printed name as the LAW identifies a person: brackets gone, every
    trailing country code gone (by membership, looped — SURESH IND ANY),
    accents and case folded. Its own reading, apart from schedule._fold."""
    s = re.sub(r'\[[^\]]*\]', ' ', raw or '')
    toks = s.split()
    while len(toks) > 1 and toks[-1] in COUNTRY_CODES:
        toks.pop()
    s = _ud.normalize("NFKD", " ".join(toks))
    return " ".join(re.sub(r'[^a-z ]', '', "".join(
        c for c in s if not _ud.combining(c)).lower()).split())


def player_on_two_courts(rows) -> list[tuple]:
    """(row, other row, the person) wherever two rows still to come book one
    person on different courts into overlapping windows.

    SP Open 2026-09-18 (document 289): Stoiana's doubles QF on QUADRA 1,
    printed "After suitable rest", was estimated "~5:30 PM" and listed ABOVE
    her singles QF on CENTRAL at "Not before 5:30 PM". The estimate chain runs
    down one court at a time and never saw the name on the other one. Nothing
    was wrong with the rows the sheet printed; the page was simply impossible.

    A window is [expected_start_at, + estimated_duration_min]. Only rows not
    yet on court, since a match in play has a remaining time the law cannot
    read. Exempt: two starts the sheet itself FIXED ("Starting at"), which no
    estimate may move — the tour's own clash, not ours. Nobody on a side the
    sheet leaves open is booked, nor a role ("Qualifier"). Split out so the
    judgement can be tested without a database. Measured over every stored
    tournament-day when written: that one pair, of 23 that share a player.
    """
    def pending(r):
        return not (r.started_at or r.completed_at or r.winner_side
                    or r.live_scores_json or r.status in ("live", "completed"))

    def fixed(r):
        return r.start_type == "fixed" and r.expected_source == "printed"

    def window(r):
        start = _naive_utc(r.expected_start_at)
        if start is None or not r.estimated_duration_min:
            return None
        return start, start + _timedelta(minutes=r.estimated_duration_min)

    booked: dict = {}
    for r in rows:
        if not pending(r):
            continue
        open_sides = (r.tbd_side or "ab") if r.is_tbd else ""
        for p in r.players or []:
            if p.side in open_sides or _names_nobody(p.raw_name or ""):
                continue
            keys = {("name", _law_person(p.raw_name))}
            if p.draw_entry_id:
                keys.add(("id", p.draw_entry_id))
            for k in keys:
                if k[1]:
                    booked.setdefault(k, {})[r.id] = (r, p.raw_name)
    out, seen = [], set()
    for by_row in booked.values():
        items = sorted(by_row.values(), key=lambda x: x[0].id)
        for i, (a, name) in enumerate(items):
            for b, _ in items[i + 1:]:
                if (a.id, b.id) in seen or (a.court or "") == (b.court or ""):
                    continue
                if fixed(a) and fixed(b):
                    continue
                wa, wb = window(a), window(b)
                if not wa or not wb:
                    continue
                overlap = min(wa[1], wb[1]) - max(wa[0], wb[0])
                if overlap.total_seconds() > 60:
                    seen.add((a.id, b.id))
                    out.append((a, b, name))
    return out


async def check_day(db, tournament_id: int, play_date) -> list[dict]:
    """Every violation in one tournament-day. Empty list = lawful."""
    # `populate_existing`, because the law runs on what the day ACTUALLY
    # stored and the ingest calls it with the session that wrote the day.
    # `AsyncSessionLocal` is expire_on_commit=False and `players` is
    # lazy="selectin", so without this a plain select returns the entry with
    # the player collection it held before `_sync_players` touched it — rows
    # already deleted still in it, rows just added missing from it. Monterrey
    # 2026-08-29 reported `singles_side_stacked` for a player the resolver had
    # deleted seconds earlier, and then two more violations against a side
    # whose second alternative the law could not see. A law reading stale rows
    # convicts the innocent and acquits the guilty in the same pass.
    # NO flush here, unlike the two resolvers: a check must never write. See
    # schedule._READ_THE_DAY_AS_STORED.
    rows = (await db.execute(
        select(ScheduleEntry).where(
            ScheduleEntry.tournament_id == tournament_id,
            ScheduleEntry.play_date == play_date,
        ).execution_options(populate_existing=True))).scalars().all()

    v: list[dict] = []

    # 2026-08-25, "CHOINSKI or ROTTGERING" beside a bracket that already knew
    # Rottgering had won: an unresolved side whose deciding match is complete
    # asserts an open question the draw has closed. The resolver
    # (schedule.resolve_settled_alternatives) collapses these from every
    # winner-writing path; this is the tripwire if any path forgets.
    from app.models.tournament import Draw, DrawEntry, Match
    from app.services.schedule import _fold, _match_tokens
    draw_ids = (await db.execute(
        select(Draw.id).where(Draw.tournament_id == tournament_id))).scalars().all()
    dents = (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id.in_(draw_ids)))).scalars().all() if draw_ids else []
    by_fold = {}
    for de in dents:
        by_fold.setdefault(_fold(de.name), []).append(de.id)
    decided = {frozenset((m.player1_id, m.player2_id)): m.winner_id
               for m in (await db.execute(
                   select(Match).where(Match.draw_id.in_(draw_ids),
                                       Match.winner_id.isnot(None)))).scalars().all()
               if m.player1_id and m.player2_id} if draw_ids else {}
    # Every real bracket pairing, decided or not. `decided` above only holds
    # finished matches; linking a slot is about the pairing existing at all.
    pair_match = {frozenset((m.player1_id, m.player2_id)): m.id
                  for m in (await db.execute(
                      select(Match).where(Match.draw_id.in_(draw_ids),
                                          Match.player1_id.isnot(None),
                                          Match.player2_id.isnot(None)))).scalars().all()
                  } if draw_ids else {}

    # The SERVE path's own resolver, run here so the law can see the shape the
    # API actually hands out. See settled_side_not_two below for why a check
    # over the stored rows cannot.
    from datetime import date as _date, timedelta as _td
    from app.services.schedule import (
        _sheet_surnames, settle_from_result_rows, settled_sides_index)
    _pd = _date.fromisoformat(play_date) if isinstance(play_date, str) else play_date
    venue_tz = (await db.execute(
        select(Draw.venue_timezone).where(
            Draw.tournament_id == tournament_id,
            Draw.venue_timezone.isnot(None)))).scalars().first()
    settled_idx: dict = {}
    # WHEN each of those results landed, and when the document that last
    # restated each slot was fetched — the two clocks
    # `pending_side_decided_before_document` compares.
    #
    # Keyed through `settled_sides_index`'s OWN reading of a name, not a
    # second one: this index is a join onto that one, and a law that keys its
    # side of a join differently does not disagree loudly, it silently never
    # matches. (Where the law needs an independent reading it keeps one — see
    # _SHEET_CAPS_RE and _printed_instant. A join key is not that.)
    decided_at: dict = {}
    # WHEN each revision of this day was published. Read unconditionally —
    # `slot_pulled_not_retired` below needs it on a day with no unresolved row
    # at all, which is exactly the day SP Open had on 2026-09-14.
    day_docs = (await db.execute(
        select(ScheduleDocument).where(
            ScheduleDocument.tournament_id == tournament_id,
            ScheduleDocument.play_date == _pd))).scalars().all()
    # WHEN THE BYTES WERE DOWNLOADED, which is not always when the row was
    # written. A forced re-parse re-reads a PDF we already hold: it clears the
    # stored `sha256` to defeat the unchanged-bytes skip, and ingest then mints
    # a NEW document stamped `now`. Nothing about the tour happened at that
    # moment, and every clock the law reads off that document is the re-parse's
    # clock rather than the sheet's.
    #
    # It is not a rare path — the order-of-play verification harness re-ingests
    # the archived PDF on every run. On 2026-09-18 that turned document 284
    # (fetched 21:24:51, three minutes after a doubles feeder finished, and
    # byte-identical to the sheet still live on wtatennis.com) into document
    # 285 stamped 21:52:40, and `pending_side_decided_before_document`
    # convicted a row that reproduces its sheet exactly — on the strength of
    # the restamp alone. The cleared sha is the marker of the re-read, so the
    # document that follows it inherits the clock of the fetch it re-reads.
    doc_fetched: dict = document_clocks(day_docs)
    if any(e.is_tbd for e in rows):
        wins = (await db.execute(
            select(ScheduleEntry).where(
                ScheduleEntry.tournament_id == tournament_id,
                ScheduleEntry.winner_side.isnot(None),
                ScheduleEntry.play_date >= _pd - _td(days=14),
                ScheduleEntry.play_date <= _pd))).scalars().all()
        settled_idx = settled_sides_index(wins)
        for r in wins:
            a = _sheet_surnames([p.raw_name for p in r.players if p.side == "a"])
            b = _sheet_surnames([p.raw_name for p in r.players if p.side == "b"])
            if a and b and r.completed_at is not None:
                decided_at[frozenset(a | b)] = _naive_utc(r.completed_at)

    def flag(code, entry, detail):
        v.append({"code": code, "entry_id": entry.id if entry else None,
                  "court": getattr(entry, "court", None), "detail": detail})

    seen_pairings: dict[frozenset, int] = {}
    seen_pending: dict[tuple, int] = {}
    court_orders: dict[tuple, int] = {}

    for e in rows:
        players = list(e.players or [])
        na = [p for p in players if p.side == "a"]
        nb = [p for p in players if p.side == "b"]
        tbd_side = e.tbd_side or ""

        if e.is_tbd:
            for side_key in (e.tbd_side or "ab"):
                rows_side = [p for p in players if p.side == side_key]
                if len(rows_side) < 2:
                    continue
                ids = []
                for r in rows_side:
                    if r.draw_entry_id:
                        ids.append(r.draw_entry_id); continue
                    cand = by_fold.get(_fold(r.raw_name)) or []
                    if len(cand) == 1:
                        ids.append(cand[0])
                    else:
                        ids = None; break
                if ids and frozenset(ids) in decided:
                    flag("alternatives_already_decided", e,
                         f"side {side_key}: "
                         + " or ".join(r.raw_name or "" for r in rows_side)
                         + " — feeder match has a winner")

        # 2026-08-26, Winston-Salem: every expected start on the day sat four
        # hours early. `recompute_expected_starts` took the venue timezone as
        # an OPTIONAL argument and fell back to UTC, so a caller that omitted
        # it read "Starts At 2:00 PM" as 14:00Z. Nothing errored, nothing was
        # logged, and `printed_start_at` — derived at serve time from the same
        # venue_timezone — stayed correct right beside the wrong estimate.
        #
        # A row whose start is PRINTED has no estimating to do: the sheet
        # states the moment, so expected_start_at must BE that moment. When
        # the two disagree, whoever wrote expected_start_at was reading the
        # clock in the wrong zone — which is the only way they can disagree,
        # and the reason this catches the whole family rather than one caller.
        if e.expected_source == "printed" and e.expected_start_at is not None:
            want = _printed_instant(e, venue_tz)
            got = e.expected_start_at
            if want is not None:
                if got.tzinfo is None:
                    got = got.replace(tzinfo=_tz.utc)
                if abs((got - want).total_seconds()) > 60:
                    flag("expected_contradicts_printed", e,
                         f"printed {e.start_time_local!r} is {want.isoformat()} "
                         f"at {venue_tz}, but expected_start_at is "
                         f"{got.isoformat()}")

        # 2026-09-15, Guadalajara CANCHA MEXCOVERY.COM: the sheet printed
        # "NB 3:30 PM - After suitable rest" and the page said "~2:50 PM".
        # `_start_type_of` knew only the spelled-out "not before", so the
        # abbreviation fell to its "after" branch, and the estimate chain —
        # which floored only a not_before — let the predecessor's end undercut
        # a time the match cannot start before. Two readings, two codes.
        #
        # The WORDING: a note that says not-before must be stored as one, or
        # every consumer that branches on start_type (the chain, both clients'
        # floor rendering) treats a floor as a guess.
        if (e.start_note and _NOT_BEFORE_WORDING_RE.search(e.start_note)
                and e.start_type != "not_before"):
            flag("not_before_wording_misread", e,
                 f"start_note {e.start_note!r} states a not-before floor but "
                 f"start_type is {e.start_type!r}")
        # The CLOCK: an estimate may run late of a printed time, never early —
        # whatever the start_type says, so a misread wording cannot hide it.
        # Only for a row still to come: once a match is on court its start is
        # history, and recompute pins it to the printed time.
        if (e.expected_source == "estimated" and e.expected_start_at is not None
                and not (e.started_at or e.completed_at or e.winner_side
                         or e.live_scores_json)):
            want = _printed_instant(e, venue_tz)
            got = e.expected_start_at
            if want is not None:
                if got.tzinfo is None:
                    got = got.replace(tzinfo=_tz.utc)
                if (want - got).total_seconds() > 60:
                    flag("expected_undercuts_printed_floor", e,
                         f"printed {e.start_note or e.start_time_local!r} is "
                         f"{want.isoformat()}, but the estimate "
                         f"{got.isoformat()} starts the match before it")

        # tbd_side must be one of a/b/ab — anything else means a writer
        # invented a value nothing downstream reads. (Defensive; no incident.)
        if e.tbd_side not in (None, "", "a", "b", "ab"):
            flag("tbd_side_invalid", e, f"tbd_side={e.tbd_side!r}")

        # 2026-08-26, Winston-Salem COURT 4: a doubles row carrying draw 121,
        # the men's SINGLES draw. We store no doubles draw at all, so a
        # non-singles row has nothing it could legitimately point at — but its
        # players resolve to draw_entries (their singles rows), and the ingest
        # fallback took a draw off the first one that matched. draw_id is what
        # `surface` and `gender` are served from, so the row published three
        # facts about somebody else's event. The seed leaked through the same
        # doorway once and was gated at serve time; this gates the field.
        if e.discipline != "singles" and e.draw_id is not None:
            flag("nonsingles_row_carries_draw", e,
                 f"{e.discipline} row points at draw {e.draw_id}; "
                 "only singles rows have a draw")

        # 2026-08-25, Medvedev vs "DAMM / SHELBAYH": a singles slot stored an
        # unresolved "A or B" as two players on one side with no tbd flag, and
        # the site rendered a phantom doubles team. Two names on a singles
        # side are legal ONLY when that side is declared unresolved.
        if e.discipline == "singles":
            for side_key, side in (("a", na), ("b", nb)):
                if len(side) > 1 and side_key not in tbd_side:
                    flag("singles_side_stacked", e,
                         f"side {side_key}: " + " / ".join(p.raw_name or "" for p in side))

        # 2026-08-24, "KRAJICEK / MEKTIC vs CABRAL": a doubles team of one,
        # because an all-caps given name was dropped by the parser. A doubles
        # side that is neither empty (slot not yet decided) nor declared
        # unresolved must hold exactly two.
        # "mixed" is a pair like any doubles — the law learned the word the
        # night a settled Bencic/Cobolli side was flagged for being two
        # people (2026-08-26, expected 1 for mixed).
        if e.discipline in ("doubles", "mixed"):
            for side_key, side in (("a", na), ("b", nb)):
                if side and len(side) != 2 and side_key not in tbd_side:
                    flag("doubles_side_not_two", e,
                         f"side {side_key} has {len(side)}: "
                         + " / ".join(p.raw_name or "" for p in side))

        # 2026-08-26, Winston-Salem Court 3: once Schnaitter/Wallner beat
        # Lammons/Withrow, the page served "[1] ARRIBAGE / GUINARD" against a
        # single player called "SCHNAITTER / WALLNER" — a two-person team in
        # one player row, surnames only, no flags, on a doubles side where
        # every other row that day showed two flagged players.
        #
        # NOTHING ABOVE COULD SEE IT. The stored row is honestly unresolved —
        # "team or team" is the right way to hold an open side, and an
        # alternative that names two people is one row on purpose — so
        # `doubles_side_not_two` exempts it via `side_key not in tbd_side`.
        # That is the same exemption that blinded `pairing_duplicated` the day
        # before: when a rule about sides carves out is_tbd, check whether the
        # bug simply moved into the carve-out. Here the defect existed ONLY in
        # what was served, so the law runs the serve path's resolver
        # (routers/schedule.py calls the same two functions) and judges the
        # side it returns. A settled side is a side: one player for singles,
        # two for doubles, whatever it looked like while the question was open.
        if e.is_tbd and settled_idx:
            for side_key in (e.tbd_side or "ab"):
                sp = sorted((p for p in players if p.side == side_key),
                            key=lambda x: x.position or 1)
                served, resolved = settle_from_result_rows(sp, settled_idx)
                if not resolved:
                    continue
                want = 2 if e.discipline in ("doubles", "mixed") else 1
                if len(served) != want:
                    flag("settled_side_not_two", e,
                         f"side {side_key} resolves to {len(served)} player row(s), "
                         f"expected {want} for {e.discipline}: "
                         + " / ".join(p.raw_name or "" for p in served))

        # 2026-09-13, SP Open QUADRA CENTRAL slot 2: the row offered
        # "W. Osuigwe or F. Labrana" hours after Osuigwe had won that Q1 —
        # and the sheet agreed with us that she had. Document 238, fetched at
        # 01:08, printed "[4] Whitney OSUIGWE USA" against the still-open
        # Urrutia/Tikhonova pair; `_dedupe_day` merged that row into document
        # 237's, kept the STALER of the two because it named one more player,
        # and deleted the update. Only the serve path's resolver kept the page
        # honest, and it cannot when the feeder has no result row of its own.
        #
        # `alternatives_already_decided` above is the same rule over the
        # BRACKET, and it cannot see this: qualifying and doubles have no rows
        # in `matches` at all, so for them the only record of who came through
        # is another schedule row — exactly the half `settled_sides_index`
        # covers and the resolver does not.
        #
        # Gated on the two clocks, because an open side is not by itself a
        # fault. A sheet published BEFORE its feeder finished honestly prints
        # the choice, and the stored row is meant to keep saying what the
        # sheet said (routers/schedule.py settles it at serve time instead).
        # It is only when our newest parse of the slot came from a document
        # fetched AFTER the answer was known that an unresolved side means we
        # dropped what that document told us. On this very sheet the gate
        # separates the two sides correctly: side a's feeder finished 00:24
        # (before), side b's at 01:16 (after), and 238 printed exactly that.
        #
        # BOTH CLOCKS ARE OBSERVATIONS, NOT PUBLICATIONS, so a gap of minutes
        # between them is not evidence of anything. `fetched_at` is when the
        # poller happened to look, not when the sheet came out, and the tour
        # does not re-issue an order of play the instant a match ends — a
        # person does it. SP Open 2026-09-18 (document 284) printed
        # "J. Mikulskyte / A. Smith OR V. Strakhova / A. Tikhonova" for a
        # doubles quarter-final whose feeder our results feed timed at
        # 21:21:45, and we downloaded it at 21:24:51: three minutes, and the
        # row was convicted of losing a rendering that sheet never carried.
        #
        # The sheet's own "RELEASED" stamp cannot settle it either — that is
        # the stamp of the ORIGINAL release and does not move when the tour
        # amends the sheet in place. Documents 280 and 282 re-timed two slots
        # between them ("After suitable rest" -> "Not before 6:15 PM") under
        # an identical stamp, so it bounds neither what a document knew nor
        # when it was generated.
        #
        # So the gap must clear the coarser of the two clocks before it says
        # anything, and that is our own 15-minute poll (scheduler.py,
        # "refresh_order_of_play"): inside one polling interval a document's
        # publication cannot be placed at all. Measured over every stored row,
        # the gate fires once at a grace of zero — this false conviction, at
        # 3.1 minutes — and never at five minutes or beyond, while document
        # 238's real incident sat at 44 and stays convicted with room to
        # spare.
        #
        # A FLOOR ON THE EVIDENCE, not a tolerance on the fault: a slot still
        # unresolved beyond it is caught exactly as before, and what keeps the
        # page honest in the meantime is the serve path's resolver, which the
        # API applies whatever the stored row says.
        if e.is_tbd and settled_idx:
            fetched = doc_fetched.get(e.last_document_id)
            for side_key in (e.tbd_side or "ab"):
                alts = sorted((p for p in players if p.side == side_key),
                              key=lambda x: x.position or 1)
                if len(alts) != 2 or fetched is None:
                    continue
                _served, resolved = settle_from_result_rows(alts, settled_idx)
                if not resolved:
                    continue
                key = frozenset().union(
                    *(_sheet_surnames([p.raw_name]) for p in alts))
                done = decided_at.get(key)
                if done is not None and done + _REISSUE_LATENCY < fetched:
                    flag("pending_side_decided_before_document", e,
                         f"side {side_key} still offers "
                         + " or ".join(p.raw_name or "" for p in alts)
                         + f", but that match finished {done.isoformat()} and "
                           f"document {e.last_document_id} was fetched "
                           f"{fetched.isoformat()} — the newer sheet's "
                           "rendering of this slot was lost")

        # 2026-08-28, Monterrey ESTADIO: the doubles semi-final printed a choice
        # between two whole PAIRS — "M. Chwalinska / S. Kraus OR S. Aoyama /
        # E. Liang" — against a settled Joint/Xu. The rows were right, and
        # nothing above judged them: `doubles_side_not_two` exempts a declared-
        # unresolved side outright, and `settled_side_not_two` waits for the
        # side to settle, which for a semi-final printed at teatime is hours
        # away. So for as long as the question is OPEN — which is exactly when
        # the slot is on the page and being read — the shape of each
        # alternative is unchecked. That is the third time this is_tbd carve-out
        # has hidden something (see the two notes above); the shape of an
        # alternative is the part of it that had never been stated.
        #
        # An alternative names ONE COMPETITOR of the row's shape: one player for
        # singles, a pair for doubles. A doubles alternative that lost a partner
        # would read on the page as a lone player entering a doubles match, and
        # a singles alternative that GAINED a slash is the Medvedev phantom team
        # ("DAMM / SHELBAYH", 2026-08-25) reappearing inside the carve-out
        # instead of beside it, where `singles_side_stacked` is watching.
        #
        # Only a side actually offering a choice is judged. A side holding one
        # alternative is the whole side and is already covered above.
        if e.is_tbd:
            want_alt = 2 if e.discipline in ("doubles", "mixed") else 1
            for side_key in (e.tbd_side or "ab"):
                alts = [p for p in players if p.side == side_key]
                if len(alts) < 2:
                    continue
                for p in alts:
                    people = [x.strip() for x in (p.raw_name or "").split("/")
                              if x.strip()]
                    if len(people) != want_alt:
                        flag("alt_side_shape", e,
                             f"side {side_key} alternative {p.raw_name!r} names "
                             f"{len(people)} player(s), expected {want_alt} "
                             f"for {e.discipline}")

        # 2026-08-25, Monterrey "Alexandra PANOVA TBC": Cancha 4's last slot
        # printed a bare "TBC" where a start time would go, one line below the
        # doubles pair above it. Three capitals on their own line is also how
        # the layout wraps a nationality, so the parser read it as one and gave
        # Panova a country nobody has. The sheet's own words are never part of
        # a name, and where a name ends in a country code it has to BE a
        # country — LUZ, GUO and TBC all have the shape.
        for p in players:
            raw = (p.raw_name or "").strip()
            if _SLOT_WORDING_RE.search(raw):
                flag("name_holds_slot_wording", e,
                     f"side {p.side}: {raw!r} contains a slot wording")
            stripped = _TRAILING_SEED_RE.sub("", raw)
            m = _TRAILING_CODE_RE.search(stripped)
            if m and m.group(1) not in COUNTRY_CODES:
                before = stripped[:m.start()].split()
                # Only where a country would stand: after a SURNAME, which the
                # sheets print in capitals. "Orlando LUZ" ends in three
                # capitals too and is a whole name.
                if any(w.isupper() and any(c.isalpha() for c in w) for w in before):
                    flag("name_trailing_noncountry", e,
                         f"side {p.side}: {raw!r} ends in {m.group(1)!r}, not a country")

        # 2026-08-26, Winston-Salem "Ra p h a e l C O L L IG N O N ( B EL)or":
        # a cell whose text the sheet had shrunk to fit was clustered into one
        # line with the line BELOW it by pdfplumber's default y_tolerance, the
        # chars of both were then sorted by x, and the two names came back
        # interleaved letter by letter. Four rows across two courts published
        # that way — data checks all passed (the letters really are the ones
        # the sheet prints, in the right slot) and the page was unreadable and
        # overflowing its card. A name is words; a scatter of lone letters is
        # an extraction that came apart, whatever it spells.
        for p in players:
            raw = _LEADING_SEED_RE.sub(
                "", _TRAILING_SEED_RE.sub("", (p.raw_name or "").strip()))
            lone = sum(1 for t in raw.split() if len(t) == 1 and t.isalpha())
            if lone >= _SHRED_MIN_SINGLES:
                flag("name_letter_shredded", e,
                     f"side {p.side}: {p.raw_name!r} has {lone} lone letters — "
                     f"the text extraction came apart")

        # 2026-08-25, "Mees ROTTGERING vs Tomas MACHAC": the draw stores
        # "Mees Röttgering", `rankings._norm` expands the umlaut the German
        # way to "roettgering", and the sheets print plain ASCII — so the
        # ingest's two matchers never met the draw and a main-draw R32 sat on
        # the live page with no round badge, no player links and no scores
        # while the bracket had held the pairing for a day. `schedule._fold`
        # existed for exactly this and only one caller had been moved onto it.
        # A settled main-draw singles slot whose sides each name exactly one
        # draw entry, and whose pair IS a bracket match, must be linked to it.
        if (e.discipline == "singles" and e.stage == "main"
                and e.match_id is None and not e.is_tbd and na and nb):
            sides = [{i for p in side
                      for i in (by_fold.get(_fold(p.raw_name)) or [])}
                     for side in (na, nb)]
            if all(len(c) == 1 for c in sides):
                pair = frozenset((next(iter(sides[0])), next(iter(sides[1]))))
                if len(pair) == 2 and pair in pair_match:
                    flag("bracket_match_missed", e,
                         " vs ".join(p.raw_name or "" for p in (na[0], nb[0]))
                         + f" is bracket match {pair_match[pair]}, "
                           "but match_id is NULL")

        # 2026-08-25, Monterrey Oliynykova vs Parry: the check above fired for
        # a second, unrelated cause — the bracket had not advanced the R32
        # winners yet when the sheet was ingested, and `match_id` was written
        # ONLY inside ingest, which returns early on an unchanged PDF. Nothing
        # retried; the row was rescued by a reissued sheet 15 minutes later.
        # `schedule.relink_bracket_matches` is the retry, and it writes
        # match_id from a background sweep rather than from the parse — so the
        # complement of the rule above now has to be law too. A slot pinned to
        # a match that is NOT its own pairing shows ANOTHER match's live score,
        # which is strictly worse than showing none. Exempt: a side naming
        # nobody in the draw, which is the withdrawal hand-over in _absorb
        # (the substitute reaches draw_entries only when the scrape catches up).
        if (e.discipline == "singles" and e.stage == "main"
                and e.match_id is not None and not e.is_tbd and na and nb):
            sides = [{i for p in side
                      for i in (by_fold.get(_fold(p.raw_name)) or [])}
                     for side in (na, nb)]
            if all(len(c) == 1 for c in sides):
                pair = frozenset((next(iter(sides[0])), next(iter(sides[1]))))
                if len(pair) == 2 and pair_match.get(pair) not in (None, e.match_id):
                    flag("bracket_match_mismatch", e,
                         " vs ".join(p.raw_name or "" for p in (na[0], nb[0]))
                         + f" is bracket match {pair_match[pair]}, "
                           f"but match_id is {e.match_id}")

        # 2026-09-13, Guadalajara: three Q2 rows wore main-draw R32 match ids
        # and the two checks above were both blind to it — for the same reason
        # `pairing_duplicated` was blind to two pending rows, their own
        # `e.stage == "main"` gate. A wrongly linked row is exactly the row
        # that is not main, so a rule that only inspects main rows can never
        # see this class. `bracket_match_mismatch` needs both sides to name a
        # draw entry too; a qualifying slot never has both, because the loser
        # of a qualifying match is in no draw we store.
        #
        # The rule underneath is absolute and needs no name matching: only
        # main-draw SINGLES has rows in `matches` at all. Qualifying draws and
        # doubles draws are not stored, so any bracket match a non-main or
        # non-singles row finds belongs to somebody else. Measured over all
        # 884 stored entries: 392 of 392 main singles rows are linked and
        # every other row is not, bar the three this names.
        #
        # draw_id is deliberately NOT part of this: ingest gives a qualifying
        # singles row its players' draw_id on purpose, because surface and
        # gender are served off it. The match link is the contradiction.
        if e.match_id is not None and not (
                e.discipline == "singles" and e.stage == "main"):
            flag("bracket_link_outside_main", e,
                 f"{e.stage}/{e.discipline} row ({e.round_label}) holds "
                 f"match_id {e.match_id} — only main-draw singles has one")

        # 2026-08-25, Medvedev vs Damm: the row was created from a revision
        # that printed the slot unresolved, the bracket resolver replaced both
        # players with their DRAW names, and `raw_name` was write-once — so
        # two later revisions printing "[WC] Martin DAMM USA" could not undo
        # it. The page showed one line in Title Case with no flag and no [WC]
        # beside sixteen carrying both. Four rows across three tournaments
        # were frozen that way. A settled side must read as the sheet prints
        # it; an unresolved side is exempt, because sheets abbreviate the
        # alternatives they offer ("D. Parry or D. Vekic").
        for p in players:
            raw = (p.raw_name or "").strip()
            if raw and p.side not in tbd_side and not _SHEET_CAPS_RE.search(raw):
                flag("name_not_sheet_form", e,
                     f"side {p.side}: {raw!r} has no capitalised surname — "
                     f"not the sheet's rendering")

        # 2026-09-14, Sao Paulo: "[Q/LL] Qualifier/LL" — the tournament saying
        # the seat belongs to a qualifier or a lucky loser and to nobody yet.
        # The parser read it as a name and split it on the slash, which there
        # means PARTNERS, so three R32 singles slots published as doubles: a
        # three-person team ("[Q", "LL] Qualifier", "LL") against [3] Sierra,
        # wearing a DOUBLES badge, with the side never declared unresolved.
        # Two things must hold of a row that names nobody, and each would have
        # caught it alone: its side is DECLARED unresolved (or the page draws
        # an open seat as a settled opponent), and the side holds exactly ONE
        # row (a placeholder's "/" separates the ways the seat can be filled,
        # never two people — so it can never be a team).
        for side_key, side in (("a", na), ("b", nb)):
            holders = [p for p in side if _names_nobody(p.raw_name or "")]
            if not holders:
                continue
            if side_key not in tbd_side:
                flag("placeholder_side_not_unresolved", e,
                     f"side {side_key}: "
                     + " / ".join(p.raw_name or "" for p in holders)
                     + " names nobody, but the side is not declared unresolved")
            if len(side) > 1:
                flag("placeholder_side_split", e,
                     f"side {side_key} has {len(side)}: "
                     + " / ".join(p.raw_name or "" for p in side)
                     + " — an open seat is one row, not a team")

        # The same wreck read syntactically, which is the cheaper half: "[Q"
        # and "LL] Qualifier" are the two ends of ONE bracketed marker, torn
        # apart by a split the sheet never asked for. A stored name whose
        # brackets do not balance is a FRAGMENT — no tour prints one — however
        # plausible the words inside it look, and this fires whatever the rule
        # above thinks of the words.
        for p in players:
            raw = p.raw_name or ""
            if raw.count("[") != raw.count("]"):
                flag("name_bracket_unbalanced", e,
                     f"side {p.side}: {raw!r} — half of a bracketed marker, "
                     f"not a name")

        # 2026-08-25, Monterrey "Oleksandra OLIYNYKOVA vs D. Parry": the same
        # class as the rule above, through the door it leaves open. The sheet
        # abbreviates the alternatives it offers, and BOTH paths that turn a
        # set of alternatives into a settled side — schedule._printed_name at
        # ingest and schedule.resolve_settled_alternatives on every winner —
        # kept the abbreviation. The rule above only caught it because this
        # sheet prints "D. Parry" in title case; a tour that prints
        # "D. PARRY or D. VEKIC" satisfies the capitalised-surname test and
        # would have gone by unseen. An initial is a whole rendering short of
        # a settled row, however it is capitalised, so test the SHAPE: a lone
        # first letter where a given name belongs.
        for p in players:
            raw = _TRAILING_SEED_RE.sub("", (p.raw_name or "").strip())
            raw = re.sub(r"^(?:\[[^\]]*\]\s*)+", "", raw).strip()
            words = raw.split()
            if (len(words) > 1 and p.side not in tbd_side
                    and _INITIAL_RE.match(words[0])):
                flag("name_abbreviated_given", e,
                     f"side {p.side}: {p.raw_name!r} gives an initial where a "
                     f"settled row prints a name")

        # 2026-08-29, Monterrey "D. Parry OR A. Li": the resolver kept only
        # tokens LONGER than two characters, so "A. Li" reduced to nothing at
        # all — an empty probe matches nobody. [5] Ann Li sat on the women's
        # final with no flag, no ranking and no link to her own draw entry,
        # and the slot could never have absorbed the settled sheet naming the
        # winner, because `_side_resolves` needs her tokens too. Every short
        # surname the tours print is in this hole: LI, TU, XU, BU, HO, JI, WU.
        #
        # Stated independently of the matcher on purpose: a printed name that
        # still holds a WORD — two letters or more, after the seeding and the
        # country come off — must leave the matcher something to probe with.
        # When it does not, the matcher is structurally blind to that row
        # rather than merely unable to place the player today.
        for p in players:
            raw = _LEADING_SEED_RE.sub(
                "", _TRAILING_SEED_RE.sub("", (p.raw_name or "").strip()))
            code = _TRAILING_CODE_RE.search(raw)
            if code and code.group(1) in COUNTRY_CODES:
                raw = raw[:code.start()]
            # A team is DELIBERATELY unmatchable — it names two people and no
            # draw entry is two people. That is the check below, not this one.
            if "/" in raw:
                continue
            if any(_WORDY_RE.search(t) for t in raw.split()) \
                    and not any(_match_tokens(p.raw_name)):
                flag("name_no_matchable_token", e,
                     f"side {p.side}: {p.raw_name!r} names somebody and the "
                     f"matcher has nothing to probe with")

        # 2026-08-29, Monterrey "M. Joint / Y. Xu": an unresolved doubles side
        # offers a choice between two PAIRS, and each pair arrives as a single
        # printed name. Only one of that pair's two surnames survived the
        # length filter above, so the whole team matched Maya Joint's SINGLES
        # draw entry — and the pair then flew her flag, her nationality and
        # her ranking, while the alternative printed beside it carried none.
        # Two people are never one draw entry, whatever the tokens say.
        for p in players:
            if "/" in (p.raw_name or "") and p.draw_entry_id is not None:
                flag("team_name_claims_entry", e,
                     f"side {p.side}: {p.raw_name!r} names a team and carries "
                     f"draw_entry_id={p.draw_entry_id}")

        # 2026-08-24, Winston-Salem's three main-draw doubles matches, two of
        # them badged "Q": _classify's last-resort qualifying inference is
        # evidence about the SINGLES draw (not in `draw_entries`; surname seen
        # on a qualifying row this week) and it was being applied to doubles
        # rows, where the first half is vacuously true — we store no doubles
        # draw — and the second is the ordinary career of a doubles player who
        # also entered singles qualifying. A doubles row may only be qualifying
        # when the SHEET said so, which reaches us as a qualifying round label.
        if (e.discipline == "doubles" and e.stage == "qualifying"
                and not _QUALI_ROUND_RE.match((e.round_label or "").strip())):
            flag("doubles_qualifying_unstated", e,
                 f"doubles row filed stage=qualifying with round_label="
                 f"{e.round_label!r} — nothing on the sheet says qualifying")

        # An entry with no players on either side describes nothing; it can
        # only be parser debris. (Defensive; near-miss during the Winston-Salem
        # blank-qualifier work — blanks are meant to be filtered, not stored.)
        if not players:
            flag("entry_empty", e, "no players on either side")

        # 2026-08-24, Sonego-Kopriva: a superseded pairing survived a lucky-
        # loser substitution and the day showed 16 matches for a 15-match
        # sheet. Two settled entries naming the same players are one slot.
        if not e.is_tbd and players:
            key = frozenset((p.raw_name or "").strip().lower() for p in players)
            if key in seen_pairings:
                flag("pairing_duplicated", e,
                     f"same players as entry {seen_pairings[key]}")
            else:
                seen_pairings[key] = e.id

        # 2026-08-26, Winston-Salem: document 77 reprinted three slots
        # unresolved exactly as document 61 had — "DAMM vs KECMANOVIC or
        # MAROZSAN" and two more — and every one hashed to a fresh
        # pairing_key anyway, because _pairing_key switches from names to
        # draw-entry ids once every printed alternative resolves to the
        # bracket. All three were published twice and each phantom slot pushed
        # every estimated start behind it on its court about two hours late.
        # Neither neighbouring check could see it: `pairing_duplicated` above
        # exempts unresolved rows outright, and `slot_restated` below requires
        # the two rows to share NOBODY on the other side, while these agreed
        # on both sides. Two pending rows printing the same alternatives on
        # the same undecided side are one slot, whatever they hash to.
        if e.is_tbd and na and nb:
            # Keyed per side and sorted, so it survives the sides swapping
            # between revisions while still recording WHICH side was open —
            # "A or B vs C" and "A vs B or C" share every name and are not
            # the same slot.
            pending_key = tuple(sorted(
                (tuple(sorted((p.raw_name or "").strip().lower()
                              for p in players if p.side == side_key)),
                 side_key in tbd_side)
                for side_key in ("a", "b")))
            if pending_key in seen_pending:
                flag("pending_pairing_duplicated", e,
                     f"same unresolved slot as entry {seen_pending[pending_key]}")
            else:
                seen_pending[pending_key] = e.id

        # Two entries at one court_order on one court means the renumber pass
        # broke; the schedule page would show them in arbitrary order.
        if e.court and e.court_order is not None:
            ck = (e.court, e.court_order)
            if ck in court_orders:
                flag("court_order_duplicated", e,
                     f"{e.court} #{e.court_order} also entry {court_orders[ck]}")
            else:
                court_orders[ck] = e.id

    # 2026-09-17, SP Open document 275: "NB 2:30 possible court change",
    # printed without PM on a sheet that wrote AM/PM everywhere else, was
    # stored as 2:30 in the morning on two courts that had opened at 11:00 AM.
    # The floor check above passed it, because it reads the printed clock
    # through the same missing meridiem. An order of play never goes back in
    # time down a court, whatever the reading of any single clock is.
    for e, prev in clock_runs_backwards(rows, venue_tz):
        flag("printed_clock_runs_backwards", e,
             f"{e.court} #{e.court_order} prints {e.start_time_local!r}, earlier "
             f"than #{prev.court_order}'s {prev.start_time_local!r} above it — "
             f"a clock read in the wrong half of the day")

    # 2026-09-17, SP Open document 277: QUADRA 2's first box was printed blank
    # under "Starting at 12:00 PM" and the court's first match "Followed by".
    # The noon was dropped with the blank box, so the row had no clock and
    # nothing ahead of it: no estimate, a bare "Followed by" on the card, and
    # a place at the bottom of the Time view. `untimed_slot_served_first`
    # could not see it — the serve order was right about a row that should
    # never have been untimed.
    for e in court_opener_untimed(rows):
        flag("court_opener_untimed", e,
             f"{e.court} #{e.court_order} opens the court printed "
             f"{e.start_note or e.start_type!r} with no clock — it follows a "
             f"box the ingest never read, and the page can print no time")

    # 2026-09-18, SP Open document 284: "After suitable rest - NB 4pm" on
    # QUADRA 1. Every clock reader in the ingest demanded minutes, so the hour
    # was not a time to any of them — no `start_time_local`, an `after_event`
    # instead of a floor, and the estimate chain ran the match to "~3:30 PM"
    # under a printed 4:00.
    #
    # THE THREE FLOOR CHECKS ARE ALL DOWNSTREAM OF THE CLOCK BEING READ.
    # `expected_undercuts_printed_floor`, `printed_clock_runs_backwards` and
    # `not_before_wording_misread` all begin at `start_time_local`, so a clock
    # the parser did not recognise disarms every one of them at once — the
    # same way a clock read in the wrong half of the day disarmed the floor
    # check on document 275. This is the check UPSTREAM of those: the note
    # still holds whatever the tour printed, so the law can ask whether the
    # sheet stated a time that the row does not have, without knowing what
    # tomorrow's odd format will look like.
    for e, printed in printed_clock_not_captured(rows):
        flag("printed_clock_not_captured", e,
             f"{e.court} #{e.court_order} is printed {e.start_note!r}, which "
             f"states a clock ({printed!r}), but the row stored none — every "
             f"floor and estimate downstream reads start_time_local, so all of "
             f"them are silent on this row")

    # 2026-08-26, Winston-Salem: re-reading the same sheet through a fixed
    # parser gave two courts a second row each — the clean names beside the
    # unreadable ones, 14 rows for a 12-match sheet. `pairing_duplicated`
    # above cannot see it: it compares whole pairings and exempts unresolved
    # rows, and these rows were unresolved and disagreed on exactly the side
    # the parser had mangled. `_dedupe_day` could not either — `_resolves`
    # wants one row to be MORE decided than the other and both were equally
    # pending, and `_superseded` was written for withdrawals and skipped TBD
    # rows outright (both since fixed).
    #
    # The shape, stated once and for any kind of row: two slots on one day
    # naming the SAME side and sharing NOBODY on the other, where one was last
    # confirmed by an older revision and neither has been on court, are one
    # slot printed twice. Both guards are load-bearing — a team really can play
    # twice on a day (the US Open's mixed-doubles event does exactly that, and
    # a rain backlog does it by accident), but both of those rows come off the
    # SAME revision, and a match that dropped off a later revision because it
    # finished has a result on it.
    # 2026-08-26, Monterrey ESTADIO: the revised sheet moved Timofeeva's
    # walked-over R16 out of the time bands and printed it with no start
    # wording at all, above the column's first "Starting at". Everything above
    # the first marker was court-header furniture to the parser, so the sheet's
    # 8 slots came back as 7 — and NOTHING said so. The match stayed on the
    # page only because an earlier revision had created its row, still wearing
    # the 3:00 PM that revision printed; had the walkover been in the day's
    # first sheet the match would never have appeared at all.
    #
    # The tell is cheap and general: rows are restated by every revision, so a
    # row that the newest document of the day did NOT restate is a slot that
    # revision either dropped or the parse could not see. Measured over every
    # tournament-day in the database: six rows, three days — this one, a
    # Winston-Salem row whose player withdrew and whose replacement was printed
    # on a different DAY (so `_dedupe_day`, which is per-day, could never
    # absorb it), and four rows from the first Cincinnati sheet. No noise.
    # `_absorb` hands the newer document id to a merge's survivor so that
    # collapsing two rows cannot look like this.
    #
    # 2026-09-14, SP Open: reporting it is not enough when the row is
    # PROVABLY dead. The 2:05 PM revision moved the day's start to 3:30 PM and
    # dropped the doubles R16 off QUADRA CENTRAL; the row stayed, and the
    # estimate chain — which runs down a court in order — carried the phantom
    # forward into its neighbours' clocks, publishing "~7:15 PM" under a
    # printed "Not before 5:30 PM". `schedule._retire_pulled_slots` deletes
    # exactly the rows the sheet can be PROVEN to have pulled rather than
    # stopped listing because they were played: no trace of having been on
    # court, on a court whose first printed start on the new sheet was still
    # ahead when that sheet was published. This is that predicate, stated
    # again as law — with the law's OWN reading of the printed clock
    # (`_printed_instant`, the independent parse), so a zone or clock bug in
    # the service is a disagreement here rather than a shared blind spot.
    latest_doc = max((r.last_document_id or 0) for r in rows) if rows else 0
    # Hoisted out of the block below because the blank-sheet rule after it
    # asks the same question of the same rows. A singles row carries no result
    # of its own — it lives on `matches` — so "was this ever on court" is two
    # readings joined, and there must only be one of them.
    played_match = {}
    linked = [e.match_id for e in rows if e.match_id]
    if linked:
        from app.models.tournament import Match as _M
        played_match = {
            mid: bool(w or c or s or lj)
            for mid, w, c, s, lj in (await db.execute(
                select(_M.id, _M.winner_id, _M.completed_at,
                       _M.started_at, _M.live_scores_json)
                .where(_M.id.in_(linked)))).all()}

    def never_played(e) -> bool:
        return not (
            e.started_at or e.completed_at or e.winner_side
            or e.live_scores_json or e.scores_json or e.printed_score
            or e.printed_status or (e.status or "scheduled") != "scheduled"
            or played_match.get(e.match_id))

    if latest_doc:
        published = doc_fetched.get(latest_doc)
        # The new sheet's own account of when each court begins. Read from the
        # rows IT stamped: a stale row's printed time belongs to the revision
        # that has just been superseded.
        anchor: dict = {}
        for e in rows:
            if (e.last_document_id or 0) != latest_doc:
                continue
            when = _naive_utc(_printed_instant(e, venue_tz))
            if when and (e.court not in anchor or when < anchor[e.court]):
                anchor[e.court] = when
        # 2026-09-15, SP Open — THE PULL THE CLOCK CANNOT SEE. Rain stopped
        # play and the 5:58 PM reissue cut six unplayed R32 matches off
        # Tuesday; every court had begun at 10:30 AM, so the rule below held
        # its tongue, the grace window hid `slot_unconfirmed`, and the next
        # sheet belongs to Wednesday — this was CLEAN on a page printing
        # Lamens/Alves between Lys/Ce and Badosa and Osuigwe/Quevedo at
        # "~2:30 AM". The mid-session proof, in the law's own reading: a slot
        # bound to a bracket match with no trace of play, on a court where a
        # match this sheet still prints had started and not finished when the
        # sheet was published. Read off `started_at`/`completed_at`/
        # `winner_id` only — the service also reads the sofa_* pair, so a
        # disagreement between the two feeds surfaces here instead of being
        # shared.
        in_play: set = set()
        on_court = {e.match_id: e.court for e in rows
                    if (e.last_document_id or 0) == latest_doc and e.match_id}
        if on_court and published:
            from app.models.tournament import Match as _M
            for mid, began, done, won in (await db.execute(
                    select(_M.id, _M.started_at, _M.completed_at, _M.winner_id)
                    .where(_M.id.in_(list(on_court))))).all():
                began, done = _naive_utc(began), _naive_utc(done)
                if (began and began <= published
                        and (done > published if done else not won)):
                    in_play.add(on_court[mid])
        for e in rows:
            if (e.last_document_id or 0) >= latest_doc:
                continue
            court_at = anchor.get(e.court)
            if (never_played(e) and published and court_at
                    and court_at > published and venue_tz):
                flag("slot_pulled_not_retired", e,
                     f"document {latest_doc} dropped this slot and was "
                     f"published before {e.court} had played anything — it was "
                     f"pulled, and it is still chaining the clocks behind it")
            elif (never_played(e) and e.match_id and venue_tz
                  and e.court in in_play):
                flag("slot_pulled_mid_session_not_retired", e,
                     f"document {latest_doc} dropped this slot while {e.court} "
                     f"had a match in play and its bracket match was never "
                     f"started — it was pulled, not played, and it is still "
                     f"chaining the clocks behind it")
            elif revisions_since(doc_fetched, e.last_document_id) >= UNCONFIRMED_GRACE:
                # ONE REVISION OF SILENCE IS THE WINDOW, NOT A FAULT. A sheet
                # that stops printing a row has either pulled it — which
                # `_retire_pulled_slots` acts on at the NEXT ingest — or failed
                # to parse. SP Open's doubles R16 on 2026-09-14 was the first:
                # document 254 dropped it, this flagged an error, and document
                # 255 retired it thirteen minutes later, exactly as designed
                # (owner's /issues run, 2026-09-15). Alarming inside the window
                # a fix runs in reports the fix working.
                #
                # TWO of the DAY'S OWN revisions, counted from doc_fetched,
                # which is scoped to this tournament and date — document ids
                # are global, so their arithmetic counts other events' sheets.
                # Two means nothing retired it and nothing restated it: a row
                # the sheet has genuinely left behind.
                flag("slot_unconfirmed", e,
                     f"last confirmed by document {e.last_document_id}, and the "
                     f"day has published "
                     f"{revisions_since(doc_fetched, e.last_document_id)} "
                     f"revisions since (newest {latest_doc}) without printing "
                     f"this slot or retiring it")

    # 2026-09-14 (again), SP Open — THE DAY THE TOURNAMENT EMPTIED, and the
    # reason `latest_doc` above cannot be the whole law. It is read off the
    # ROWS, so a revision that stamped none of them is invisible to it: the
    # 4:55 PM sheet printed three court headers over three empty columns,
    # every row went on pointing at the 3:30 PM sheet, and this check returned
    # CLEAN on a day whose four remaining R32 matches had just been moved to
    # Tuesday's sheet, released fifteen minutes later. Nothing had been
    # played. The site had no revision left that could ever take them off,
    # because every later document belongs to another day.
    #
    # `printed_boxes` is what the SHEET printed, counted off its own lines
    # before `oop_parser` assigns a column or opens a slot, and it is the one
    # reading a broken parser cannot forge — a parse that LOST every slot
    # leaves printed_boxes above zero against match_count zero, which is
    # `check_parse`'s `vs_lines_exceed_matches` and emphatically not this.
    # NULL is a document written before the column existed, or a feed that
    # counts nothing off a sheet: unknown, and unknown never convicts.
    #
    # Everything after that is the law's own: `_printed_instant` for the
    # clock, and the same never-on-court reading every other rule here uses.
    blank_doc = max((d for d in day_docs
                     if (d.parse_status or "") == "oop"
                     and not (d.match_count or 0)
                     and d.printed_boxes == 0
                     and d.id > latest_doc),
                    key=lambda d: d.id, default=None)
    if blank_doc is not None and venue_tz:
        blank_published = doc_fetched.get(blank_doc.id)
        # No sheet prints these courts any more, so the last one that did is
        # the only published account of when each begins. The question it has
        # to answer is only whether the court could have been underway when
        # the blank sheet came out.
        anchor = {}
        for e in rows:
            when = _naive_utc(_printed_instant(e, venue_tz))
            if when and (e.court not in anchor or when < anchor[e.court]):
                anchor[e.court] = when
        for e in rows:
            court_at = anchor.get(e.court)
            if (never_played(e) and blank_published and court_at
                    and court_at > blank_published):
                flag("blank_sheet_slot_not_retired", e,
                     f"document {blank_doc.id} is a BLANK order of play — the "
                     f"sheet prints no match boxes at all — and was published "
                     f"before {e.court} had played anything, so the "
                     f"tournament emptied this day and the slot is still on "
                     f"the page")

    from app.services.schedule import _side_tokens
    _opp = {"a": "b", "b": "a"}
    fresh = [r for r in rows
             if not (r.started_at or r.completed_at or r.winner_side
                     or r.live_scores_json)]
    for i, a in enumerate(fresh):
        for b in fresh[i + 1:]:
            if a.stage != b.stage:
                continue
            if (a.last_document_id or 0) == (b.last_document_id or 0):
                continue
            A = {s: set().union(set(), *_side_tokens(a, s)) for s in "ab"}
            B = {s: set().union(set(), *_side_tokens(b, s)) for s in "ab"}
            hit = next((
                (sa, sb) for sa in "ab" for sb in "ab"
                if A[sa] and A[sa] == B[sb] and not (A[_opp[sa]] & B[_opp[sb]])), None)
            if hit:
                old, new = (a, b) if (a.last_document_id or 0) < (b.last_document_id or 0) else (b, a)
                flag("slot_restated", old,
                     f"entry {old.id} (document {old.last_document_id}) and entry "
                     f"{new.id} (document {new.last_document_id}) share side "
                     f"{hit[0]}/{hit[1]} and no player on the other — one slot, "
                     f"two rows")

    # 2026-09-12, SP Open qualifying: "Antonia VERGARA RIVERA" and "Martina
    # CAPURRO TABORDA" were served with no ranking, no Elo, no age and no
    # head-to-head link while the fourteen other names on the same sheet had
    # all four. Both women are in te_players under exactly the name the sheet
    # prints. What lost them was the SHORTLIST in routers/schedule — it asked
    # for `lower(last_name) IN {the key's last token}`, so every Tennis
    # Explorer surname of more than one word was unreachable before the
    # whole-name comparison ever ran. 45 of the 887 names ever stored here
    # were uniquely resolvable and silently unresolved.
    #
    # Stated as the law can state it: the fast path the API runs must resolve
    # every name an EXHAUSTIVE scan of te_players resolves. The check does the
    # expensive, obviously-correct thing (read every row, compare the whole
    # normalised name) and the request path does the fast thing; divergence is
    # the bug, whatever narrowing causes it next time. Qualifying and doubles
    # are where this bites, because those rows have no draw_entries row to
    # carry the link instead.
    from app.models.rankings import TePlayer as _TePlayer
    from app.routers.schedule import _name_key as _te_key, _slugs_by_name
    from app.services.rankings import _norm as _te_norm

    raws = [p.raw_name for e in rows for p in (e.players or []) if p.raw_name]
    if raws:
        served = await _slugs_by_name(db, raws)
        truth: dict = {}
        for slug, display in (await db.execute(
                select(_TePlayer.te_slug, _TePlayer.name_display)
                .where(_TePlayer.te_slug.isnot(None)))).all():
            k = _te_norm(display or "")
            if not k:
                continue
            # One name, two people, is a walk-away for the serve path too —
            # so it must not count as something the shortlist "missed".
            truth[k] = None if k in truth else slug
        for e in rows:
            for p in (e.players or []):
                k = _te_key(p.raw_name or "")
                want = truth.get(k) if k else None
                if want and not served.get(k):
                    flag("name_te_shortlist_missed", e,
                         f"side {p.side}: {p.raw_name!r} is te_players "
                         f"{want} by whole name, and the serve path's "
                         f"shortlist did not offer it")

    # 2026-09-13, Guadalajara: Sunday's Q2 slot "[ALT] Nadiia KICHENOK UKR vs
    # [5] Nao HIBINO JPN" was served COMPLETED with a final score of 6-4 6-1,
    # on a sheet released that same afternoon, for a match nobody had played.
    # The serve path carries a rained-off match's score from the day it
    # stopped onto the day it resumes, and it decides "the same match" from a
    # set of surnames read off the printed names — except it read the LAST
    # TOKEN, and the last token of an order-of-play name is the COUNTRY. Every
    # row's cross-day signature was therefore a set of NATIONALITIES, and
    # Saturday's "BIELINSKA UKR vs HIBINO JPN" signed {ukr, jpn} exactly as
    # Sunday's slot did. 18 of the 62 cross-day sibling pairs in the stored
    # corpus were wrong the same way, one of them a singles row inheriting a
    # DOUBLES score — four nationalities collapse to two inside a set.
    #
    # Stated over the serve path's OWN function, because the data is innocent:
    # two different matches sharing a pair of nationalities is ordinary, and
    # nothing about the stored rows is wrong. What must hold is that a
    # signature which MERGES two rows names the same people on both of them —
    # true of whatever the signature is computed from next time.
    #
    # The law reads the sheet's country its own way, by MEMBERSHIP of
    # COUNTRY_CODES; the serve path reads it by SHAPE, with a guard for the
    # surnames that share the shape (LUZ, POW, GUO). That disagreement is the
    # axis the bug lived on, so sharing the reading is exactly how this check
    # would go blind. See _printed_instant for the same principle.
    from app.routers.schedule import _pairing_surname

    def _law_fold(tok: str) -> str:
        nfd = _ud.normalize("NFD", tok)
        return "".join(c for c in nfd
                       if _ud.category(c) != "Mn").lower().replace("-", " ")

    def _law_surnames(entry) -> frozenset:
        """Surnames as the LAW reads them: strip the entry tags, strip every
        trailing token that IS a country, and keep the capitalised ones —
        the sheets shout the surname. A sheet that capitalises nothing (some
        smaller events) leaves the last token, which is then a name because
        the country is already gone."""
        out = set()
        for p in (entry.players or []):
            raw = _LEADING_SEED_RE.sub(
                "", _TRAILING_SEED_RE.sub("", (p.raw_name or "").strip()))
            toks = raw.split()
            while len(toks) >= 2 and toks[-1] in COUNTRY_CODES:
                toks = toks[:-1]
            caps = [t for t in toks
                    if t.isupper() and len(_ALPHA_RE.sub("", t)) >= 2]
            pick = caps or toks[-1:]
            if pick:
                out.add(_law_fold(" ".join(pick)))
        return frozenset(out)

    def _carry_sig(entry) -> frozenset:
        return frozenset(_pairing_surname(p.raw_name or "")
                         for p in (entry.players or [])
                         if (p.raw_name or "").strip())

    neighbours = (await db.execute(
        select(ScheduleEntry).where(
            ScheduleEntry.tournament_id == tournament_id,
            ScheduleEntry.play_date >= _pd - _td(days=1),
            ScheduleEntry.play_date <= _pd + _td(days=1),
            ScheduleEntry.play_date != _pd,
        ).execution_options(populate_existing=True))).scalars().all()
    if neighbours:
        n_sig = [(o, _carry_sig(o), _law_surnames(o)) for o in neighbours]
        for e in rows:
            if not (e.players or []):
                continue
            sig, mine = _carry_sig(e), _law_surnames(e)
            for other, o_sig, theirs in n_sig:
                if sig == o_sig and mine != theirs:
                    flag("carry_signature_collides", e,
                         f"the cross-day carry signs this row the same as "
                         f"entry {other.id} on {other.play_date} "
                         f"({sorted(sig)}), but they name different people: "
                         f"{sorted(mine)} vs {sorted(theirs)} — one match's "
                         f"score can be published on the other's slot")
                    break

    # 2026-09-15, SP Open: rain stopped three R32 matches just after 18:00 UTC
    # and Sofascore took the "interrupted" events off its live list. The
    # singles poller read the absence as the end of the match and, after
    # GONE_AFTER, emptied both live columns: Brace/Sierra (4-4) showed no score
    # at all, You/Charaeva kept only Wikipedia's first set, and none of the
    # three said Suspended — for hours, under a sheet printing "44* TBF". A
    # match SEEN IN PLAY, with no result and no live state anywhere, reads on
    # the page as a match that never began. Judged off the score history,
    # which only the feeds write and nothing clears, rather than off the live
    # columns the defect empties. The grace covers the gap between a match
    # ending and its result landing (GONE_AFTER plus a results sweep).
    singles_linked = {e.match_id: e for e in rows
                      if e.match_id and e.discipline == "singles"}
    if singles_linked:
        from datetime import datetime as _datetime
        from app.models.score_history import MatchScoreSnapshot as _Snap
        _now = _naive_utc(_datetime.now(_tz.utc))
        for m in (await db.execute(
                select(Match).where(Match.id.in_(list(singles_linked)),
                                    Match.winner_id.is_(None)))).scalars().all():
            if m.live_scores_json or m.sofa_live_json:
                continue
            last = (await db.execute(
                select(_Snap).where(_Snap.match_id == m.id)
                .order_by(_Snap.at.desc()).limit(1))).scalars().first()
            sets = ((last.snap or {}).get("sets") or []) if last else []
            games = sum(int(g or 0) for s in sets for g in (s or [])[:2]
                        if str(g or 0).isdigit())
            if not games or _now - _naive_utc(last.at) < _td(minutes=20):
                continue
            flag("started_match_live_state_lost", singles_linked[m.id],
                 f"match {m.id} was last seen in play at {sets} "
                 f"({_naive_utc(last.at):%H:%M} UTC), has no result, and holds "
                 f"no live score — the page shows it as never begun")

    # 2026-09-16, SP Open doc 267: Tuesday's rain carried three R32 matches
    # into Wednesday, and the sheet printed "Not before 2:00 PM" against each.
    # They were the only three rows on the day with NO TIME ON THEM AT ALL —
    # the one thing a resumption exists to tell a reader. The fault was in the
    # web, not the data: Schedule.jsx read `live_scores[4] === 'suspended'` —
    # a flag frozen the night play stopped, and permanently true of a carried
    # match — as "on court right now", and hid the time line its own comment
    # said these rows must keep. `mobile/schedule.js` had already gated its
    # copy on the server's status; the web was the copy that never got it.
    #
    # The law cannot read JSX, so the rule itself is pinned by
    # `node frontend/src/utils/playState.test.mjs` and this pins what that rule
    # has to print: a row the serve path will call "to be completed" must carry
    # an expected start that lands on THIS day at the venue. Without one even a
    # correct page has nothing to say — and an estimate that drifts off the day
    # entirely is the "~2:30 AM" damage of 2026-09-15 wearing another hat.
    #
    # The carried shape is read the serve path's way (routers/schedule.py):
    # play began on an EARLIER day and there is still no result. Singles keeps
    # that on `matches`, doubles and qualifying on the row itself, so both are
    # asked. A match that began today and is merely suspended is still on
    # court and is not this.
    if venue_tz:
        from zoneinfo import ZoneInfo as _ZI
        try:
            _vtz = _ZI(venue_tz)
        except Exception:
            _vtz = None
        started_before: dict = {}
        if linked:
            from app.models.tournament import Match as _M2
            started_before = {
                mid: (st, win)
                for mid, st, win in (await db.execute(
                    select(_M2.id, _M2.started_at, _M2.winner_id)
                    .where(_M2.id.in_(linked)))).all()}

        def _venue_date(dt):
            if dt is None or _vtz is None:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz.utc)
            return dt.astimezone(_vtz).date()

        if _vtz is not None:
            for e in rows:
                # A result anywhere ends it: singles carry theirs on `matches`,
                # doubles and qualifying on the row. Asked of both, always —
                # reading only the source that supplied `began` is how a
                # finished match keeps being called a resumption.
                began, settled = None, (e.winner_side is not None
                                        or e.completed_at is not None)
                if e.match_id and e.match_id in started_before:
                    m_started, m_winner = started_before[e.match_id]
                    began = m_started
                    settled = settled or m_winner is not None
                if began is None:
                    began = e.started_at
                began_on = _venue_date(began)
                if began_on is None or began_on >= _pd or settled:
                    continue
                on_day = _venue_date(e.expected_start_at)
                if on_day == _pd:
                    continue
                flag("carried_slot_has_no_time", e,
                     f"carried from {began_on} with no result, but "
                     + (f"expected_start_at lands on {on_day}"
                        if on_day else "no expected_start_at")
                     + " — the page can print nothing for a resumption"
                     + f" the sheet slots at {e.start_note or e.start_type!r}")

    # 2026-09-17, Guadalajara doc 274: the doubles SF was printed "Time TBA -
    # After suitable rest", alone on CANCHA with that court's first band left
    # empty — no clock, and nothing ahead of it to chain an estimate from.
    # The ROW was right (the time genuinely is unknown); the ORDER was not.
    # SQLite sorts NULL first, so the day endpoint served it as the day's
    # opener, and both clients' Time views keyed it on '' and listed it above
    # the 1:00 PM first match that the sheet's layout and its "after rest" put
    # it behind. The defect is in code, so this runs the SERVE path's own
    # ordering (routers/schedule.day_order) over the stored day, the way
    # carry_signature_collides runs its signature. The clients' copies of the
    # rule are pinned by frontend/src/utils/dayOrder.test.mjs and
    # mobile/schedule.test.mjs.
    from app.routers.schedule import day_order as _day_order
    by_id = {e.id: e for e in rows}
    untimed = None
    for rid, exp in (await db.execute(
            select(ScheduleEntry.id, ScheduleEntry.expected_start_at).where(
                ScheduleEntry.tournament_id == tournament_id,
                ScheduleEntry.play_date == play_date,
            ).order_by(*_day_order()))).all():
        if exp is None:
            untimed = untimed or rid
        elif untimed is not None:
            flag("untimed_slot_served_first", by_id.get(untimed),
                 f"entry {untimed} has no expected start but is served ahead "
                 f"of entry {rid} ({exp:%H:%M} UTC) — the page lists a slot "
                 f"nobody can time as earlier than a timed one")
            break

    # 2026-09-18, SP Open doc 289 — see player_on_two_courts.
    for a, b, name in player_on_two_courts(rows):
        flag("player_on_two_courts", b,
             f"{name!r} is booked on {a.court!r} (entry {a.id}, "
             f"{_naive_utc(a.expected_start_at):%H:%M} UTC, "
             f"{a.estimated_duration_min} min) and on {b.court!r} (entry "
             f"{b.id}, {_naive_utc(b.expected_start_at):%H:%M} UTC) at once")

    return v


def check_parse(meta, match_count: int | None = None,
                rounds: list | None = None) -> list[dict]:
    """The law applied to a PARSE, before a single row is stored.

    Everything in check_day looks at rows the ingest wrote. That is blind to
    the worst thing a parser can do, which is to write nothing: a slot the
    sheet prints and the parse throws away leaves NO row to violate any rule,
    and the day is simply one match short of the sheet with no error anywhere.

    2026-08-26, Winston-Salem Court 3: the third slot's four lines were all
    doubles pairs printed the way the ATP prints them — "ARRIBAGE (FRA) /
    GUINARD (FRA)" — surname only, so `_is_name`'s all-caps exemption (which
    wants two name-shaped tokens before the country) rejected every one of
    them as the sheet's own furniture. The slot flushed empty, the site
    published 11 matches for a 12-match sheet, and the only way anyone would
    ever have known was by holding the PDF beside the page.

    `oop_parser` now hands back every slot a marker opened that it could not
    fill AND that swallowed words it could not read. Measured over the
    285-file corpus: zero. An alarm this quiet is one worth believing.
    """
    out: list[dict] = []
    for m in (meta or {}).get('dropped_slots') or []:
        out.append({
            "code": "slot_dropped", "entry_id": None,
            "court": getattr(m, 'court', None),
            "detail": f"{getattr(m, 'court', '') or '?'} "
                      f"{getattr(m, 'start_raw', '') or '?'}: slot opened but no "
                      f"players parsed; unread lines: "
                      + "; ".join(repr(x) for x in (m.rejected or [])[:4]),
        })

    # COUNT THE SHEET'S OWN "vs", not the parser's opinion of it.
    #
    # `slot_dropped` above only sees a slot a MARKER opened — so it was blind
    # to Monterrey 2026-08-26, where the walkover box had no marker at all and
    # the whole match evaporated between the sheet and the site (8 printed, 7
    # parsed, nothing logged). A standalone "vs" is the one line only a match
    # box produces: a page title, a date, a court name and a footer cannot,
    # and every box in the corpus prints exactly one. So the sheet states its
    # own match count, independently of every rule in the parser, and a parse
    # that comes back with fewer has lost a slot HOWEVER it lost it.
    #
    # One-sided on purpose: some sheets print "A vs B" inline on a single line
    # and those are not counted, so fewer "vs" than matches is ordinary.
    # Measured over the 285-file corpus, more "vs" than matches happens in
    # exactly two files — this incident, and a 2025 Eastbourne finals sheet
    # whose two courts print on one line and are being merged into one match.
    # An alarm that quiet is one worth believing.
    vs_lines = (meta or {}).get('vs_lines')
    if vs_lines is not None and match_count is not None and vs_lines > match_count:
        out.append({
            "code": "vs_lines_exceed_matches", "entry_id": None, "court": None,
            "detail": f"the sheet prints {vs_lines} match boxes ('vs' on its own "
                      f"line) but the parse produced {match_count} — "
                      f"{vs_lines - match_count} slot(s) lost",
        })

    # 2026-08-29, Winston-Salem's finals sheet: the page printed "DOUBLES
    # FINAL" over one box and "SINGLES FINAL" over the other, and NOISE_RE ate
    # both — it exists to stop a header becoming a player, and nothing read one
    # first. The singles row took its "F" off the bracket and looked fine; the
    # doubles row has no bracket to fall back on (we store no doubles draw) and
    # published with no round at all, beside a sheet that states one.
    #
    # Counted off the sheet's own lines in parse_pdf, independently of every
    # rule that reads them — the same construction as vs_lines above, and quiet
    # for the same reason: it fires only when the sheet printed a header and
    # NOT ONE match came back wearing a round, which is the reading being
    # broken rather than a sheet that labels some of its slots and not others.
    # Measured over the 285-file corpus: zero.
    headers = (meta or {}).get('round_headers')
    if headers and rounds is not None and not any(rounds):
        out.append({
            "code": "printed_round_dropped", "entry_id": None, "court": None,
            "detail": f"the sheet prints {headers} event header(s) stating a "
                      f"round and the parse kept none — see _EVENT_HEADER_RE",
        })
    return out


# NOT EVERY CODE CAN BE JUDGED AT INGEST TIME. `expected_contradicts_printed`
# compares expected_start_at against the sheet's printed time — and the ingest
# does not write expected_start_at. Its callers recompute the estimates in the
# very next statement, under the same day_write_lock, so at the moment the law
# runs after an ingest the row still holds the PREVIOUS estimate against the
# NEW printed time. That is a half-finished pipeline, not a bug: on 2026-09-04
# Court 12 was reported as "printed 5:30 PM but expected 2:30 PM" and was
# already correct by the time anyone looked. The SWEEP still checks this code,
# on settled state, so a real contradiction is still caught — just not blamed
# on the ingest that was about to fix it. Same lesson as the two-transaction
# window the sweep itself had to learn.
# `expected_undercuts_printed_floor` and `player_on_two_courts` read the same
# half-written estimate.
INGEST_DEFERRED = frozenset({"expected_contradicts_printed",
                             "expected_undercuts_printed_floor",
                             "player_on_two_courts"})


async def check_and_log(db, tournament, play_date, *,
                        skip: frozenset = frozenset()) -> list[dict]:
    """Run the law and put violations where the alert digest reads.

    `skip` drops codes this caller cannot fairly judge yet (see
    INGEST_DEFERRED); they are still checked by the sweep.
    """
    from app.services.system_log import app_log

    violations = [v for v in await check_day(db, tournament.id, play_date)
                  if v.get("code") not in skip]
    if violations:
        await app_log(
            "error", "order_of_play",
            f"{len(violations)} schedule invariant violation(s) in "
            f"{tournament.name} on {play_date}: "
            + "; ".join(f"{x['code']} ({x['detail'][:60]})" for x in violations[:5]),
            {"tournament_id": tournament.id, "play_date": str(play_date),
             "violations": violations[:20]},
            dedup_key=f"sched_invariants_{tournament.id}_{play_date}",
            dedup_hours=6)
    return violations


async def sweep(db) -> int:
    """The law applied to every tournament-day near now.

    Entries keep changing AFTER ingest — dedupe absorbs rows, alternatives
    resolve to winners, courts renumber — so checking only at ingest time
    would miss a violation those passes introduce. Returns total violations.
    """
    from datetime import date, timedelta

    from app.models.tournament import Tournament

    today = date.today()
    days = [today - timedelta(days=1), today, today + timedelta(days=1)]
    pairs = (await db.execute(
        select(ScheduleEntry.tournament_id, ScheduleEntry.play_date)
        .where(ScheduleEntry.play_date.in_(days)).distinct())).all()
    total = 0
    for tid, day in pairs:
        t = await db.get(Tournament, tid)
        if t is None:
            continue
        total += len(await check_and_log(db, t, day))
    return total


if __name__ == "__main__":  # pragma: no cover
    # `python -m app.services.schedule_invariants [tournament_id play_date]`
    # — the verifier's first move, and the runner's gate under its verdict.
    # Prints one JSON line; exit code 1 when violations exist.
    import asyncio
    import json as _json
    import sys

    async def _main():
        from app.database import AsyncSessionLocal
        from app.models.tournament import Tournament

        # The registry main.py builds, rebuilt for a process that never
        # imported main. `name_te_shortlist_missed` runs the SERVE path's
        # resolver, which touches the TePlayer mapper — and configuring one
        # mapper configures them all, so a half-registered registry raises
        # "expression 'League' failed to locate a name" and takes the whole
        # CLI down with it. The verifier's first move and the runner's gate
        # are both this CLI; it cannot depend on who imported what.
        import importlib
        for _m in ("user", "passkey", "prediction", "league", "tournament",
                   "rankings", "h2h", "system_log"):
            importlib.import_module(f"app.models.{_m}")

        async with AsyncSessionLocal() as db:
            if len(sys.argv) >= 3:
                t = await db.get(Tournament, int(sys.argv[1]))
                out = await check_day(db, int(sys.argv[1]), sys.argv[2]) if t else []
            else:
                n = await sweep(db)
                out = [{"code": "sweep_total", "detail": str(n)}] if n else []
        print(_json.dumps(out))
        sys.exit(1 if out else 0)

    asyncio.run(_main())
