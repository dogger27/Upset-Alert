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
from datetime import datetime as _datetime, timedelta as _timedelta, timezone as _tz

from sqlalchemy import select

from app.models.schedule import ScheduleDocument, ScheduleEntry
from app.services.oop_parser import COUNTRY_CODES, served_nation


# How many of the DAY'S OWN revisions have come and gone without restating a
# slot before it counts as abandoned. One is the window between a sheet
# dropping a row and `_retire_pulled_slots` acting on it at the next ingest,
# which is a fix in progress, not a fault.
UNCONFIRMED_GRACE = 2

# Stands in for a row with NO printed clock ("Followed by", "TBA") wherever a
# rule compares one. Always earlier than any real instant, so a row that never
# said when it starts can never satisfy a rule that needs it to be late enough
# — silence must not convict.
_FAR_PAST = _datetime.min


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
# Russian and Belarusian players are neutral athletes: no sheet in 348 prints
# either code. See `withheld_nation_served`.
_WITHHELD_NATIONS = frozenset({"RUS", "BLR"})
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
# THE WORDS A SHEET PRINTS ABOUT ITSELF — the heading over a block of boxes,
# as opposed to the roles above, which stand where a PERSON would.
#
# Korea's 2026-09-24 sheet (doc 465) printed "Doubles" on a line of its own in
# each court's column: the heading over a doubles section whose draw was not
# made yet, with nothing under it. Every header reader in oop_parser wanted a
# ROUND word after the discipline, so the word was stored as a PLAYER —
# Ostapenko's R16 SINGLES published as a doubles match against "Taylah PRESTON
# AUS / Doubles", Bondar's the same on the other court, and both rows lost the
# bracket match a singles row is linked by. Fixed in the parser
# (oop_parser._BARE_EVENT_RE, da786379); this is the law that says it can
# never be data again, whatever reads a sheet next.
#
# CASE-BLIND, which is exactly where it disagrees with `name_not_sheet_form`,
# the check that happened to convict the incident. That one asks a name for a
# capitalised run, and "DOUBLES" — the spelling the sheets shout their headings
# in — HAS one, so the all-caps heading walks straight past it; on a doubles
# row `doubles_side_not_two` then counts two names and passes as well. A
# heading is not a person in any casing.
_EVENT_WORD_RE = re.compile(
    r"^(?:men'?s|women'?s|ladies'?|gentlemen'?s|boys'?|girls'?|"
    r"singles|doubles|mixed|qualifying|qualification|main|draw|"
    r"ATP|WTA|ITF)$", re.I)
# The half of that vocabulary that can only be an event, tested ANYWHERE in a
# name rather than as the whole of it — the reach `name_holds_slot_wording`
# has, and for the same reason: the sheet's own word joins a name by being
# GLUED to it as often as by standing alone. "Main", "Draw" and the tour codes
# are deliberately absent here — they are ordinary words and three-letter
# surnames, and only the whole-line reading above may judge them.
_EVENT_DISCIPLINE_RE = re.compile(
    r'(?<![A-Za-z])(?:singles|doubles|mixed|qualifying|qualification)'
    r'(?![A-Za-z])', re.I)
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
# A GENERATIONAL SUFFIX, as the LAW reads one. Stated here and not imported
# from `sofascore_doubles.strip_gen_suffix` for the reason `_person_words` and
# `_INITIAL_RE` are: a copy the service owns would go blind with it, and this
# law exists to catch the day the service's identity fails. "Martin Damm Jr"
# has no capitals at all off the ATP feed, so every last-token reading of a
# surname took "Jr" for one (Chengdu 2026-09-23).
_GEN_SUFFIX_RE = re.compile(r'^(?:jn?r|sn?r|ii|iii|iv)\.?$', re.I)


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


def _names_the_event(raw: str) -> bool:
    """Is this stored player row the sheet's own HEADING rather than a person?

    Two readings, either of which convicts, because the sheet's word reaches a
    name two ways: standing alone in the column, and glued to the name above
    it. Neither strips a country — a heading carries none, and a name that
    holds a discipline word is wrong however it ends.

    Measured over every name the system holds: 0 of 2,656 stored player rows
    and 0 of 4,482 draw entries, against the two Korea rows it was written for.
    """
    s = _LEADING_SEED_RE.sub("", _TRAILING_SEED_RE.sub("", (raw or "").strip()))
    if _EVENT_DISCIPLINE_RE.search(s):
        return True
    toks = [t for t in re.split(r'[\s/]+', s) if t]
    return bool(toks) and all(_EVENT_WORD_RE.match(t) for t in toks)


def _person_words(raw: str) -> set:
    """The WORDS of a printed name that name a person, under both spellings
    of a hyphen — the law's own reading of who a slot is about.

    "[5] Ye-Xin MA CHN" and "Yexin Ma" are one player; the seeding, the entry
    mark and the country are the sheet's furniture around her, and an initial
    stands in for a name without being one. A HYPHEN IS TWO SPELLINGS
    (rankings._match_token_set, history.tml.name_keys): the tours hyphenate a
    romanised Chinese or Korean given name where Sofascore and Tennis Explorer
    join it, so BOTH are carried and whichever the other row prints will meet
    one of them.

    Written here rather than borrowed from `schedule._name_tokens`, for the
    reason `_INITIAL_RE` is: a copy the service owns would go blind with it,
    and this law exists to catch the day the service's identity fails.
    """
    from app.services.rankings import _norm as _name_norm
    s = _LEADING_SEED_RE.sub("", _TRAILING_SEED_RE.sub("", (raw or "").strip()))
    m = _TRAILING_CODE_RE.search(s)
    if m and m.group(1) in COUNTRY_CODES:
        s = s[:m.start()].strip()
    out = set()
    for spelling in {s, s.replace("-", "")}:
        # A team reaches us as one string ("S. Aoyama / E. Liang"); both of
        # its people belong to the side that printed it.
        for t in _name_norm(spelling.replace("/", " ")).split():
            if _WORDY_RE.match(t):
                out.add(t)
    return out


def _sides_agree(x: set, y: set) -> bool:
    """Two printings of one side: equal, or one a subset of the other.

    The subset is `schedule._same_pairing`'s, for its reason — one revision
    abbreviates what another spells out, and a corrected parser makes a side
    GAIN a player. The same team cannot meet the same opponents twice in a
    day, which is what makes equality conclusive and the subset safe.
    """
    return bool(x and y) and (x == y or x < y or y < x)


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
    # An ESTIMATE is not a printed clock, and every law that reads one is about
    # what the tour printed (2026-09-18): a feed's guess moves when a court is
    # re-staggered, which is not a contradiction to report.
    if getattr(entry, "start_type", None) == "estimated":
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


_LAW_WALKOVER_RE = re.compile(r'^\s*w\s*/?\s*o\.?\s*$', re.I)


# THE LAW'S OWN READING of "the sheet has declared this match over", written
# apart from `oop_parser.printed_score_final` on purpose: an alarm that shares
# its reader's blind spot is not an alarm (Chengdu doc 408 — `round_headers`
# was counted with the very regex that could not see the header). This one
# finds the sets by SEARCHING the line and then proves it has accounted for
# every character of it; the parser's walks the line token by token. They agree
# on all 43 printed scores in the stored corpus and can disagree on the next
# form a sheet invents, which is the point.
_LAW_SCORE_ENDS_RE = re.compile(r'\b(?:RET|W\s*/?\s*O|DEF|CONC)\b', re.I)
_LAW_SCORE_OPEN_RE = re.compile(r'\b(?:TBF|ABD)\b', re.I)
_LAW_SCORE_FURNITURE_RE = re.compile(r'\b(?:F|SF|QF|ATP|WTA)\b', re.I)
_LAW_SCORE_SET_RE = re.compile(r'(\d{1,2})[-\u2013](\d{1,2})(?:\(\d+\))?')


def _sheet_declared_finished(entry) -> bool:
    """Did the tournament print this slot's match as FINISHED?

    A sheet prints its score where "vs" would go, and the same cell holds a
    mid-match snapshot ("62 *42 TBF") and a final result ("7-6(3) 6-1"). Only
    the second may be acted on, so anything this reading cannot account for
    character by character is False.
    """
    text = str(getattr(entry, "printed_score", None) or "").strip()
    if not text or _LAW_SCORE_OPEN_RE.search(text):
        return False
    if _LAW_SCORE_ENDS_RE.search(text):
        return True
    pairs = _LAW_SCORE_SET_RE.findall(text)
    if not pairs:
        return False
    rest = _LAW_SCORE_FURNITURE_RE.sub('', _LAW_SCORE_SET_RE.sub('', text))
    if rest.strip(' ,;.'):
        # A form this reading does not know — the compact "62", a server
        # asterisk. Not a finished match as far as the law is concerned.
        return False
    won = [0, 0]
    for a, b in pairs:
        a, b = int(a), int(b)
        hi, lo = max(a, b), min(a, b)
        if not ((hi >= 6 and hi - lo >= 2) or (hi == 7 and lo >= 5)):
            return False
        won[0 if a > b else 1] += 1
    return max(won) >= 2 and won[0] != won[1]


def _walked_over(entry) -> bool:
    """Did this slot's match end in a walkover? The law's own reading, apart
    from schedule._played: a result cell or a printed score that is "w/o"."""
    if _LAW_WALKOVER_RE.match(str(getattr(entry, "printed_score", None) or "")):
        return True
    return _scores_walked_over(getattr(entry, "scores_json", None))


def _scores_walked_over(scores) -> bool:
    """A result cell that reads "w/o" — on a row, or on its bracket match."""
    for side in (scores if isinstance(scores, (list, tuple)) else []):
        for cell in (side if isinstance(side, (list, tuple)) else [side]):
            if _LAW_WALKOVER_RE.match(str(cell or "")):
                return True
    return False


def clock_runs_backwards(rows, tz_name, walked_over=_walked_over) -> list[tuple]:
    """(row, the row above it) wherever a court's printed clock goes BACK in time.

    Down one court, in `court_order`, each printed clock is at or after every
    clock printed above it — that is what an order of play is. A clock earlier
    than one above it was read in the wrong half of the day: SP Open
    2026-09-17 stored "NB 2:30" as 2:30 AM under "Not before 1:00 PM". Read
    through the law's own `_printed_instant`, so it does not share the
    parser's `settle_meridiems`. Measured over every stored court-day when it
    was written (278): those two rows and nothing else.

    A WALKOVER HAS NO PLACE IN THAT ORDER. It never occupied the court, so the
    chain frees the court from whatever came before it (schedule._played), and
    its clock is not a time anything on the court ran to: whatever wrote it —
    the sheet before the w/o, or the WTA feed stamping the moment the result
    was ENTERED — it neither convicts nor is convicted. SP Open 2026-09-18:
    Dabrowski/Stefani's doubles QF went w/o, the feed stamped it 12:48, and it
    sat as QUADRA 1 #2 under the 2:00 PM opener, reported on every sweep.

    A SINGLES WALKOVER IS WRITTEN ON THE BRACKET, not on the row: a main-draw
    singles row carries no result of its own (see `_row_played`), so
    `check_day` passes a `walked_over` that reads the linked match too.
    Singapore 2026-09-23: Mertens v Krejcikova went w/o, match 5437 said
    `[["w/o"], [""]]`, the row said nothing. The feed rightly dropped its
    stamp, the row kept the sheet's "Not before 2:30 PM", sorted untimed-last
    under the court's 19:56 finale, and the row-only reading convicted it.
    """
    courts: dict = {}
    for r in rows:
        if r.court and not walked_over(r):
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


_LAW_ROUND_RE = re.compile(r'^(?:R(\d+)|(\d)R)$', re.I)


def _law_round_number(label, num_rounds) -> int | None:
    """The bracket round a label names, or None when it names none the law
    can check. F / SF / QF count back from the final. "R2" and "2R" are a
    round NUMBER (the sheets and the WTA feed); "R16" and up a FIELD SIZE
    (the bracket's own labels) — no draw has 8 rounds, and no field of 8 is
    called anything but QF, so the two never collide."""
    lab = (label or "").strip().upper()
    if not lab or not num_rounds:
        return None
    back = {"F": 0, "SF": 1, "QF": 2}.get(lab)
    if back is not None:
        return num_rounds - back
    m = _LAW_ROUND_RE.match(lab)
    if not m:
        return None
    k = int(m.group(1) or m.group(2))
    if k < 8:
        return k
    if k & (k - 1) == 0:
        return num_rounds - (k.bit_length() - 1) + 1
    return None


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

    A RECLAIM is the same re-read without the marker. When the sheet takes a
    day back from the WTA feed (schedule.ingest_document, `superseded`) it
    stores bytes it already holds, under the SAME sha — so a sha seen earlier
    in the day keeps the clock of the first fetch that brought it.
    """
    out: dict = {}
    carried = None
    first_seen: dict = {}
    for d in sorted(day_docs, key=lambda x: x.id):
        when = _naive_utc(d.fetched_at)
        if carried is not None:
            when, carried = carried, None
        sha = str(d.sha256 or '')
        if sha.startswith('forced'):
            carried = when
        elif sha:
            when = first_seen.setdefault(sha, when)
        out[d.id] = when
    return out


def publication_clocks(day_docs) -> dict:
    """-> {document id: the latest moment its bytes can have been written}.

    `document_clocks`, tightened by the server's Last-Modified where the
    fetch recorded one — which is what `pending_side_decided_before_document`
    asks: could this sheet have known the result?

    `fetched_at` answered that only while the PDF was polled every quarter
    hour. Since the feeds took the schedule (2026-09-18) it is fetched when a
    feed DECLINES a day, and the first such fetch can come hours after the
    sheet was published. Korea's Sunday sheet (2026-09-20) was released at
    08:45:18 UTC, printed "M. Kuramochi OR B. Jeong" honestly, since that Q1
    finished at 08:50; fetched an hour later, the law convicted it of losing
    a rendering it never carried. Last-Modified is the file's own mtime, so
    unlike the printed RELEASED stamp it moves when a sheet is amended in
    place. Not used for the pull laws: those mirror `_retire_pulled_slots`,
    which reads `fetched_at`, and a law on a different clock from the pass
    it checks convicts the pass for disagreeing.
    """
    from email.utils import parsedate_to_datetime
    out = document_clocks(day_docs)
    for d in day_docs:
        try:
            lm = _naive_utc(parsedate_to_datetime(d.http_last_modified))
        except (TypeError, ValueError, AttributeError):
            continue
        if lm is not None and (out.get(d.id) is None or lm < out[d.id]):
            out[d.id] = lm
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


def singles_stage_contradicts_round(rows) -> list:
    """Singles rows whose round belongs to the other draw from their stage.

    2026-09-23, Hangzhou (doc 421): Court view listed COURT 1 (qualifying
    finals only) above CENTER COURT, which the sheet prints first and which
    carried the day's two unseeded main-draw R32s. Courts are ranked by STAGE
    before seed now — a main-draw match outranks every qualifying seed (web
    utils/courtRank.js, mobile courtGroups.js; pinned by courtRank.test.mjs and
    courtGroups.test.mjs) — so the order of a day's courts is only as right as
    each row's stage. A singles row whose round names the other draw would
    wear the wrong badge AND lift a qualifying court over the show court, or
    sink the show court beneath one. Stored at the time: 0 of 822 singles rows.
    """
    out = []
    for r in rows:
        lab = (r.round_label or "").strip()
        if r.discipline != "singles" or not lab:
            continue
        if bool(_QUALI_ROUND_RE.match(lab)) != (r.stage == "qualifying"):
            out.append(r)
    return out


def round_unlabelled_beside_labelled(rows) -> list:
    """Rows with no round on a day whose other rows of the same event have one.

    2026-09-25, Hangzhou (doc 525): the ATP sheet prints no round, so every
    row takes its round from the feed that declined the day, matched on the
    pair of surnames. Sofascore wrote two doubles players "Rojer J-J" and
    "Zhang Zhi" — surname-first, as in every "/" team, but with a given name
    longer than the one letter sofa_schedule._surname_last recognised — so
    their surnames read "j-j" and "zhi", two rows matched nothing, and the page
    showed nine R16 chips and two blanks. Whatever named the siblings could
    name these; a blank beside them is a key that failed to join, not a round
    nobody knows. Judged per (stage, discipline): a qualifying day beside an
    unlabelled main-draw one says nothing. An unresolved slot (is_tbd) is not
    judged: one side is unknown, so there is no pair to join on, and a doubles
    TBD has no bracket for _fill_tbd_rounds to read either. Stored at the
    time: these two rows, and one doubles TBD, across 80 tournament-days.
    """
    labelled = {(r.stage, r.discipline) for r in rows
                if (r.round_label or "").strip()}
    return [r for r in rows
            if not (r.round_label or "").strip() and not r.is_tbd
            and (r.stage, r.discipline) in labelled]


def court_unnamed(rows) -> list:
    """Rows stored with no court at all.

    Every order of play prints a court over every box, so a blank court is a
    source that did not say where the match is. Singapore and Korea
    2026-09-19 (feed documents 306/307): the WTA's published shape names its
    court in `CourtName`, the reader looked only at `CourtID`, and sixteen
    qualifying matches went on the page under no heading.
    """
    return [r for r in rows if not (r.court or "").strip()]


def court_opened_twice(rows) -> list[tuple]:
    """(row, other) pairs printed to START at the same clock on the same court.

    A court begins one match at a time. Two fixed starts at one clock on one
    court are two courts read as one — the same Singapore/Korea day, where
    CENTER COURT's and COURT 1's "Starting at 11:00 AM" openers both landed on
    the one blank court. Independent of the court's name, so it also holds
    when two named courts are mapped onto one.
    """
    seen: dict = {}
    out = []
    for r in sorted(rows, key=lambda r: (r.court_order is None, r.court_order or 0, r.id)):
        if r.start_type != "fixed" or not r.start_time_local:
            continue
        k = (r.court or "", r.start_time_local)
        if k in seen:
            out.append((r, seen[k]))
        else:
            seen[k] = r
    return out


def court_spelled_two_ways(rows) -> list[tuple]:
    """(row, other spelling) for rows whose court is another court's name
    spelled differently — case and spacing only.

    Hangzhou 2026-09-23 (doc 418): a merge kept the Sofascore feed's "Court 1"
    on a row the sheet prints on "COURT 1", and the page grouped by the stored
    string — one court shown twice, its opener on one card and its second
    match opening the other with no clock. Rows on the less common spelling
    are reported (ties: the later-sorting one), so the court most of the day
    agrees on is the one named as right.
    """
    groups: dict = {}
    for r in rows:
        name = r.court or ""
        groups.setdefault(" ".join(name.split()).casefold(), {}).setdefault(name, []).append(r)
    out = []
    for spellings in groups.values():
        if len(spellings) < 2:
            continue
        ranked = sorted(spellings, key=lambda n: (-len(spellings[n]), n))
        for name in ranked[1:]:
            out += [(r, ranked[0]) for r in spellings[name]]
    return out


def sheet_row_placed_by_feed(rows, feed_docs) -> list:
    """Rows a SHEET document restated that still carry a feed's own start.

    "Est. 12:00" (`start_type` 'estimated') is a wording only a feed writes —
    Sofascore's staggered guess, the WTA's isEstimatedStartTime. A row whose
    newest document is a sheet and whose start is still the feed's was
    restated by the sheet without taking the sheet's placement: the doc-418
    merge (see `court_spelled_two_ways`), which `_prefer_challenger` settled
    in the feed row's favour and whose survivor kept the feed's court, clock
    and spellings under the sheet's document id. A played box is exempt: a
    sheet drops a finished match's time band, and the row then keeps what it
    had (ingest's `keep_start`).
    """
    return [r for r in rows
            if r.start_type == "estimated" and r.last_document_id
            and r.last_document_id not in feed_docs
            and not (r.started_at or r.completed_at or r.winner_side)]


def feed_order_unstated(rows, feed_docs) -> list[list]:
    """Courts, as lists of rows, whose order a FEED wrote without knowing it.

    A sheet's page is its order; a feed has only clocks. The WTA publishes
    every "Followed By" match with no clock and no place on its court (see
    wta_feed.unordered_courts), so two or more of them on one court were put
    in SOME order by a sort, not by the tour — Singapore 2026-09-19 had Garland
    v Perez fourth on CENTER COURT where the sheet prints it third, and every
    estimate down the court followed the invented order. Rows already begun
    are history, not an order question.
    """
    courts: dict = {}
    for r in rows:
        if (r.last_document_id in feed_docs and not r.start_time_local
                and not (r.started_at or r.completed_at or r.winner_side)):
            courts.setdefault(r.court or "", []).append(r)
    return [rs for rs in courts.values() if len(rs) > 1]


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


def _law_people(raw_names) -> list[frozenset]:
    """One side's PEOPLE as the law reads them: per person (a "/" splits a
    team) the words of `_law_person` that are names rather than initials.

    Whole names, never a surname extraction — that is the serve path's
    reading (`schedule.join_surnames`), and a law that joined results the
    same way would go blind with it. "Petr Bar Biryukov" and "Petr BAR
    BIRYUKOV" are the same three words however either source capitalises."""
    out = []
    for raw in raw_names:
        for part in (raw or "").split("/"):
            words = frozenset(w for w in _law_person(part).split() if len(w) >= 2)
            if words:
                out.append(words)
    return out


def _people_agree(xs: list, ys: list) -> bool:
    """Do two lists of `_law_people` name the same people, one-to-one? A pair
    agrees when one's words are the other's or a subset ("C. BUCSA" is
    Cristina Bucsa) — `_sides_agree`, person by person."""
    if not xs or len(xs) != len(ys):
        return False
    if len(xs) == 1:
        return _sides_agree(xs[0], ys[0])
    from itertools import permutations
    return any(all(_sides_agree(x, y) for x, y in zip(xs, perm))
               for perm in permutations(ys))


# PLAY LIVES ON THE MATCH, NOT ALWAYS ON THE ROW. A doubles or qualifying slot
# carries its own status, start and winner because nothing else ever sees it;
# a main-draw SINGLES slot carries none of them — its result is written to
# `matches`, and its schedule row stays `scheduled` with every column empty
# from the first ball to the last. `schedule.recompute_expected_starts` knows
# this and reads the linked match; the three laws below did not, and read the
# row alone.
#
# Korea Open 2026-09-23: Back v Joint (entry 1401, CENTER COURT) finished at
# 06:12, and match 5407 said so. The chain therefore freed the court at 06:12
# and floored Joint's "After suitable rest" doubles on GRANDSTAND from there.
# `rest_slot_without_its_rest` still read entry 1401 as a match yet to come,
# invented its end as printed start + 102 minutes = 06:42, and convicted the
# doubles at "~7:22" for not leaving 45 minutes after a moment that never
# happened.
#
# So "has this row been on court?" gets ONE reading — `never_played` in
# `check_day`, the row's own columns joined to its bracket match, the same
# reading the pull rules and `slot_unconfirmed` use. This is the row-only
# half, the default for a caller with no database (the pure-function tests);
# `check_day` passes the joined reading in.
def _row_played(r) -> bool:
    return bool(r.started_at or r.completed_at or r.winner_side
                or r.live_scores_json or r.status in ("live", "completed"))


def player_on_two_courts(rows, played=_row_played) -> list[tuple]:
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
        return not played(r)

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


# The law's own reading of the rest wording, apart from schedule's.
_LAW_REST_RE = re.compile(r'\brest\b', re.I)


def rest_slot_ahead_of_its_match(rows, played=_row_played) -> list[tuple]:
    """(rest row, the match it waits for, the person) wherever a slot worded
    "after (suitable) rest" is expected to START BEFORE its player's match on
    another court does.

    SP Open 2026-09-18 (document 313): Stoiana's doubles QF on QUADRA 1,
    "After suitable rest", read "~3:40 PM" while her singles QF on CENTRAL was
    "Not before 5:30 PM". `player_on_two_courts` passed it — the windows did
    not overlap, the doubles' 80 minutes ending before 5:30 — and the chain
    had used the rest wording only to break a tie between overlapping
    windows. The wording is an ORDER: the rest is from the player's other
    match, so that match comes first. Checked on the order alone (start before
    start), not the length of the rest, so a match in play whose remaining
    time the law cannot read still convicts nothing it should not.

    The match waited for is the EARLIEST any of its players has on another
    court (a partner's evening singles is not what the rest is for); none when
    one of them has a match earlier on the rest row's own court (the rest is
    for that one), and nobody waits for a walkover (it has no duration). Exempt:
    a start the sheet fixed, and a rest row already under way.
    """
    def pending(r):
        return not played(r)

    def begins(r):
        return _naive_utc(r.started_at) or _naive_utc(r.expected_start_at)

    def people(r):
        open_sides = (r.tbd_side or "ab") if r.is_tbd else ""
        out = {}
        for p in r.players or []:
            if p.side in open_sides or _names_nobody(p.raw_name or ""):
                continue
            key = _law_person(p.raw_name)
            if key:
                out[key] = p.raw_name
        return out

    who = {r.id: people(r) for r in rows}
    out = []
    for r in rows:
        if (not _LAW_REST_RE.search(r.start_note or "") or not pending(r)
                or (r.start_type == "fixed" and r.expected_source == "printed")
                or begins(r) is None):
            continue
        mine = [(o, name) for key, name in who[r.id].items()
                for o in rows if o.id != r.id and key in who[o.id]]
        if any((o.court or "") == (r.court or "")
               and (o.court_order or 0) < (r.court_order or 0) for o, _ in mine):
            continue
        others = [(o, name) for o, name in mine if (o.court or "") != (r.court or "")
                  and not _LAW_REST_RE.search(o.start_note or "")
                  and o.estimated_duration_min and begins(o) is not None]
        if not others:
            continue
        first, name = min(others, key=lambda x: (begins(x[0]), x[0].id))
        if (begins(first) - begins(r)).total_seconds() > 60:
            out.append((r, first, name))
    return out


# How long "suitable" is, as the law reads it: the tightest gap ever measured
# between a rest-worded doubles and its player's singles on another court was
# Dolehide's 50 minutes (Guadalajara 2026-09-14); 45 leaves the estimate room
# to err early. Stated here rather than imported from schedule, so the chain
# and the law can disagree.
_LAW_REST_MIN = 45


def rest_slot_without_its_rest(rows, played=_row_played) -> list[tuple]:
    """(rest row, the match it follows, the person) wherever a slot worded
    "after (suitable) rest" is expected to start less than `_LAW_REST_MIN`
    after the expected END of a match one of its players begins earlier on
    another court.

    Singapore 2026-09-23 (document 441): CHWALINSKA / KREJCIKOVA "After
    suitable rest" on COURT 1, both in singles on CENTER COURT before it. The
    chain rested the doubles from Chwalinska's 1:00 PM match only — the
    earliest — and put it at "~5:00 PM", 19 minutes after Krejcikova's
    2:55 PM singles was expected to end. `rest_slot_ahead_of_its_match`
    passed it (the doubles came after both singles), and so did
    `player_on_two_courts` (the windows never met).

    Both rows still to come: a match in play has a remaining time the law
    cannot read. Exempt as in `rest_slot_ahead_of_its_match`: a start the sheet
    fixed, another rest-worded row, and a rest row whose player has an earlier
    match on its own court (the rest is for that one, and the court's chain
    already spaces it).
    """
    def pending(r):
        return not played(r)

    def people(r):
        open_sides = (r.tbd_side or "ab") if r.is_tbd else ""
        out = {}
        for p in r.players or []:
            if p.side in open_sides or _names_nobody(p.raw_name or ""):
                continue
            key = _law_person(p.raw_name)
            if key:
                out[key] = p.raw_name
        return out

    who = {r.id: people(r) for r in rows}
    out = []
    for r in rows:
        start = _naive_utc(r.expected_start_at)
        if (not _LAW_REST_RE.search(r.start_note or "") or not pending(r)
                or (r.start_type == "fixed" and r.expected_source == "printed")
                or start is None):
            continue
        mine = [(o, name) for key, name in who[r.id].items()
                for o in rows if o.id != r.id and key in who[o.id]]
        if any((o.court or "") == (r.court or "")
               and (o.court_order or 0) < (r.court_order or 0) for o, _ in mine):
            continue
        seen = set()
        for o, name in mine:
            o_start = _naive_utc(o.expected_start_at)
            if (o.id in seen or (o.court or "") == (r.court or "")
                    or _LAW_REST_RE.search(o.start_note or "") or not pending(o)
                    or not o.estimated_duration_min or o_start is None
                    or o_start >= start):
                continue
            end = o_start + _timedelta(minutes=o.estimated_duration_min)
            if start - end < _timedelta(minutes=_LAW_REST_MIN - 1):
                seen.add(o.id)
                out.append((r, o, name))
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

    # ROWS FROM THE FEEDS ARE NOT SHEET ROWS (2026-09-18). The WTA's JSON and
    # Sofascore render a name as "Anna Blinkova" or "Dabrowski G / Stefani L",
    # never as the sheet's "Anna BLINKOVA FRA" — so the sheet-form law is for
    # rows a sheet wrote. Which document wrote a row is on the row.
    feed_docs = {d.id for d in (await db.execute(
        select(ScheduleDocument).where(
            ScheduleDocument.tournament_id == tournament_id,
            ScheduleDocument.play_date == play_date))).scalars()
        if (d.source_url or "").startswith("feeds://") or "api.wtatennis.com" in (d.source_url or "")}

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
    de_nat = {de.id: de.nationality for de in dents if de.nationality}
    # {match id: (its round number, its draw's number of rounds)} for every
    # bracket match a row of this day is linked to — `round_contradicts_bracket`.
    linked = {e.match_id for e in rows if e.match_id is not None}
    match_round = {mid: (rn, nr) for mid, rn, nr in (await db.execute(
        select(Match.id, Match.round_number, Draw.num_rounds)
        .join(Draw, Draw.id == Match.draw_id)
        .where(Match.id.in_(linked)))).all()} if linked else {}
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
    # The same pairings the other way round, and every spelling held for an
    # entry — `bracket_player_unlinked`.
    match_pair = {mid: pair for pair, mid in pair_match.items()}
    de_names = {de.id: [nm for nm in dict.fromkeys((de.name, de.sofa_name)) if nm]
                for de in dents}

    # The SERVE path's own resolver, run here so the law can see the shape the
    # API actually hands out. See settled_side_not_two below for why a check
    # over the stored rows cannot.
    from datetime import date as _date, timedelta as _td
    from app.services.schedule import (
        result_pair_keys, settle_from_result_rows, settled_sides_index)
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
    doc_published: dict = publication_clocks(day_docs)
    wins: list = []
    if any(e.is_tbd for e in rows):
        wins = (await db.execute(
            select(ScheduleEntry).where(
                ScheduleEntry.tournament_id == tournament_id,
                ScheduleEntry.winner_side.isnot(None),
                ScheduleEntry.play_date >= _pd - _td(days=14),
                ScheduleEntry.play_date <= _pd))).scalars().all()
        settled_idx = settled_sides_index(wins)
        for r in wins:
            if r.completed_at is None:
                continue
            for key in result_pair_keys(
                    [p.raw_name for p in r.players if p.side == "a"],
                    [p.raw_name for p in r.players if p.side == "b"]):
                decided_at[key] = _naive_utc(r.completed_at)

    def flag(code, entry, detail):
        # ROWS THE FEEDS WROTE ARE NOT JUDGED BY THE SHEET'S RENDERING
        # (2026-09-18): every name_* law reads how a PDF prints a name; a
        # WTA-JSON or Sofascore row is rendered by its feed, by design.
        if str(code).startswith("name_") and getattr(entry, "last_document_id", None) in feed_docs:
            return
        v.append({"code": code, "entry_id": entry.id if entry else None,
                  "court": getattr(entry, "court", None), "detail": detail})

    seen_pairings: list = []
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

        # 2026-09-25, Chengdu COURT 2 (doc 516): "Alternate vs Marcelo MELO /
        # Ryan SEGGERMAN", a doubles R16, stored as SINGLES — the placeholder
        # made the row tbd, and with no slash on it `_classify` read tbd as
        # "alternatives" and called it singles. The ingest then declared the
        # two-name side unresolved too, so `singles_side_stacked` above was
        # satisfied and the page served "MELO or SEGGERMAN".
        #
        # The stored row looks the same as an honest singles "Qualifier vs
        # X or Y", so the tell is the draw: a main-draw singles alternative is
        # between two people IN the singles draw. A role word facing two names
        # that resolve to no singles entry at all is a doubles pair misfiled.
        if e.discipline == "singles" and e.stage == "main":
            for mine, other in ((na, nb), (nb, na)):
                if (mine and all(_names_nobody(p.raw_name or "") for p in mine)
                        and len(other) == 2
                        and not any(p.draw_entry_id for p in other)
                        and not any(_names_nobody(p.raw_name or "") for p in other)):
                    flag("placeholder_faces_unlinked_pair", e,
                         " / ".join(p.raw_name or "" for p in mine) + " vs "
                         + " / ".join(p.raw_name or "" for p in other)
                         + " — two names in no singles draw: a doubles pair?")

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
        # when it was generated. The server's Last-Modified does, where the
        # fetch kept it — see `publication_clocks`.
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
            fetched = doc_published.get(e.last_document_id)
            for side_key in (e.tbd_side or "ab"):
                alts = sorted((p for p in players if p.side == side_key),
                              key=lambda x: x.position or 1)
                if len(alts) != 2 or fetched is None:
                    continue
                _served, resolved = settle_from_result_rows(alts, settled_idx)
                if not resolved:
                    continue
                done = next((decided_at[k] for k in result_pair_keys(
                    [alts[0].raw_name], [alts[1].raw_name]) if k in decided_at), None)
                if done is not None and done + _REISSUE_LATENCY < fetched:
                    flag("pending_side_decided_before_document", e,
                         f"side {side_key} still offers "
                         + " or ".join(p.raw_name or "" for p in alts)
                         + f", but that match finished {done.isoformat()} and "
                           f"document {e.last_document_id} was fetched "
                           f"{fetched.isoformat()} — the newer sheet's "
                           "rendering of this slot was lost")

        # 2026-09-22, Chengdu COURT 1 (doc 410): the Q2 slot "[2] Alexandre
        # MULLER FRA or Luka PAVLOVIC FRA vs Petr BAR BIRYUKOV or [7] Andre
        # ILAGAN USA" went on offering both choices after both Q1 feeders had
        # finished. The results were on the Sofascore feed's rows for the day
        # before, spelled "Luka Pavlović" and "Petr Bar Biryukov", and the
        # serve path joined results to slots by `_sheet_surnames` — which keeps
        # the accent and, finding no capitals, reads a feed's compound surname
        # as its last word. Neither key met. Two slots over, the Ymer/Galarneau
        # feeder, spelled alike by both sources, settled, so the page was
        # inconsistent with itself as well as with the results.
        #
        # Every rule above that judges a settled side runs the serve path's
        # resolver and only looks at what it RESOLVED, so a join that silently
        # misses is invisible to all of them, and `decided_at` shared the same
        # key and went blind the same way. This one finds the feeder with the
        # law's own reading of a person (`_law_people`: whole names, folded,
        # countries stripped by membership). Where that reading finds a
        # finished match between exactly this side's two candidates, the serve
        # path must have settled the side, and settled it to the winner.
        #
        # A side whose candidates all carry a draw entry is left to
        # `alternatives_already_decided`: the serve path asks the bracket
        # first, and the bracket is that rule's business.
        if e.is_tbd and wins:
            for side_key in (e.tbd_side or "ab"):
                alts = sorted((p for p in players if p.side == side_key),
                              key=lambda x: x.position or 1)
                if len(alts) != 2 or all(p.draw_entry_id for p in alts):
                    continue
                cands = [_law_people([p.raw_name]) for p in alts]
                if not all(cands):
                    continue
                feeder = None
                for r in wins:
                    if r.id == e.id:
                        continue
                    ra = _law_people([p.raw_name for p in r.players if p.side == "a"])
                    rb = _law_people([p.raw_name for p in r.players if p.side == "b"])
                    if ((_people_agree(cands[0], ra) and _people_agree(cands[1], rb))
                            or (_people_agree(cands[0], rb) and _people_agree(cands[1], ra))):
                        feeder = (r, ra if r.winner_side == "a" else rb)
                        break
                if feeder is None:
                    continue
                r, won = feeder
                served, resolved = settle_from_result_rows(alts, settled_idx)
                if not resolved:
                    flag("pending_side_result_unjoined", e,
                         f"side {side_key} still offers "
                         + " or ".join(p.raw_name or "" for p in alts)
                         + f", but entry {r.id} ({r.play_date}) recorded that "
                           "match's winner: "
                         + " / ".join(p.raw_name or "" for p in r.players
                                      if p.side == r.winner_side)
                         + " — the serve path's name join missed it")
                elif not _people_agree(_law_people([p.raw_name for p in served]), won):
                    flag("settled_side_not_winner", e,
                         f"side {side_key} settles to "
                         + " / ".join(p.raw_name or "" for p in served)
                         + f", but entry {r.id} ({r.play_date}) was won by "
                         + " / ".join(p.raw_name or "" for p in r.players
                                      if p.side == r.winner_side))

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

        # 2026-09-18, Guadalajara doc 298: the sheet printed "[8] Liudmila
        # SAMSONOVA" with no country, as every sheet does for a neutral
        # athlete, and the page flew a Russian flag beside her. The WTA feed
        # that held the day an hour earlier states PlayerCountry "RUS"; it
        # wrote the code onto her row, and `_sync_players` let no later None
        # erase it. The web and the app each make a flag from EITHER the
        # served nationality or a name's trailing code, so both are judged —
        # the served one THROUGH `served_nation`, which is the serve path's
        # own computation and not a copy of it.
        #
        # 2026-09-21, Korea Open "Alina KORNEEVA": that fix closed every
        # source that writes schedule_entry_players.nationality and left the
        # one the serve path prefers — the DRAW ENTRY, where assign_rankings
        # deliberately backfills RUS/BLR from Tennis Explorer so the BRACKET
        # can fly those flags (2026-07-11). Judging the raw column instead
        # would now call all 192 of those rows a fault, and they are not one:
        # the draw page is ours to render. Judging what is SERVED asks the
        # only question this law ever meant — does the sheet's row fly a flag
        # the sheet withheld.
        #
        # "Arantxa RUS" is a surname: a trailing code counts only after a
        # capitalised surname, as in name_trailing_noncountry above. Its own
        # copy of the codes, not oop_parser's: the law must not go blind when
        # the thing it checks is edited — drop RUS from NEUTRAL_NATIONS and
        # `served_nation` starts serving it, and this fires.
        for p in players:
            served = served_nation(de_nat.get(p.draw_entry_id), p.nationality)
            if (served or "").upper() in _WITHHELD_NATIONS:
                flag("withheld_nation_served", e,
                     f"side {p.side}: {p.raw_name!r} is served nationality "
                     f"{served!r}, which the tour's sheet withholds")
                continue
            stripped = _TRAILING_SEED_RE.sub("", (p.raw_name or "").strip())
            m = _TRAILING_CODE_RE.search(stripped)
            if m and m.group(1) in _WITHHELD_NATIONS:
                before = stripped[:m.start()].split()
                if any(w.isupper() and any(c.isalpha() for c in w) for w in before):
                    flag("withheld_nation_served", e,
                         f"side {p.side}: {p.raw_name!r} ends in "
                         f"{m.group(1)!r}, which the tour's sheet withholds")

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

        # 2026-09-22, Korea Open doc 382: three R32 rows held their own
        # bracket match and printed its player — "[WC] Sohyun PARK KOR"
        # against the draw's "Park So-hyun", "[Q] Ye-Xin MA CHN" against "Ma
        # Yexin" — with no draw_entry_id, so the cards lost the nationality,
        # the draw rank and Ku's Tennis Explorer profile. Every linker missed
        # them at once: the ingest's subset match knew one spelling of a
        # hyphen, and `stamp_linked_rows` read the sheet's COUNTRY and the
        # draw's GIVEN name as the two surnames. Nothing here looked, because
        # an unlinked player is usually an expected state (a qualifier the
        # draw has not caught up with). This one is not: the row's own
        # bracket match already names her. Stated in the law's own reading of
        # a person (`_person_words`, both spellings of a hyphen) so it sees
        # the day the service's matchers all go blind together. A substitute
        # the draw has not caught up with names nobody in the match, and
        # stays silent. Over every stored row: these three, nothing else.
        if (e.discipline == "singles" and e.stage == "main"
                and e.match_id in match_pair and not e.is_tbd
                and len(na) == 1 and len(nb) == 1):
            held = {p.draw_entry_id for p in (na[0], nb[0]) if p.draw_entry_id}
            for p in (na[0], nb[0]):
                if (p.draw_entry_id or "/" in (p.raw_name or "")
                        or _names_nobody(p.raw_name)):
                    continue
                words = _person_words(p.raw_name)
                hit = [i for i in match_pair[e.match_id] - held
                       if any(_sides_agree(words, _person_words(nm))
                              for nm in de_names.get(i, ()))]
                if hit:
                    flag("bracket_player_unlinked", e,
                         f"side {p.side}: {p.raw_name!r} is entry {hit[0]} of "
                         f"its own bracket match {e.match_id}, but "
                         f"draw_entry_id is NULL")

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

        # 2026-09-18, Guadalajara: the WTA feed states an unplaced match's
        # RoundID as a bare integer placeholder — 2 on all three semi-finals —
        # the feed reader took it for the second round, and ingest writes the
        # source's round OVER the one it derives from the bracket. A row linked
        # to a bracket match is the one row whose round is KNOWN, so its label
        # must name that match's round. The law's own reading of a label, not
        # schedule._round_label: "R2" is a round NUMBER, "R16" a field size.
        if e.match_id is not None and e.match_id in match_round:
            said = _law_round_number(e.round_label, match_round[e.match_id][1])
            if said is not None and said != match_round[e.match_id][0]:
                flag("round_contradicts_bracket", e,
                     f"labelled {e.round_label!r} but bracket match {e.match_id} "
                     f"is round {match_round[e.match_id][0]} of "
                     f"{match_round[e.match_id][1]}")

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

        # 2026-09-24, Korea doc 465: "Doubles", the heading the sheet printed
        # over an empty section of each court's column, stored as a player on
        # whichever side was open when the line arrived. The page drew a
        # phantom team — "Taylah PRESTON AUS / Doubles" against Ostapenko —
        # and the two R16 SINGLES rows wearing it lost their bracket match.
        # The sheet talking about itself is never a person; see
        # `_names_the_event` for why neither neighbour above can be trusted to
        # say so.
        for p in players:
            raw = (p.raw_name or "").strip()
            if raw and _names_the_event(raw):
                flag("name_is_event_heading", e,
                     f"side {p.side}: {raw!r} is the sheet's own event "
                     f"heading, not a player")

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
        #
        # THE SAME PLAYERS, NOT THE SAME PRINTED STRING. This compared raw
        # names lowercased, so it could only see a duplicate both sources
        # spelled identically — and the duplicate that matters is the one they
        # spelled differently. Korea Open 2026-09-20: the WTA feed's "[WC]
        # Eunhye LEE KOR vs [5] Ye-Xin MA CHN" and the Sofascore half of the
        # same document's "Eunhye Lee vs Yexin Ma" are one Q2, stored twice
        # because `_pairing_key` hashes `_norm`, which spaces the hyphen. The
        # day carried the match on GRANDSTAND #1 and a phantom of it at #3,
        # and what reached the owner was the downstream symptom — the real row
        # unstamped by the newest document, `slot_pulled_not_retired`. This
        # law was the one that should have named it, and was blind.
        #
        # Disciplines must agree, as they must in `_dedupe_day`: a player in
        # the singles and in the doubles on one day puts her singles side
        # inside her doubles side, and those are two matches.
        if not e.is_tbd and players:
            sides = {s: set().union(set(), *(_person_words(p.raw_name)
                                             for p in players if p.side == s))
                     for s in ("a", "b")}
            twin = next(
                (eid for eid, disc, prev in seen_pairings
                 if disc == e.discipline
                 and ((_sides_agree(sides["a"], prev["a"])
                       and _sides_agree(sides["b"], prev["b"]))
                      or (_sides_agree(sides["a"], prev["b"])
                          and _sides_agree(sides["b"], prev["a"])))), None)
            if twin is not None:
                flag("pairing_duplicated", e,
                     f"same players as entry {twin}")
            else:
                seen_pairings.append((e.id, e.discipline, sides))

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
    # The walkover is on the bracket for a singles row — see
    # clock_runs_backwards. Both result columns, as the chain reads either.
    wo_matches = {
        mid for mid, sj, ssj in ((await db.execute(
            select(Match.id, Match.scores_json, Match.sofa_scores_json)
            .where(Match.id.in_(linked)))).all() if linked else [])
        if _scores_walked_over(sj) or _scores_walked_over(ssj)}
    for e, prev in clock_runs_backwards(
            rows, venue_tz,
            walked_over=lambda r: _walked_over(r) or r.match_id in wo_matches):
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

    # 2026-09-23, Hangzhou (doc 421): the Court view ranks courts by stage
    # before seed, so a row filed in the wrong draw misorders the courts.
    for e in singles_stage_contradicts_round(rows):
        flag("singles_stage_contradicts_round", e,
             f"singles row filed stage={e.stage!r} with round_label="
             f"{e.round_label!r} — the page badges it, and ranks its court, "
             f"by the wrong draw")

    # 2026-09-19, Singapore and Korea qualifying (feed documents 306/307):
    # the WTA's published shape names its court in `CourtName` and gives the
    # "Followed By" matches no order; read as the played shape, both days
    # went up as eight matches on one blank court, chained to 11:36 PM. The
    # law passed it — nothing here asked where a row IS or who ordered it.
    # 2026-09-25, Hangzhou doc 525 — see round_unlabelled_beside_labelled.
    for e in round_unlabelled_beside_labelled(rows):
        flag("round_unlabelled_beside_labelled", e,
             f"{e.stage}/{e.discipline} on {e.court!r} #{e.court_order} has no "
             f"round while the day's other {e.stage}/{e.discipline} rows do — "
             f"the page shows a blank chip among labelled ones")
    for e in court_unnamed(rows):
        flag("court_unnamed", e,
             f"#{e.court_order} is stored with no court — every sheet prints "
             f"one over every box, so the source's court went unread")
    for e, other in court_opened_twice(rows):
        flag("court_opened_twice", e,
             f"{e.court!r} #{e.court_order} and #{other.court_order} (entry "
             f"{other.id}) both START at {e.start_time_local!r} — two courts "
             f"read as one")
    # 2026-09-23, Hangzhou (doc 418): the sheet took a feed-written day back
    # and a dedupe merge kept the feed row's court, clock and names under the
    # sheet's document id — COURT 1 rendered as two courts. See
    # schedule._take_placement.
    for e, other in court_spelled_two_ways(rows):
        flag("court_spelled_two_ways", e,
             f"{e.court!r} #{e.court_order} is {other!r} spelled another way — "
             f"the page shows one court twice")
    for e in sheet_row_placed_by_feed(rows, feed_docs):
        flag("sheet_row_placed_by_feed", e,
             f"{e.court!r} #{e.court_order} was restated by sheet document "
             f"{e.last_document_id} but still starts {e.start_note!r}, a feed's "
             f"estimate — a merge kept the older row's placement")
    for rs in feed_order_unstated(rows, feed_docs):
        first = min(rs, key=lambda r: (r.court_order or 0, r.id))
        flag("feed_order_unstated", first,
             f"{first.court!r}: {len(rs)} rows a feed wrote with no clock "
             f"(entries {sorted(r.id for r in rs)}) — the feed states no order "
             f"among them, so the court's order was invented")

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

    # The same question the other way up, for the laws that take the predicate
    # (`player_on_two_courts` and the two rest laws). Their default is the
    # row's own columns, which is blind to a singles match whose result lives
    # on `matches` — see `_row_played`.
    def _was_on_court(e) -> bool:
        return not never_played(e)

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
        last_done: dict = {}
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
                if done and done <= published:
                    last_done[on_court[mid]] = max(
                        last_done.get(on_court[mid], done), done)
        # 2026-09-23, Singapore — THE PULL ON AN EMPTY COURT. Krejcikova
        # withdrew and the 2:35 PM revision took her R16 vs Mertens ("Not
        # before 2:30 PM") off CENTER COURT, which had finished its 1:00 PM
        # match at 2:09 and was standing empty waiting for the 2:40. The
        # court's first start was 11:00 AM so the rule above was mute, nothing
        # was in play so the mid-session rule was mute, and one revision of
        # silence is inside `slot_unconfirmed`'s grace window — CLEAN, on a
        # page printing a withdrawn match between two real ones and rendering
        # the printed "Not before 2:40 PM" behind it as "~4:20 PM".
        #
        # The law's own reading of `_slot_was_pulled`'s between-matches proof:
        # a court is IDLE when a match this sheet still prints there finished
        # at or before publication, nothing is underway, and the next match it
        # prints there is not yet due. A bracket-linked row with no trace of
        # play whose own printed start falls in that empty stretch was pulled.
        # Read off `started_at`/`completed_at`/`winner_id` only, as above, so
        # a disagreement with the service's sofa_* pair surfaces here.
        next_due: dict = {}
        for e in rows:
            if (e.last_document_id or 0) != latest_doc:
                continue
            when = _naive_utc(_printed_instant(e, venue_tz))
            if when and published and when > published and (
                    e.court not in next_due or when < next_due[e.court]):
                next_due[e.court] = when
        court_idle = {c: w for c, w in last_done.items()
                      if c not in in_play and c in next_due}
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
            elif (never_played(e) and e.match_id and venue_tz
                  and e.court in court_idle
                  and (_naive_utc(_printed_instant(e, venue_tz)) or _FAR_PAST)
                  >= court_idle[e.court]):
                flag("slot_pulled_between_matches_not_retired", e,
                     f"document {latest_doc} dropped this slot while {e.court} "
                     f"stood empty between matches — the court's last match "
                     f"finished at {court_idle[e.court]:%H:%M} UTC, its next "
                     f"is not yet due, and this slot's bracket match was never "
                     f"started — it was pulled, not played, and it is still "
                     f"chaining the clocks behind it")
            elif (never_played(e)
                  and revisions_since(doc_fetched,
                                      e.last_document_id) >= UNCONFIRMED_GRACE):
                # A DECIDED MATCH IS NOT AN ABANDONED ROW. Singapore
                # 2026-09-23: Krejcikova withdrew, the 2:35 PM revision took
                # her R16 vs Mertens off CENTER COURT, and thirteen minutes
                # later the feed wrote the walkover — Mertens through, "w/o".
                # A sheet is right to stop printing a match that will not be
                # played, and the row is right to stay: it carries a result
                # users are scored on. Reporting it as a slot nothing restated
                # is an expected state served as an error, once per sweep,
                # forever. `never_played` is the same reading the pull rules
                # above use, and it is the reading that knows — a SINGLES row
                # carries no result of its own, so the answer is on `matches`
                # (this row reads scores_json NULL, printed_score NULL,
                # status "scheduled" and is nonetheless over).
                #
                # What still alarms is what the law genuinely cannot place:
                # Cincinnati's dropped doubles, which have no bracket match
                # and no result anywhere, stay unconfirmed as before.
                #
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
    # `never_played`, not the row's own columns: a singles row keeps its result
    # on `matches` and stays `scheduled` forever, so the row-only reading calls
    # a finished R16 "still to come". Pair that with the QF the next sheet
    # prints for its winner and the two share a side with nothing in common on
    # the other — the Cincinnati shape (2026-08-19), reported as one slot
    # stated twice. See `_row_played`.
    fresh = [r for r in rows if never_played(r)]
    for i, a in enumerate(fresh):
        for b in fresh[i + 1:]:
            # LIKE WITH LIKE. One slot means one match: the same event
            # (discipline), the same half of it (stage) and the same round. A
            # round either side leaves unlabelled cannot contradict, and does
            # not acquit.
            if a.stage != b.stage or a.discipline != b.discipline:
                continue
            if (a.round_label and b.round_label
                    and a.round_label != b.round_label):
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
    #
    # 2026-09-20, Korea Open Q2 (doc 348): "[5] Ye-Xin MA CHN" served bare
    # beside three linked qualifiers. Tennis Explorer files her "Yexin Ma";
    # the serve path's key spaced the hyphen ("ye xin ma") and so did this
    # law's, which is why it stayed silent — the exhaustive scan was only as
    # wide as the one spelling both sides shared. A HYPHEN IS TWO SPELLINGS
    # (rankings._match_token_set, history.tml.name_keys), and the law now
    # reads it that way itself, on both sides, rather than borrowing the
    # router's `_spellings`: a copy it shared would go blind with it.
    from app.models.rankings import TePlayer as _TePlayer
    from app.routers.schedule import (_by_name, _name_key as _te_key,
                                      _slugs_by_name)
    from app.services.rankings import _norm as _te_norm

    def _law_spellings(name: str, fold) -> set:
        out = {fold(name)}
        if "-" in name:
            out.add(fold(name.replace("-", "")))
        return out - {""}

    raws = [p.raw_name for e in rows for p in (e.players or []) if p.raw_name]
    if raws:
        served = await _slugs_by_name(db, raws)
        truth: dict = {}
        for slug, display in (await db.execute(
                select(_TePlayer.te_slug, _TePlayer.name_display)
                .where(_TePlayer.te_slug.isnot(None)))).all():
            for k in _law_spellings(display or "", _te_norm):
                # One name, two people, is a walk-away for the serve path too —
                # so it must not count as something the shortlist "missed".
                truth[k] = None if k in truth else slug
        for e in rows:
            for p in (e.players or []):
                raw = p.raw_name or ""
                hits = [truth[k] for k in sorted(_law_spellings(raw, _te_key))
                        if k in truth]
                # Two spellings reaching two people is a walk-away as well.
                if not hits or any(h is None or h != hits[0] for h in hits):
                    continue
                want = hits[0]
                if _by_name(served, raw):
                    continue
                if truth.get(_te_key(raw)):
                    flag("name_te_shortlist_missed", e,
                         f"side {p.side}: {raw!r} is te_players "
                         f"{want} by whole name, and the serve path's "
                         f"shortlist did not offer it")
                else:
                    flag("name_te_spelling_missed", e,
                         f"side {p.side}: {raw!r} is te_players {want} "
                         f"with its hyphen closed up, and the serve path "
                         f"read only the split spelling")

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
        the country is already gone — and the generational suffix with it,
        or two unrelated players both sign as "jr"."""
        out = set()
        for p in (entry.players or []):
            raw = _LEADING_SEED_RE.sub(
                "", _TRAILING_SEED_RE.sub("", (p.raw_name or "").strip()))
            toks = raw.split()
            while len(toks) >= 2 and toks[-1] in COUNTRY_CODES:
                toks = toks[:-1]
            while len(toks) >= 2 and _GEN_SUFFIX_RE.match(toks[-1]):
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

    # 2026-09-23, Singapore doc 463: COURT 1's opener — CASCINO / FENG vs
    # COSTOULAS / GIBSON, printed "Not before 2:00 PM", no result on the sheet
    # and no score anywhere — was served COMPLETED. The day endpoint infers a
    # status the feeds cannot give it from the RUNNING ORDER ("a later slot
    # under way proves the ones above it are over"), which is sound only
    # within one tournament's court. Its groups were keyed on the court NAME,
    # and a day spans every tournament playing: Chengdu and Hangzhou each had
    # a live second match on THEIR "COURT 1", so Singapore's first was
    # declared finished. Three tournaments shared "COURT 1" that afternoon and
    # four shared "CENTER COURT" — generic court names are the norm, so this
    # was firing most days, and only where a court name collided.
    #
    # Stated as the law that was broken — no running order may span two
    # tournaments — and read through the serve path's OWN key
    # (routers/schedule.court_run_key) the way untimed_slot_served_first runs
    # its ordering, so the name-only key cannot drift back.
    from app.routers.schedule import court_run_key as _court_run_key
    runs: dict = {}
    for r in (await db.execute(
            select(ScheduleEntry).where(
                ScheduleEntry.play_date == play_date))).scalars().all():
        runs.setdefault(_court_run_key(r), []).append(r)
    for key, group in runs.items():
        mine = [r for r in group if r.tournament_id == tournament_id]
        others = sorted({r.tournament_id for r in group} - {tournament_id})
        if mine and others:
            flag("court_run_crosses_tournaments", mine[0],
                 f"{mine[0].court!r} puts this tournament's {len(mine)} slot(s) "
                 f"and {len(group) - len(mine)} from tournament(s) {others} "
                 f"under one running order (key {key!r}) — another venue's "
                 f"court decides what has finished here")

    # 2026-09-23, Singapore doc 468: COURT 1's opener — CASCINO / FENG vs
    # COSTOULAS / GIBSON — was printed with its score, "7-6(3) 6-1", on the
    # very sheet the page's PDF button opens, and the page offered it as an
    # upcoming 2:00 PM match all afternoon. ESPN covers neither doubles nor
    # qualifying, so `winner_side` and `live_scores_json` stay empty unless
    # the Sofascore sweep claims the event, and the day endpoint's other
    # source of truth — the running order, "a later slot under way proves the
    # ones above it are over" — cannot say anything about the LAST match to
    # finish on a court that then stands idle. That is an ordinary shape, not
    # a corner: every court has a last finished match.
    #
    # Stated as the law that was broken — a slot the tournament has declared
    # finished is never served as still to come — and read through the serve
    # path's OWN `_status_of`, the way court_run_crosses_tournaments runs its
    # key, so a future edit there cannot quietly drop the sheet again. The
    # law's reading of the score is its own (`_sheet_declared_finished`).
    from app.routers.schedule import _status_of as _served_status
    linked_m = {}
    if linked:
        from app.models.tournament import Match as _MatchRow
        linked_m = {m.id: m for m in (await db.execute(
            select(_MatchRow).where(_MatchRow.id.in_(linked)))).scalars().all()}
    for e in rows:
        if not _sheet_declared_finished(e):
            continue
        if _served_status(e, linked_m.get(e.match_id) if e.match_id else None) \
                != "scheduled":
            continue
        flag("finished_slot_served_as_upcoming", e,
             f"{e.court!r} #{e.court_order} is printed "
             f"{e.printed_score!r} — the sheet says it is over — and the day "
             f"endpoint still serves it as 'scheduled'"
             + (" (no bracket match behind it, so the sheet is the only"
                " record there is)" if not e.match_id else ""))

    # 2026-09-18, SP Open doc 289 — see player_on_two_courts.
    for a, b, name in player_on_two_courts(rows, played=_was_on_court):
        flag("player_on_two_courts", b,
             f"{name!r} is booked on {a.court!r} (entry {a.id}, "
             f"{_naive_utc(a.expected_start_at):%H:%M} UTC, "
             f"{a.estimated_duration_min} min) and on {b.court!r} (entry "
             f"{b.id}, {_naive_utc(b.expected_start_at):%H:%M} UTC) at once")

    # 2026-09-18, SP Open doc 313 — see rest_slot_ahead_of_its_match.
    for r, first, name in rest_slot_ahead_of_its_match(rows, played=_was_on_court):
        flag("rest_slot_ahead_of_its_match", r,
             f"{r.court!r} #{r.court_order} is printed {r.start_note!r} but "
             f"expected at {_naive_utc(r.expected_start_at):%H:%M} UTC, before "
             f"{name!r}'s match on {first.court!r} (entry {first.id}, "
             f"{(_naive_utc(first.started_at) or _naive_utc(first.expected_start_at)):%H:%M} UTC) "
             f"that the rest is from")

    # 2026-09-23, Singapore doc 441 — see rest_slot_without_its_rest.
    for r, first, name in rest_slot_without_its_rest(rows, played=_was_on_court):
        flag("rest_slot_without_its_rest", r,
             f"{r.court!r} #{r.court_order} is printed {r.start_note!r} but "
             f"expected at {_naive_utc(r.expected_start_at):%H:%M} UTC, less "
             f"than {_LAW_REST_MIN} min after {name!r}'s match on "
             f"{first.court!r} (entry {first.id}, "
             f"{_naive_utc(first.expected_start_at):%H:%M} UTC + "
             f"{first.estimated_duration_min} min) is expected to end")

    # 2026-09-19, Korea Open doc 345: the day's two 11:00 AM Q2 slots came
    # from the WTA feed (tour WTA) and its two "Time TBC" slots from the PDF,
    # which names no tour on a single-tour sheet (NULL). Every name, court and
    # clock matched the sheet; half the cards wore the WTA tag and tint, the
    # app split the day into a "WTA" group and an untitled one, and the H2H
    # popup called a women's match's ranking column "Rank (ATP)". A row's tour
    # is its EVENT's — the linked draw's gender, else the tournament's only
    # one — whoever wrote the row. Stated here without schedule.event_tour, so
    # a change there cannot quietly move the law with it. Mixed doubles and a
    # combined event's unlinked row belong to no single tour and are not judged.
    genders = {d_id: (g or "").upper() for d_id, g in (await db.execute(
        select(Draw.id, Draw.gender).where(
            Draw.tournament_id == tournament_id))).all()}
    only = set(g for g in genders.values() if g)
    for e in rows:
        if e.discipline == "mixed":
            continue
        g = genders.get(e.draw_id) if e.draw_id is not None else (
            next(iter(only)) if len(only) == 1 else None)
        want = {"F": "WTA", "M": "ATP"}.get(g or "")
        if want and e.tour != want:
            flag("tour_unstated", e,
                 f"{e.discipline} {e.round_label or ''} on {e.court!r} has tour "
                 f"{e.tour!r} but its event is {want} — the page tags, tints, "
                 f"groups and labels the H2H ranking by this field")

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
    #
    # 2026-09-22, Chengdu doc 408: "QUALIFYING FINAL" over four boxes, read by
    # nothing, and this check stayed silent — because the count was taken with
    # the READER's regex, so a spelling the reader did not know was not counted
    # either. The count now uses its own wider reading (_HEADER_SHAPED_RE);
    # over the 376 archived sheets that moved it on doc 408 alone.
    headers = (meta or {}).get('round_headers')
    if headers and rounds is not None and not any(rounds):
        out.append({
            "code": "printed_round_dropped", "entry_id": None, "court": None,
            "detail": f"the sheet prints {headers} event header(s) stating a "
                      f"round and the parse kept none — see _EVENT_HEADER_RE "
                      f"and _QUALI_HEADER_RE",
        })

    # The same loss, box by box. `printed_round_dropped` is quiet by design
    # while ANY match wears a round, so a sheet mixing boxes whose round was
    # read ("R32") with boxes whose header was not ("QUALIFYING FINAL") hides
    # the second kind behind the first — doc 408 would have, had its main-draw
    # boxes printed a token. This one names each header a box printed and
    # neither reader took. Measured over the 376 archived sheets with the fix:
    # zero (before it: doc 408's four).
    for court, text in (meta or {}).get('unread_headers') or []:
        out.append({
            "code": "printed_round_unread", "entry_id": None, "court": court,
            "detail": f"{court or '?'}: the box prints {text!r} and no reader "
                      f"took it, so its row has no printed round — teach "
                      f"oop_parser._event_header the spelling",
        })

    # 2026-09-19, Singapore Open doc 291: the layout wrapped Kai Ning Chanya
    # NG's "SGP" onto a line of its own, COUNTRY_CODES knew Singapore only by
    # its pre-2016 code SIN, and a lone three-capital line joins the name above
    # only when it is a country — so her nationality was dropped with no record
    # anywhere, and she published beside an empty flag box. (Her compatriot on
    # the same sheet kept SGP inline and `name_trailing_noncountry` caught
    # that half; the dropped half leaves no row text to judge.) The parser
    # now hands back every such line it drops. Measured over 343 sheets:
    # this one, and nothing once SGP was added.
    for court, name, code in (meta or {}).get('orphan_codes') or []:
        out.append({
            "code": "nationality_code_unknown", "entry_id": None,
            "court": court,
            "detail": f"{court or '?'}: {code!r} printed under {name!r} has a "
                      f"nationality's shape but is not in "
                      f"oop_parser.COUNTRY_CODES, so it was dropped — add it "
                      f"if it is a country",
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
# `expected_undercuts_printed_floor`, `player_on_two_courts` and the two rest
# laws read the same half-written estimate. So do `carried_slot_has_no_time`
# and `untimed_slot_served_first`, which read a row the sheet has only just
# CREATED — still NULL until the recompute (Korea Open doc 549, 2026-09-25:
# a QF carried "Starting at 11:00 AM" was called untimed 0.5 s after insert).
# tests/test_ingest_defers_expected_readers.py holds every reader to this set.
INGEST_DEFERRED = frozenset({"expected_contradicts_printed",
                             "expected_undercuts_printed_floor",
                             "carried_slot_has_no_time",
                             "untimed_slot_served_first",
                             "player_on_two_courts",
                             "rest_slot_ahead_of_its_match",
                             "rest_slot_without_its_rest"})


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


async def relink_resolvable(db, tournament_id: int, play_date) -> list[str]:
    """Fill the draw entry a row could not be matched to WHEN IT WAS INGESTED.

    A schedule row points at a draw entry so the page can show a seed, an
    inferred draw rank, a flag and an entry code. The match is made once, by
    the ingest, against the draw as it stood — and the sheet routinely names
    people the draw does not hold yet:

      * A QUALIFIER, above all. The order of play prints the winners of
        qualifying the evening they win; the main draw gains them when it is
        next scraped. schedule.py says as much where it refuses to erase a
        proved id: "a qualifier reaches draw_entries days after the sheet
        first names them."
      * A SLOT THE BRACKET LATER SETTLES, printed as "A or B" first.
      * A SPELLING the draw acquires afterwards — Sofascore's second name for
        a player the sheet prints its own way.

    Nothing recomputed the match after any of those, because it was only ever
    computed on the ingest path. So a row stayed unlinked unless that day's
    sheet happened to be re-read later, which is luck: of the four qualifiers
    into the Korea and Singapore main draws on 2026-09-21, one had her row
    re-ingested after the draw caught up and wore her rank, and three did not
    and showed no badge at all (owner, 2026-09-20).

    NOR DID ANYTHING REPORT IT. An unlinked row is an expected state at
    ingest, so it is not logged as a fault — and the self-heal watcher acts
    on what the logs say, which means a silence nothing writes down heals
    nothing. That is the gap this closes: the law now re-runs the resolver
    over what is still unmatched, and fills what the draw can answer for.

    A TEAM IS NEVER FILLED. Two people are not one entry, and `None` there
    means "cannot resolve, ever" rather than "not yet".

    Returns the names it linked, for the caller's log.
    """
    from app.models.schedule import ScheduleEntryPlayer
    from app.models.tournament import Draw, DrawEntry
    from app.services.schedule import (
        _entry_tokens, _names_a_team, _resolve_players,
    )

    rows = (await db.execute(
        select(ScheduleEntryPlayer)
        .join(ScheduleEntry, ScheduleEntry.id == ScheduleEntryPlayer.schedule_entry_id)
        .where(ScheduleEntry.tournament_id == tournament_id,
               ScheduleEntry.play_date == play_date,
               # MAIN DRAW ONLY. A qualifying row must not point at a main
               # draw entry even when the person is in both: the badge it
               # would then wear is their place in the MAIN field, and the
               # number the sheet printed beside them in qualifying — their
               # qualifying seed — is the true one for that match. We hold no
               # qualifying draw to link to, which is the whole reason those
               # rows resolve to nothing, and leaving them so is correct.
               ScheduleEntry.stage == "main",
               ScheduleEntryPlayer.draw_entry_id.is_(None)))).scalars().all()
    todo = [r for r in rows if r.raw_name and not _names_a_team(r.raw_name)]
    if not todo:
        return []

    # The same roster the ingest resolves against, from the same builder:
    # both folds of both spellings per entry, and both spellings of a hyphen
    # (schedule._entry_tokens). This was a hand-written second copy, and it
    # went blind with the first — Korea 2026-09-22, "Park So-hyun" in the
    # draw against "Sohyun PARK KOR" on the sheet — see bracket_player_unlinked.
    draw_rows = (await db.execute(
        select(Draw).where(Draw.tournament_id == tournament_id))).scalars().all()
    draws = []
    for d in draw_rows:
        ents = (await db.execute(
            select(DrawEntry.id, DrawEntry.name, DrawEntry.sofa_name)
            .where(DrawEntry.draw_id == d.id))).all()
        draws.append({'draw': d, 'entries': [
            (e[0], *_entry_tokens(nm))
            for e in ents for nm in dict.fromkeys((e[1], e[2])) if nm]})
    if not any(d['entries'] for d in draws):
        return []

    ids = await _resolve_players(db, draws, None, [r.raw_name for r in todo])
    linked = []
    for row, eid in zip(todo, ids):
        if eid is not None:
            row.draw_entry_id = eid
            linked.append(row.raw_name)
    return linked


async def extend_end_dates(db, tournament_id: int, play_date) -> list[int]:
    """Let a day of main-draw play push a draw's end_date out to meet it.

    The evidence is the order of play; the judgement is
    tournament_schedule.adopt_scheduled_end_date, which is where the rules and
    the reasoning live. This only finds the draws and asks.

    Returns the ids of the draws whose end_date moved, for the caller's log.
    """
    from app.models.tournament import Draw
    from app.services.tournament_schedule import adopt_scheduled_end_date

    # Does this day hold main-draw play at all? Qualifying cannot speak to
    # when a tournament ends, and a day of nothing cannot either.
    main = (await db.execute(
        select(ScheduleEntry.id).where(
            ScheduleEntry.tournament_id == tournament_id,
            ScheduleEntry.play_date == play_date,
            ScheduleEntry.stage == "main").limit(1))).first()
    if not main:
        return []

    draws = (await db.execute(
        select(Draw).where(Draw.tournament_id == tournament_id))).scalars().all()
    return [d.id for d in draws if adopt_scheduled_end_date(d, play_date)]


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
        # FIRST, FILL WHAT THE DRAW CAN NOW ANSWER FOR. This is a fix, not a
        # check: the resolver is deterministic and the answer is already in
        # draw_entries, so routing it through a logged fault and the watcher
        # would be ceremony. It runs before the checks so they see the healed
        # state rather than reporting on rows about to be linked.
        # A DAY OF PLAY PAST THE CALENDAR'S LAST DAY MOVES THE LAST DAY.
        # Weather postpones a final and the sheet says so within the hour;
        # Wikipedia's range may never say it. Left alone, computed_status
        # retires the draw with its final unplayed.
        moved = await extend_end_dates(db, tid, day)
        if moved:
            from app.services.system_log import app_log
            await db.commit()
            await app_log(
                "info", "schedule",
                f"End date extended to {day} for {len(moved)} draw(s): play is "
                f"scheduled past the calendar's last day",
                {"tournament_id": tid, "play_date": str(day), "draw_ids": moved},
            )
        relinked = await relink_resolvable(db, tid, day)
        if relinked:
            from app.services.system_log import app_log
            await db.commit()
            await app_log(
                "info", "schedule",
                f"Linked {len(relinked)} schedule row(s) to draw entries the "
                f"ingest could not match yet: {', '.join(relinked[:6])}"
                + (" …" if len(relinked) > 6 else ""),
                {"tournament_id": tid, "play_date": str(day), "names": relinked},
            )
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
