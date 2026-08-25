"""
Scoring for order-of-play rows that have no bracket match — doubles, and
qualifying singles.

WHY THIS IS SEPARATE FROM EVERYTHING ELSE. Both are on the order of play and
neither is in the app's draws. Doubles because nobody picks it: no bracket, no
predictions, nothing to score against. Qualifying because a 128-draw stores
rounds 1-7 only, and players who fail to qualify never reach `draw_entries` at
all. ESPN covers neither, so those rows sat at "scheduled" all day with no
score — the one part of the sheet the page could not bring to life.

Sofascore does cover them. So the result is stored on the SCHEDULE ROW itself,
which is the only record of a doubles match that exists here. Nothing about the
draws changes, and `schedule_entries.match_id` stays null for these rows exactly
as it always has.

HOW A ROW IS MATCHED TO AN EVENT. By id where we have one, and by everything
else where we do not. Most doubles specialists are in no singles draw, so only
19 of 64 doubles slots on a real day carried a `sofa_player_id` and ids alone
cannot carry this — but ids are decisive when present, so a confident match
writes back the ones it just proved and the next one leans on names less.

Names alone are NOT enough, and the day this was believed cost a whole Sunday:
surnames identify a person, not a match, and a "winner of Bondar/Jacquemot" row
contains exactly the names of the Q1 match that decides it. So a candidate has
to agree on the day, the printed time, the round, the shape of the match, and
both sides pairing off one-to-one — see `_match`, which is the whole of it.

Claims are re-checked on every sweep rather than trusted once, so a wrong one
lets go by itself; and one event can be claimed by only one row.
"""

import asyncio
import logging
import re
import unicodedata
from collections import namedtuple
from itertools import permutations
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import or_, select

from app.models.schedule import ScheduleEntry, ScheduleEntryPlayer
from app.models.tournament import Draw, DrawEntry, Tournament
from app.services.sofascore import SofascoreBlocked, SofascoreNotFound, _get
from app.services.sofascore_live import _as_espn_shape, _norm_point, _sets_and_tiebreak
from app.services.sofascore_results import _final_scores
from app.services.system_log import app_log

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60.0

# "[WC]" and "[2]" are the sheet's own annotations and never part of a name.
_SHEET_TAGS = re.compile(r"\[[^\]]*\]")
_THREE_CAPS = re.compile(r"[A-Z]{3}$")
# Everything that is not a letter, for telling an INITIAL ("H.") from a
# capitalised surname ("NYS") — both are uppercase, only one has two letters.
_ALPHA = re.compile(r"[^A-Za-z]")

# A day at a venue, expressed in UTC. Play starts no earlier than 06:00 local
# and the last match can finish after midnight, so against play_date's midnight
# UTC an event may legitimately land anywhere from 6h before (UTC+13 morning) to
# 30h after (UTC-6 night session).
_DAY_FROM = timedelta(hours=6)
_DAY_TO = timedelta(hours=30)

# How far an event may sit from the time the SHEET prints for that row. A day's
# order of play runs about twelve hours, so anything further away is a different
# day's match rather than a delayed one.
_SLOT_SLACK = timedelta(hours=12)


def _event_near(event, entry) -> bool:
    """Is this event the row's match, or the same fixture on another day?

    Two tests, because either alone lets a wrong day through:

    The day window catches an event from another week. It has to be wide — the
    sheet prints the venue's date and Sofascore stamps UTC, and those disagree
    for the whole night session at any American venue.

    That width is exactly what lets in the near miss: yesterday's session sits
    only a couple of hours outside today's midnight, so it passes the window
    while being the same fixture a day early. The printed start is a far sharper
    anchor, so when the row has one, the event has to be near THAT too.
    """
    ts = event.get("startTimestamp")
    if not ts:
        # No time yet: an upcoming match, which is the one being looked for.
        return True
    when = datetime.fromtimestamp(ts, tz=timezone.utc)

    day = datetime.combine(entry.play_date, time(0, 0), tzinfo=timezone.utc)
    if not (day - _DAY_FROM <= when <= day + _DAY_TO):
        return False

    # Only a PRINTED time may veto. `expected_start_at` is our own estimate
    # whenever the sheet gave no time, and an estimate is derived from the very
    # rows being matched — one wrong match skews it, and the skewed estimate
    # then rejects the right match. It gets a vote on nothing.
    slot = entry.expected_start_at if entry.expected_source == "printed" else None
    if slot is None:
        return True
    if slot.tzinfo is None:
        slot = slot.replace(tzinfo=timezone.utc)
    return abs(when - slot) <= _SLOT_SLACK


def _sheet_surnames(raw_names: list) -> set:
    """Surnames as the ORDER OF PLAY spells them.

    The sheet capitalises the surname and prints given names normally, so the
    all-caps token is the surname. Falls back to the last token for sheets that
    do not capitalise — some smaller events do not.
    """
    out = set()
    for raw in raw_names:
        for part in (raw or "").split("/"):
            part = _SHEET_TAGS.sub(" ", part)
            # Two letters, not three. "Li TU AUS" is a real entry and TU is a
            # real surname; at three the whole name vanished and the row could
            # never be matched. A two-letter particle ("de", "van") is lower
            # case on these sheets, so it is never mistaken for the surname.
            toks = [t for t in part.split() if len(t) >= 2]
            # A trailing three-letter capital is a COUNTRY only when a surname
            # already precedes it. Stripping every one of them cost this sweep
            # "Luca POW GBR" — POW is the surname — and the same shape eats LUZ,
            # GUO, RAM and LEE. Tested structurally rather than against a
            # country list, which would strand exactly the players whose surname
            # happens to be spelled like one.
            # STRIP EVERY trailing three-letter capital, not just one. A
            # Winston-Salem sheet printed "Dhakshineswar SURESH IND ANY";
            # removing one token left IND as the surname, so the row matched no
            # event, went unscored, and its estimated start ran away to 11:20pm
            # while the match had in fact finished at 5pm.
            #
            # Looping is safe for the same reason one pass was: the guard needs
            # ANOTHER capitalised token in front. "Luca POW GBR" gives up GBR
            # and then stops, because "Luca" is not capitalised and POW is the
            # surname. See the note above.
            while (len(toks) >= 2 and _THREE_CAPS.match(toks[-1])
                    and any(t.isupper() for t in toks[:-1])):
                toks = toks[:-1]
            # An INITIAL is uppercase too. "H. Nys" made caps == ["H."], so the
            # surname was thrown away and the initial kept — which is why a
            # doubles final could not be matched to the semi that fed it. A
            # capitalised surname has at least two letters; an initial has one.
            caps = [t for t in toks if t.isupper() and len(_ALPHA.sub("", t)) >= 2]
            out |= {t.lower() for t in (caps or toks[-1:])}
    return out


# ---------------------------------------------------------------- IDENTITY
#
# WHY THIS IS NOT SURNAME OVERLAP ANY MORE. Overlap counted how many of a row's
# surnames appeared anywhere in an event, which identifies PEOPLE, not a MATCH.
# On 2026-08-23 every one of Sunday's qualifying rows was wearing Saturday's
# result. A "winner of Bondar/Jacquemot" row literally contains both surnames,
# so the Q1 match that DECIDES that row scored a flawless two out of two; three
# Saturday events were each claimed by two rows at once; and one row had been
# holding a match from six days earlier, score and all, for a week.
#
# A match is not a bag of names. It is two sides, on a day, at a time, in a
# round, of a shape — and all of that is checked here, because each of those
# wrong matches satisfied the names and contradicted something else. Sofascore's
# own player ids settle it outright wherever we hold them, and every confident
# match writes back the ones we did not, so this gets more certain every day.

Person = namedtuple("Person", "surname initial pid ref",
                    defaults=(None, None))
Found = namedtuple("Found", "key flip pairs")


def _fold(text: str) -> str:
    """Letters only, lower case, no accents — the spelling both sides agree on.

    "Heliovaara"/"Heliovaara" and "Roger-Vasselin"/"Roger Vasselin" are the same
    surname spelled by two sources with different punctuation, and used to cost
    a name each.
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return _ALPHA.sub("", text).lower()


def _person(name: str, pid=None) -> Optional[Person]:
    """One player, however the source spells them.

    Both orders occur and a single trailing letter is what tells them apart,
    since no surname is one letter long:

        "Hugo Nys", "Alex De Minaur"   given name first, surname last
        "Nys H."                       surname first, initial last
    """
    toks = [t for t in (name or "").replace(".", " ").split() if _ALPHA.sub("", t)]
    if not toks:
        return None
    if len(toks) >= 2 and len(_ALPHA.sub("", toks[-1])) == 1:
        return Person(_fold(toks[0]), _fold(toks[-1])[:1], pid)
    return Person(_fold(toks[-1]), _fold(toks[0])[:1], pid)


def _sofa_people(team: dict) -> list:
    """The players on a Sofascore team, with their ids.

    A doubles team carries `subTeams`, which is the good path twice over: it
    gives each player's own id — the same id `draw_entries.sofa_player_id`
    holds — and their FULL name, where the team name only has "Nys H".
    """
    subs = team.get("subTeams")
    if subs:
        return [p for p in (_person(s.get("name"), s.get("id")) for s in subs) if p]
    name = team.get("name") or ""
    if "/" in name:
        return [p for p in (_person(part) for part in name.split("/")) if p]
    p = _person(name, team.get("id"))
    return [p] if p else []


def _sheet_people(raw_names: list, pids=None, ref=None) -> list:
    """The players on one side of the order of play.

    Surname extraction is the same reading as _sheet_surnames — the sheet prints
    the surname in capitals — and this keeps its two hard-won exceptions: a
    trailing three-letter capital is only a country when a surname precedes it
    ("Luca POW GBR" is a player called Pow), and a lone capital is an initial
    rather than a surname ("H. Nys").
    """
    out = []
    for i, raw in enumerate(raw_names):
        pid = pids[i] if pids and i < len(pids) else None
        for part in (raw or "").split("/"):
            part = _SHEET_TAGS.sub(" ", part)
            toks = [t for t in part.split() if len(t) >= 2]
            # STRIP EVERY trailing three-letter capital, not just one. A
            # Winston-Salem sheet printed "Dhakshineswar SURESH IND ANY";
            # removing one token left IND as the surname, so the row matched no
            # event, went unscored, and its estimated start ran away to 11:20pm
            # while the match had in fact finished at 5pm.
            #
            # Looping is safe for the same reason one pass was: the guard needs
            # ANOTHER capitalised token in front. "Luca POW GBR" gives up GBR
            # and then stops, because "Luca" is not capitalised and POW is the
            # surname. See the note above.
            while (len(toks) >= 2 and _THREE_CAPS.match(toks[-1])
                    and any(t.isupper() for t in toks[:-1])):
                toks = toks[:-1]
            caps = [t for t in toks if t.isupper() and len(_ALPHA.sub("", t)) >= 2]
            surname = _fold(caps[-1]) if caps else (_fold(toks[-1]) if toks else "")
            if not surname:
                continue
            initial = ""
            for t in part.split():
                letters = _ALPHA.sub("", t)
                if letters and _fold(t) != surname:
                    initial = letters[0].lower()
                    break
            out.append(Person(surname, initial, pid, ref[i] if ref else None))
    return out


def _same_person(ours: Person, theirs: Person) -> int:
    """2 certain, 1 by name, 0 unknown, -1 contradicted.

    An id disagreeing is a contradiction and not merely a miss: these are the
    same identifiers, so two different ones are two different people however
    alike the names read. Initials work the same way — Zverev A and Zverev M
    share every letter of the only token surname matching ever looked at.
    """
    if ours.pid and theirs.pid:
        return 2 if ours.pid == theirs.pid else -1
    if ours.surname and ours.surname == theirs.surname:
        if ours.initial and theirs.initial and ours.initial != theirs.initial:
            return -1
        return 1
    return 0


def _pair_side(ours: list, theirs: list):
    """Pair our side against their team one-to-one. None if it cannot be done.

    Sides are one or two people, so every assignment is tried rather than
    guessed at. Requiring one-to-one is the point: it is what stops one player
    appearing on our row from carrying a whole team.
    """
    if len(ours) != len(theirs) or not ours:
        return None
    best = None
    for perm in permutations(theirs):
        certain = matched = 0
        for a, b in zip(ours, perm):
            verdict = _same_person(a, b)
            if verdict < 0:
                break
            certain += verdict == 2
            matched += verdict >= 1
        else:
            key = (certain, matched)
            if best is None or key > best[0]:
                best = (key, list(zip(ours, perm)))
    return best


def _alternatives_ok(alts: list, theirs: list) -> bool:
    """For a side the sheet has not settled — "winner of X/Y" — is this them?

    The row names everyone it could be, so the test is containment: whoever
    Sofascore has must be one of the people the sheet listed. This is what lets
    a half-decided row still be scored, without letting the match that decides
    it be mistaken for it.
    """
    if not alts or not theirs or len(theirs) > len(alts):
        return False
    return all(any(_same_person(a, t) >= 1 for a in alts) for t in theirs)


def _round_key(text: str):
    """A round as ("q", n) or ("m", draw size), or None when unreadable.

    Both sources name rounds, in different words, and they must agree: a Q2 row
    is not the Q1 match that feeds it, however identical the four names are.
    """
    t = (text or "").lower()
    if not t:
        return None
    digits = re.search(r"\d+", t)
    if "qual" in t or re.fullmatch(r"f?q\d*", t.strip()):
        # ("q", 0) is a WILDCARD qualifying round. Sofascore calls the last one
        # "Qualification Final" and never numbers it, because which number it is
        # depends on the draw — two rounds at a tour event, three at a slam —
        # and our own sheets say "FQ" or a bare "Q" for the same reason. Reading
        # the missing digit as round 1 made every Q2 row reject its own match.
        # Being unnumbered is safe here: the numbered rounds still exclude each
        # other, and the day, the printed time and one-event-one-row all stand.
        if digits and "final" not in t:
            return ("q", int(digits.group()))
        return ("q", 0)
    if "quarter" in t or t.strip() == "qf":
        return ("m", 8)
    if "semi" in t or t.strip() == "sf":
        return ("m", 4)
    if "final" in t or t.strip() == "f":
        return ("m", 2)
    if digits:
        return ("m", int(digits.group()))
    return None


def _rounds_agree(event: dict, entry) -> bool:
    ours = _round_key(entry.round_label)
    info = event.get("roundInfo") or {}
    theirs = _round_key(info.get("name") or info.get("slug") or "")
    if ours is None or theirs is None:
        return True
    if ours[0] == "q" and theirs[0] == "q" and 0 in (ours[1], theirs[1]):
        return True
    return ours == theirs



def _match(entry, event: dict, sides: dict):
    """Is this event this row's match? Every gate, or nothing.

    Each of the wrong matches that prompted this satisfied the names and broke
    one of these, so none of them is optional:

      the day        an event from another week, six days stale
      the time       yesterday's session, two hours the wrong side of midnight
      the round      the Q1 match that DECIDES a Q2 row, sharing all its names
      the shape      one side pairing off against a team of a different size
      one-to-one     both people on our side being the same person on theirs
    """
    if not _event_near(event, entry):
        return None
    if not _rounds_agree(event, entry):
        return None

    teams = (_sofa_people(event.get("homeTeam") or {}),
             _sofa_people(event.get("awayTeam") or {}))
    tbd = entry.tbd_side or ""
    best = None
    for flip in (False, True):
        assign = (("a", teams[1 if flip else 0]), ("b", teams[0 if flip else 1]))
        certain = matched = settled = sure_sides = 0
        pairs, ok = [], True
        for side, theirs in assign:
            ours = sides.get(side) or []
            if side in tbd:
                # The sheet has not decided this side yet, so it is checked for
                # containment: whoever Sofascore has must be one of the people
                # the sheet listed. Both sides may be undecided — a Q2 match
                # between two pending Q1 winners is exactly that — and
                # containment on BOTH still identifies it, because only one of
                # the four possible pairings is a real event.
                if not _alternatives_ok(ours, theirs):
                    ok = False
                    break
                continue
            got = _pair_side(ours, theirs)
            if got is None or got[0][1] < 1:
                ok = False
                break
            certain += got[0][0]
            matched += got[0][1]
            settled += len(ours)
            sure_sides += 1
            pairs += got[1]
        if not ok:
            continue
        # One name may miss where there are three or more to go on — that is
        # what a diacritic or a hyphen costs. With only two there is no spare
        # name to be wrong about, so both have to land.
        if matched < settled - (1 if settled >= 3 else 0):
            continue
        key = (certain, matched, sure_sides)
        if best is None or key > best.key:
            best = Found(key, flip, pairs)
    return best


def _unclaim(entry) -> None:
    """Drop an event that no longer passes, and everything derived from it.

    THIS IS THE SELF-HEALING. Claims are re-checked on every sweep rather than
    trusted once, so a bad one lets go by itself and the row is free to match
    correctly on the next pass. Without it the Sunday rows would have kept
    Saturday's scores until somebody edited the database by hand.
    """
    entry.sofa_event_id = None
    entry.started_at = None
    entry.completed_at = None
    entry.winner_side = None
    entry.live_scores_json = None
    entry.live_point_json = None
    entry.scores_json = None
    entry.status = "scheduled"

async def _doubles_ids(db, draw: Draw, tournament: Tournament) -> Optional[tuple]:
    """(unique_tournament_id, season_id) for this draw's DOUBLES event.

    Sofascore keeps doubles as its own uniqueTournament — Cincinnati is 2373 /
    2548 for singles and 2381 / 2553 for doubles — so it has to be found rather
    than derived. Searched by the tournament's own name and filtered on both
    "Doubles" in the name and the right tour, because a combined event returns
    an ATP and a WTA doubles entry that are otherwise identical.
    """
    if draw.sofa_doubles_tournament_id and draw.sofa_doubles_season_id:
        return draw.sofa_doubles_tournament_id, draw.sofa_doubles_season_id

    want_cat = {"M": "ATP", "F": "WTA"}.get(draw.gender)

    # Search SOFASCORE'S OWN NAME for the singles event, not ours. Our name is
    # "Cincinnati Open" and theirs is "Cincinnati"; searching ours returns
    # nothing at all. This app already learned that lesson resolving the singles
    # draws — "French Open" is not indexed under that name either — and the
    # singles uniqueTournament id we are holding is the reliable way to ask them
    # what they call it.
    from urllib.parse import quote

    try:
        meta = await _get(f"/unique-tournament/{draw.sofa_tournament_id}")
        their_name = ((meta.get("uniqueTournament") or {}).get("name")
                      or (tournament.name or ""))
    except Exception:
        their_name = tournament.name or ""
    base = their_name.split("(")[0].strip()
    if not base:
        return None
    payload = await _get(f"/search/unique-tournaments?q={quote(base)}")
    cand = None
    for row in payload.get("results", []):
        ent = row.get("entity", {})
        name = ent.get("name") or ""
        cat = (ent.get("category") or {}).get("name")
        if "doubles" in name.lower() and cat == want_cat:
            cand = ent.get("id")
            break
    if not cand:
        return None

    seasons = await _get(f"/unique-tournament/{cand}/seasons")
    # `year` is a STRING here, as it is on the singles seasons endpoint.
    season = next((s for s in seasons.get("seasons", [])
                   if str(s.get("year")) == str(draw.year)), None)
    if not season:
        return None

    draw.sofa_doubles_tournament_id = cand
    draw.sofa_doubles_season_id = season["id"]
    await db.commit()
    await app_log("info", "sofascore_doubles",
                  f"Resolved doubles event for {tournament.name} {draw.gender}: "
                  f"ut={cand} season={season['id']}",
                  detail={"draw_id": draw.id})
    return cand, season["id"]


async def _mixed_ids(db, tournament: Tournament, draw: Draw) -> Optional[tuple]:
    """_doubles_ids for the MIXED event — a third uniqueTournament beside the
    gendered pairs ("US Open Mixed Doubles"), stored on the tournament since
    there is one mixed championship per event. `draw` is any resolved draw of
    the tournament: its singles id supplies Sofascore's own name to search by,
    and its year picks the season, exactly as the doubles resolver does. No
    tour-category filter here — mixed is neither ATP nor WTA."""
    if tournament.sofa_mixed_tournament_id and tournament.sofa_mixed_season_id:
        return tournament.sofa_mixed_tournament_id, tournament.sofa_mixed_season_id
    from urllib.parse import quote
    try:
        meta = await _get(f"/unique-tournament/{draw.sofa_tournament_id}")
        their_name = ((meta.get("uniqueTournament") or {}).get("name")
                      or (tournament.name or ""))
    except Exception:
        their_name = tournament.name or ""
    base = their_name.split("(")[0].strip()
    # Sofascore's own singles name is GENDERED — "US Open, Men" — and a search
    # for that never returns the mixed event at all. The family name is what
    # indexes it ("US Open" finds "US Open, Mixed Doubles").
    base = re.sub(r",\s*(?:Men|Women)$", "", base).strip()
    if not base:
        return None
    payload = await _get(f"/search/unique-tournaments?q={quote(base)}")
    cand = None
    for row in payload.get("results", []):
        ent = row.get("entity", {})
        name = (ent.get("name") or "").lower()
        # Anchored on the family name, or the 2018 wheelchair edition
        # ("US Open (WT) 2018, Mixed Doubles") is one list position away.
        if (name.startswith(base.lower())
                and "mixed" in name and "doubles" in name):
            cand = ent.get("id")
            break
    if not cand:
        return None
    seasons = await _get(f"/unique-tournament/{cand}/seasons")
    season = next((s for s in seasons.get("seasons", [])
                   if str(s.get("year")) == str(draw.year)), None)
    if not season:
        return None
    tournament.sofa_mixed_tournament_id = cand
    tournament.sofa_mixed_season_id = season["id"]
    await db.commit()
    await app_log("info", "sofascore_doubles",
                  f"Resolved mixed doubles event for {tournament.name}: "
                  f"ut={cand} season={season['id']}",
                  detail={"tournament_id": tournament.id})
    return cand, season["id"]


def _has_sets(snap) -> bool:
    """Does this snapshot actually carry a score?

    Sofascore numbers sets period1..period5 and _sets_and_tiebreak returns an
    EMPTY list when the payload carries none of them. That happens between
    updates on a match that is very much in progress — it is the feed having
    nothing to say this second, not the score being nothing.
    """
    return bool((snap or {}).get("sets"))


def _snapshot(event: dict) -> dict:
    """The live point state, in the same shape the singles poller produces."""
    home, away = event.get("homeScore") or {}, event.get("awayScore") or {}
    sets, tiebreak, match_tb = _sets_and_tiebreak(home, away)
    return {
        "sets": sets,
        "point": [_norm_point(home.get("point"), tiebreak),
                  _norm_point(away.get("point"), tiebreak)],
        "tiebreak": tiebreak,
        "match_tiebreak": match_tb,
        "serving": event.get("firstToServe") if event.get("firstToServe") in (1, 2) else None,
        "at": datetime.now(timezone.utc).isoformat(),
    }


async def sweep_once(db, day: Optional[date] = None) -> dict:
    """Resolve unmatched doubles rows, then score every one we can."""
    """day is the LATEST day swept; yesterday is swept with it."""
    day = day or date.today()
    # YESTERDAY TOO. The server clock is UTC and venues are not: in Monterrey
    # the date rolls over at 6pm local, mid-session, so a match still on court
    # becomes "yesterday" and was never looked at again. Three of Monterrey's
    # eight qualifiers froze that way — one of them still reading "scheduled"
    # while the player who beat her was on court in the next round.
    # Two days, not a window: a sheet is published a day ahead and finished the
    # same night, so anything older than that is not going to change.
    days = [day - timedelta(days=1), day]

    # Everything on the sheet with no bracket row behind it. Main-draw singles
    # is excluded because it HAS one: it scores through `matches`, and letting
    # it also match here would give one match two writers.
    entries = (await db.execute(
        select(ScheduleEntry).where(
            or_(ScheduleEntry.discipline != "singles",
                ScheduleEntry.stage == "qualifying"),
            ScheduleEntry.play_date.in_(days),
        ))).scalars().all()
    if not entries:
        return {"entries": 0, "resolved": 0, "scored": 0}

    # Draws carry the pointer to the doubles event; a tournament with no tracked
    # draw is not one we follow.
    draws = (await db.execute(
        select(Draw).where(Draw.tournament_id.in_({e.tournament_id for e in entries}),
                           Draw.sofa_tournament_id.isnot(None)))).scalars().all()
    if not draws:
        return {"entries": len(entries), "resolved": 0, "scored": 0}
    tourns = {t.id: t for t in (await db.execute(
        select(Tournament).where(
            Tournament.id.in_({d.tournament_id for d in draws})))).scalars().all()}

    # One events pull per doubles season, shared by every row that needs it.
    by_season, events = {}, []
    # Qualifying is NOT a separate uniqueTournament — Sofascore files it under
    # the singles one, distinguished only by the sub-tournament name
    # ("Winston Salem, USA, Qualifying") and the round. So a tournament with
    # qualifying rows today needs its singles season pulled as well, and the
    # surname match sorts out which event belongs to which row.
    quali_tournaments = {e.tournament_id for e in entries
                         if e.discipline == "singles" and e.stage == "qualifying"}
    # Mixed is a third event again — one per TOURNAMENT, resolved through any
    # draw that already knows its Sofascore singles id.
    mixed_tournaments = {e.tournament_id for e in entries
                         if e.discipline == "mixed"}
    for d in draws:
        ids = await _doubles_ids(db, d, tourns.get(d.tournament_id))
        if ids:
            by_season[(d.tournament_id, d.gender)] = ids
        if (d.tournament_id in quali_tournaments
                and d.sofa_tournament_id and d.sofa_season_id):
            by_season[(d.tournament_id, d.gender, "q")] = (d.sofa_tournament_id,
                                                           d.sofa_season_id)
        if d.tournament_id in mixed_tournaments and d.sofa_tournament_id:
            t = tourns.get(d.tournament_id)
            if t is not None and (d.tournament_id, "x") not in by_season:
                ids = await _mixed_ids(db, t, d)
                if ids:
                    by_season[(d.tournament_id, "x")] = ids
    for ut, season in set(by_season.values()):
        for kind in ("last", "next"):
            # Same rule as sofascore_results: the writer never waits at the
            # pacing gate. _doubles_ids ratchets ids back onto entries above,
            # and holding those dirty rows through a queued fetch is the
            # write-lock storm of 2026-08-25 in a second costume.
            await db.commit()
            try:
                payload = await _get(
                    f"/unique-tournament/{ut}/season/{season}/events/{kind}/0")
            except SofascoreBlocked:
                raise
            except SofascoreNotFound:
                # No upcoming doubles in this season — the ordinary state of a
                # tournament on its final day, and of every tournament after it.
                # The `last` page is the one that matters by then, and it must
                # still be read: that is where the results are.
                continue
            except Exception as exc:
                logger.warning("doubles %s page failed for ut %s: %s", kind, ut, exc)
                continue
            events += payload.get("events") or []

    players = {}
    for row in (await db.execute(
            select(ScheduleEntryPlayer).where(
                ScheduleEntryPlayer.schedule_entry_id.in_([e.id for e in entries])))).scalars().all():
        players.setdefault(row.schedule_entry_id, []).append(row)

    # Whatever Sofascore ids we already hold for these people. This is the
    # strong identifier, and the reason the matching gets more certain over
    # time: every confident match below writes back the ones that were missing,
    # so a player matched by name today is matched by id tomorrow.
    de_ids = {p.draw_entry_id for rows in players.values() for p in rows
              if p.draw_entry_id}
    draw_entries = {d.id: d for d in (await db.execute(
        select(DrawEntry).where(DrawEntry.id.in_(de_ids)))).scalars().all()} if de_ids else {}
    taken = set()
    if draw_entries:
        taken = {(d.draw_id, d.sofa_player_id) for d in (await db.execute(
            select(DrawEntry).where(
                DrawEntry.draw_id.in_({d.draw_id for d in draw_entries.values()}),
                DrawEntry.sofa_player_id.isnot(None)))).scalars().all()}

    sides_of = {}
    for e in entries:
        grouped = {}
        for pl in players.get(e.id, []):
            grouped.setdefault(pl.side, []).append(pl)
        sides_of[e.id] = {
            side: _sheet_people(
                [pl.raw_name for pl in rows],
                [(draw_entries.get(pl.draw_entry_id).sofa_player_id
                  if draw_entries.get(pl.draw_entry_id) else None) for pl in rows],
                rows)
            for side, rows in grouped.items()}

    by_id = {ev["id"]: ev for ev in events}
    resolved = scored = 0

    # A claim is re-checked, never trusted. A row holding an event that no
    # longer passes lets go of it here and is free to match properly below.
    for e in entries:
        if not e.sofa_event_id:
            continue
        held = by_id.get(e.sofa_event_id)
        if held is not None and _match(e, held, sides_of[e.id]) is None:
            await app_log("warning", "sofascore_doubles",
                    f"dropped event {e.sofa_event_id} from schedule row {e.id} "
                    f"({e.play_date} {e.round_label}) — it no longer identifies "
                    f"this match")
            _unclaim(e)

    # ONE EVENT, ONE ROW. Three of Saturday's events were each being scored
    # into two different rows at once, which is how Sunday's sheet came to be
    # showing Saturday's results. Rows propose, the best proposal wins, and an
    # event that is already spoken for is not on offer.
    claimed = {e.sofa_event_id for e in entries if e.sofa_event_id}
    proposals = []
    for e in entries:
        if e.sofa_event_id:
            continue
        best = runner = chosen = None
        for cand in events:
            if cand["id"] in claimed:
                continue
            got = _match(e, cand, sides_of[e.id])
            if got is None:
                continue
            if best is None or got.key > best.key:
                best, runner, chosen = got, best, cand
            elif runner is None or got.key > runner.key:
                runner = got
        if best is None:
            continue
        if runner is not None and runner.key == best.key:
            # Two events fit equally well, so neither is identified. Saying so
            # and waiting is right: one of them is the wrong match, and there is
            # nothing here to tell which.
            await app_log("warning", "sofascore_doubles",
                    f"schedule row {e.id} ({e.play_date} {e.round_label}) "
                    f"matches more than one event equally well — left unresolved")
            continue
        proposals.append((best.key, e, chosen, best))

    proposals.sort(key=lambda x: x[0], reverse=True)
    for _key, e, cand, got in proposals:
        if cand["id"] in claimed:
            continue
        e.sofa_event_id = cand["id"]
        claimed.add(cand["id"])
        resolved += 1
        # The ratchet: write down the ids this match just proved.
        for ours, theirs in got.pairs:
            entry = draw_entries.get(ours.ref.draw_entry_id) if ours.ref else None
            if (entry is None or entry.sofa_player_id or not theirs.pid
                    or (entry.draw_id, theirs.pid) in taken):
                continue
            entry.sofa_player_id = theirs.pid
            taken.add((entry.draw_id, theirs.pid))

    for e in entries:
        ev = by_id.get(e.sofa_event_id) if e.sofa_event_id else None
        if ev is None:
            continue
        # Which side of OUR row is Sofascore's home team? The sheet's order and
        # theirs need not agree, and getting it backwards would credit the win
        # to the wrong pair. This comes out of the match itself now rather than
        # being guessed at separately — it is the orientation that made the two
        # sides pair off one-to-one.
        got = _match(e, ev, sides_of[e.id])
        if got is None:
            continue
        flip = got.flip

        status = (ev.get("status") or {}).get("type")
        code = (ev.get("status") or {}).get("code", 100)
        wc = ev.get("winnerCode")

        if status == "inprogress":
            snap = _snapshot(ev)
            # First sighting of play, on the same terms as the singles poller:
            # `startTimestamp` is the announced slot rather than the first
            # point, so it is only used when games are already on the board and
            # we plainly missed the start.
            if e.started_at is None:
                played = sum((x[0] or 0) + (x[1] or 0) for x in (snap.get("sets") or []))
                ts = ev.get("startTimestamp")
                if played == 0:
                    e.started_at = datetime.now(timezone.utc)
                    scored += 1
                elif ts:
                    e.started_at = datetime.fromtimestamp(ts, tz=timezone.utc)
                    scored += 1
            if flip:
                snap["sets"] = [[b, a] for a, b in snap["sets"]]
                snap["point"] = [snap["point"][1], snap["point"][0]]
                if snap["serving"] in (1, 2):
                    snap["serving"] = 3 - snap["serving"]
            live = _as_espn_shape(snap)
            # snap carries its own `at`, which differs on every sweep, so this
            # always writes — which is what keeps the stamp inside freshness for
            # a doubles row. The singles poller compares without the stamp and
            # has to refresh it deliberately; see the note there.
            # A BLANK SNAPSHOT NEVER REPLACES A REAL ONE. An in-progress match
            # whose payload carries no periods at all is the feed between
            # updates; writing it through blanked the score on screen until the
            # next sweep put it back, which is the "score disappears, comes back
            # a moment later" everyone sees. Nothing is lost by keeping the last
            # good one — the next sweep overwrites it with the real thing.
            if _has_sets(snap) or not _has_sets(e.live_point_json):
                if e.live_scores_json != live or e.live_point_json != snap:
                    # HISTORY, on real change only. `snap.at` differs on every
                    # sweep so the outer condition always fires; comparing
                    # without it is what separates "the score moved" from "the
                    # stamp was refreshed" — same split the singles poller
                    # documents. Wrapped so a history failure can never cost
                    # the score write it rides beside.
                    prev = dict(e.live_point_json or {}); prev.pop("at", None)
                    cur = dict(snap); cur.pop("at", None)
                    if prev != cur:
                        try:
                            from app.services.score_history import record_entry_snapshot
                            record_entry_snapshot(db, e.id, snap)
                        except Exception:
                            logger.exception(
                                "entry score history insert failed for %s", e.id)
                    e.live_scores_json = live
                    e.live_point_json = snap
                    e.status = "live"
                    scored += 1
        elif status == "finished" and wc in (1, 2):
            final = _final_scores(ev.get("homeScore") or {}, ev.get("awayScore") or {},
                                  code, wc)
            if final and flip:
                final = [final[1], final[0]]
            # A match that finished before we ever saw it live has no observed
            # start. The announced slot is the only thing left, and it beats
            # showing nothing on a completed row.
            if e.started_at is None and ev.get("startTimestamp"):
                e.started_at = datetime.fromtimestamp(
                    ev["startTimestamp"], tz=timezone.utc)
                scored += 1

            side = ("a" if wc == 1 else "b") if not flip else ("b" if wc == 1 else "a")
            if e.scores_json != final or e.winner_side != side:
                e.scores_json = final
                e.winner_side = side
                e.status = "completed"
                e.live_scores_json = None
                e.live_point_json = None
                # When the court freed. Only on the transition — re-stamping it
                # on every sweep would walk the time forward for as long as the
                # row stays in the day's window, and push everything chained
                # behind it forward with it.
                if e.completed_at is None:
                    e.completed_at = datetime.now(timezone.utc)
                scored += 1

    if resolved or scored:
        await db.commit()
    return {"entries": len(entries), "resolved": resolved, "scored": scored}


class SofascoreDoublesMonitor:
    """Self-managed loop, in the shape the other two pollers use."""

    BLOCKED_BACKOFF = 1800.0

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        from app.database import AsyncSessionLocal

        logger.info("Sofascore doubles sweep started (interval=%ss)", POLL_INTERVAL)
        while not self._stop.is_set():
            delay = POLL_INTERVAL
            try:
                async with AsyncSessionLocal() as db:
                    report = await sweep_once(db)
                    if report.get("resolved") or report.get("scored"):
                        logger.info("Sofascore doubles: %s", report)
                        from app.services import broadcaster
                        for tid in {e for e in
                                    (await db.execute(select(ScheduleEntry.tournament_id)
                                                      .where(ScheduleEntry.play_date >= date.today() - timedelta(days=1))
                                                      )).scalars().all()}:
                            await broadcaster.publish(tid)
            except SofascoreBlocked as exc:
                delay = self.BLOCKED_BACKOFF
                await app_log("warning", "sofascore_doubles",
                              f"Doubles sweep paused {self.BLOCKED_BACKOFF / 60:.0f}m ({exc})",
                              dedup_key="sofa_doubles_blocked", dedup_hours=1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Sofascore doubles sweep failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass


monitor = SofascoreDoublesMonitor()
