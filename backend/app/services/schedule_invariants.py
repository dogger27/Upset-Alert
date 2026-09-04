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
from datetime import timezone as _tz

from sqlalchemy import select

from app.models.schedule import ScheduleEntry
from app.services.oop_parser import COUNTRY_CODES

# The sheet's own words, in the places a name can pick them up. A slot wording
# printed on its own line sits directly above or below a name and has been
# absorbed by both ends of the parse before now.
_SLOT_WORDING_RE = re.compile(
    r'\b(?:TB[ACD]|followed\s+by|not\s+bef|start(?:s|ing)?\s+at|'
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
# A leading entry-status marker, "[LL] " / "[WC] " — the mirror of
# _TRAILING_SEED_RE, which only strips the ones printed after the name.
_LEADING_SEED_RE = re.compile(r'^(?:\[[^\]]*\]\s*)+')
# Lone letters standing on their own where a name's letters belong. A name may
# hold ONE ("Alex de Minaur" does not, but an initial-only rendering might);
# three is not a name any tour prints. Measured over all 705 stored player
# rows: fires on the four shredded ones below and on nothing else.
_SHRED_MIN_SINGLES = 3


_CLOCK_RE = re.compile(r'^(\d{1,2})[:.](\d{2})\s*(am|pm)?$', re.I)


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
    from app.services.schedule import settle_from_result_rows, settled_sides_index
    _pd = _date.fromisoformat(play_date) if isinstance(play_date, str) else play_date
    venue_tz = (await db.execute(
        select(Draw.venue_timezone).where(
            Draw.tournament_id == tournament_id,
            Draw.venue_timezone.isnot(None)))).scalars().first()
    settled_idx: dict = {}
    if any(e.is_tbd for e in rows):
        settled_idx = settled_sides_index((await db.execute(
            select(ScheduleEntry).where(
                ScheduleEntry.tournament_id == tournament_id,
                ScheduleEntry.winner_side.isnot(None),
                ScheduleEntry.play_date >= _pd - _td(days=14),
                ScheduleEntry.play_date <= _pd))).scalars().all())

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
    latest_doc = max((r.last_document_id or 0) for r in rows) if rows else 0
    if latest_doc:
        for e in rows:
            if (e.last_document_id or 0) < latest_doc:
                flag("slot_unconfirmed", e,
                     f"last confirmed by document {e.last_document_id}, but the "
                     f"day's newest document is {latest_doc} — the current sheet "
                     f"does not print this slot")

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
INGEST_DEFERRED = frozenset({"expected_contradicts_printed"})


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
