"""The WTA's own schedule, as JSON, instead of parsing their order-of-play PDF.

    https://api.wtatennis.com/tennis/tournaments/{event_id}/{year}/matches

Public, unauthenticated, and keyed by the SAME id that appears in the PDF URL
we already fetch — wtafiles.wtatennis.com/pdf/draws/2026/1039/OP.pdf is event
1039 — so nothing has to be mapped or looked up.

Per match it states the things a sheet only implies through layout:
MatchTimeStamp the time, isEstimatedStartTime whether that time is a promise or
a guess (the "Followed by" case), and RoundID the round. DateSeq is NOT the
order on court — it numbers the tournament's day (every SP Open court shared
DateSeq 5 on 2026-09-16), so the order is the clocks'.
It also carries seeds, entry types, nationalities and tour player ids, which a
PDF makes us recover from printed text.

WHAT IT DOES NOT GIVE is the court's NAME. Tour events carry CourtID only — 1,
2, 3 — while the Slams carry Venue.name as well. `court_names` lets a caller
supply the mapping it has (learned from a sheet we already ingested, or from
Sofascore, which names courts at every level), keyed `court_id_key` — never
"Court {id}", which is a name real courts are called. Without a learned name the
row has NO court: the caller takes Sofascore's court for the same match or
gives the day to the sheet, and never guesses.

TWO SHAPES OF ROW. The above is a match that has been PLAYED (or is on court):
CourtID, DateSeq, the real start time. A match that has only been PUBLISHED —
the next day's sheet, or the rest of today's — comes in another shape entirely
(Singapore's and Korea's qualifying, 2026-09-19): no CourtID and no DateSeq,
but `CourtName` ("Center Court"), `NotBefore` ("Starting at 11:00 AM", "Not
before 5:00 PM", "Followed By"), and `Unscheduled: true` on every "Followed
By" row, whose MatchTimeStamp is the 23:59 placeholder. That shape does NOT
say in which order the "Followed By" matches come — the array is in no court
order, nor is MatchID — so `unordered_courts` names the courts a caller must
not take from this feed.
"""

import logging
from datetime import date, datetime
from typing import Optional
from urllib.request import Request, urlopen

from app.services.oop_parser import (COUNTRY_CODES, NEUTRAL_NATIONS, Match,
                                     feed_order)

logger = logging.getLogger(__name__)

BASE = "https://api.wtatennis.com/tennis/tournaments"
# The API answers plain urllib, but a site that fronts Cloudflare can start
# refusing the default python-urllib agent without warning; this is the same
# browser string the rest of the codebase sends.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json",
}
TIMEOUT = 20

# RoundID as the feed states it, in the vocabulary the rest of the site uses.
_ROUNDS = {"F": "F", "S": "SF", "Q": "QF", "1": "R1", "2": "R2", "3": "R3",
           "4": "R4", "5": "R5", "6": "R6", "7": "R7"}


def fetch_matches(event_id: int, year: int) -> list[dict]:
    """Every match the WTA holds for this event — all days, all draws."""
    url = f"{BASE}/{event_id}/{year}/matches"
    with urlopen(Request(url, headers=HEADERS), timeout=TIMEOUT) as r:
        import json
        payload = json.loads(r.read().decode("utf-8"))
    return payload.get("matches") or []


def event_id_from_pdf_url(url: Optional[str]) -> Optional[int]:
    """1039 out of .../pdf/draws/2026/1039/OP.pdf — the id we already hold."""
    import re
    m = re.search(r"/draws/\d{4}/(\d+)/", url or "")
    return int(m.group(1)) if m else None


def _name(first: str, last: str, country: str = "", mark: str = "") -> str:
    """One player in SHEET FORM — "[WC] Gaeul JANG KOR" — because the
    stored name IS the page's rendering, and every reader of it was written
    against the sheet.

    This returned the plain "Alexandra Shubladze", on the reasoning that the
    ingest normalises before matching. Matching is not the only reader. The
    first feed days (2026-09-18, 10:13 UTC) re-stamped forty rows out of sheet
    form and `name_not_sheet_form` convicted every one — rightly: the serve
    path reads a qualifying or doubles row's seed and entry type off the
    name's bracket (`_printed_mark`), so every [2] and [WC] left the page, and
    the readers that find a surname by its capitals (the frontend's
    parseSheetName, `_sheet_surnames`) fell back to the LAST word, which makes
    Beatriz Haddad Maia a Ms Maia. The feed names the surname outright, so
    capitalising it guesses nothing. uso_feed._person builds the same form.

    The COUNTRY goes on the end as the sheet prints it, and only a code we
    know (anything else would be `name_trailing_noncountry`). Without it a
    three-letter surname is the name's last token, and the readers that strip
    a trailing code take it for one: `_fold` would read "Eunhye LEE" as plain
    "eunhye", `_clean_name` "Priscilla HON" as a Honduran called Priscilla.

    A row without both names is a role, not a person, and stays as written.
    """
    first, last = (first or "").strip(), (last or "").strip()
    if not (first and last):
        return first or last
    code = (country or "").strip().upper()
    return " ".join(p for p in (mark, first, last.upper(),
                                code if code in COUNTRY_CODES else "") if p)


def _mark(m: dict, side: str) -> str:
    """The bracket a sheet prints before a side: the seed, else the entry type.

    Once per SIDE, on its first player — a doubles seed belongs to the team,
    and SP Open prints "[2] Valeriya STRAKHOVA UKR" over a bare "Anastasia
    TIKHONOVA"."""
    seed = str(m.get(f"Seed{side}") or "").strip()
    entry = str(m.get(f"EntryType{side}") or "").strip()
    return f"[{seed or entry}]" if (seed or entry) else ""


def _side(m: dict, side: str) -> tuple[list, list]:
    """One side's players and their nations, doubles included (the A2/B2 pair)."""
    names, nations = [], []
    mark = _mark(m, side)
    for suffix in ("", "2"):
        country = (m.get(f"PlayerCountry{side}{suffix}") or "").strip()
        # The feed states what the sheet withholds (Samsonova "RUS",
        # Guadalajara 2026-09-18), and the name's trailing code and the nation
        # each become a flag on the page. See oop_parser.NEUTRAL_NATIONS.
        if country.upper() in NEUTRAL_NATIONS:
            country = ""
        nm = _name(m.get(f"PlayerNameFirst{side}{suffix}"),
                   m.get(f"PlayerNameLast{side}{suffix}"),
                   country, "" if names else mark)
        if nm:
            names.append(nm)
            nations.append(country)
    return names, nations


# A WALKOVER WAS NEVER ON COURT, so its MatchTimeStamp is not a start: it is
# the moment the result was ENTERED. SP Open 2026-09-18: Dabrowski/Stefani's
# doubles QF, printed "After suitable rest - NB 4pm" as QUADRA 1's second
# match, went w/o when Quevedo walked on for her singles, and the feed stamped
# it 15:48:22 UTC — 12:48 PM local, MatchTimeTotal 00:00:00. Read as the played
# shape's real start, that became a FIXED "12:48" written over the sheet's
# wording, under the court's 2:00 PM opener (`printed_clock_runs_backwards`),
# and it sorted the walkover FIRST on its court. The score fields that say so
# are volatile and stripped from the stored bytes (normalize_day), so the fact
# is kept there under its own key: it changes once, when the w/o is entered,
# which is a real revision of the day.
_WALKOVER_KEY = "Walkover"


def _is_walkover(m: dict) -> bool:
    if m.get(_WALKOVER_KEY):
        return True
    import re
    # The result line carries names too, so only the slashed form counts there.
    return bool(re.search(r"\bW/?O\b", str(m.get("ScoreString") or ""), re.I)
                or re.search(r"\bW/O\b", str(m.get("ResultString") or ""), re.I))


def _parse_ts(ts: str) -> datetime:
    """The feed's stamp as a datetime. It writes as many fractional digits as
    it likes ("03:04:16.44"), which Python 3.10's fromisoformat refuses — so
    they are padded to six first."""
    import re
    ts = re.sub(r"(\.\d{1,5})(?=\D|$)", lambda f: f.group(1).ljust(7, "0"), ts.replace("Z", "+00:00"))
    return datetime.fromisoformat(ts)


def _local_hhmm(ts: Optional[str], venue_tz: Optional[str]) -> Optional[str]:
    if not ts or len(ts) < 16:
        return None
    if not venue_tz:
        return ts[11:16]
    try:
        from zoneinfo import ZoneInfo
        dt = _parse_ts(ts)
        return dt.astimezone(ZoneInfo(venue_tz)).strftime("%H:%M")
    except Exception:
        return ts[11:16]


def play_date_of(m: dict, venue_tz: Optional[str] = None) -> Optional[date]:
    """The day the SHEET would file this match under, which is the venue's day.

    The feed stamps UTC, so a Monterrey night match at 01:16 UTC is 19:16 the
    previous evening on site. Taking the UTC date moved every night match onto
    the next day's sheet — the staging run showed it immediately: 4 matches on
    2026-08-29 against the 2 the tournament actually played.
    """
    ts = m.get("MatchTimeStamp")
    if not ts:
        return None
    try:
        dt = _parse_ts(ts)
    except ValueError:
        return None
    if venue_tz:
        try:
            from zoneinfo import ZoneInfo
            return dt.astimezone(ZoneInfo(venue_tz)).date()
        except Exception:
            pass
    return dt.date()


def court_id_key(cid) -> str:
    """The learned mapping's key for a numbered court — a string no court is
    ever called.

    It was "Court {id}", which IS a court's name at Singapore: CourtID 1 is
    CENTER COURT there and "Court 1" is COURT 1, both voted under the one key,
    and the 106 votes Sofascore's "Court 1" cast outweighed the 14 the played
    CourtID 1 rows did. From 14:41 local on 2026-09-19 every Center Court
    match that had been played was filed on COURT 1 (feed document 328), and
    the court's one unplayed "Followed By" match was left opening it
    (`court_opener_untimed`). Guessing "Court {id}" for an unmapped id made the
    same mistake with no mapping at all.
    """
    return f"CourtID {cid}"


def matches_for_day(rows: list[dict], day: date,
                    court_names: Optional[dict] = None,
                    venue_tz: Optional[str] = None) -> list[Match]:
    """The feed's rows for one day, in the shape the schedule ingest takes.

    Ordered by court then DateSeq, so the ingest sees a sheet's reading order
    without having to reconstruct it from positions on a page.
    """
    court_names = court_names or {}
    out = []
    for m in rows:
        if play_date_of(m, venue_tz) != day:
            continue
        cid = str(m.get("CourtID") or "").strip()
        venue = (m.get("Venue") or {}).get("name")
        # A PUBLISHED match names its court outright and has no CourtID (see
        # the module docstring). Reading CourtID alone put Singapore's and
        # Korea's whole qualifying day on one blank court, eight matches
        # chained to 11:36 PM (2026-09-19, documents 306/307). The name goes
        # through the learned mapping first — "Estadio Skarch" is the sheet's
        # "ESTADIO SKARCH".
        named = (m.get("CourtName") or "").strip()
        # A numbered court is looked up, and voted for, under its own key and
        # nothing else (see court_id_key); unmapped, it is no court at all.
        id_key = court_id_key(cid) if cid and not venue and not named else None
        court = (venue or (court_names.get(named) if named else None)
                 or (court_names.get(id_key) if id_key else None)
                 or named or "")
        # VENUE-LOCAL, like the sheet prints. The feed stamps UTC, so a
        # Monterrey night match reads 01:36 raw — tomorrow's date, and an hour
        # nobody played at. Without the zone the raw value is kept rather than
        # guessed at, and the caller can see it is unconverted.
        hhmm = _local_hhmm(m.get("MatchTimeStamp"), venue_tz)
        estimated = bool(m.get("isEstimatedStartTime"))
        # A MATCH NOT YET PLACED: the feed stamps it 23:59 with no court and no
        # order (Guadalajara 2026-09-18, Samsonova v Stearns). That is a
        # placeholder, not a time — printed as "11:59 PM" it would be a lie.
        if (m.get("MatchTimeStamp") or "")[11:16] == "23:59" and not m.get("DateSeq") and not cid:
            hhmm = None
        # Nor is a walkover's stamp a time (see _is_walkover). No clock and no
        # wording is the sheet's own silence over a w/o box, and ingest keeps
        # the wording an earlier revision printed for exactly that case.
        if _is_walkover(m):
            hhmm = None
        names_a, nats_a = _side(m, "A")
        names_b, nats_b = _side(m, "B")
        # The ROUND of an unplaced match is a placeholder too. Every placed
        # match states RoundID as a STRING ("1", "2", "Q", "S", "F"); the
        # unplaced ones carry a bare INTEGER — 2 on Guadalajara's three
        # semi-finals (2026-09-18), 11 on Korea's and Singapore's next-day
        # qualifying — which is no round at all. Read as "2" it made every
        # semi-final an "R2", and ingest takes the feed's round over the
        # bracket's. None leaves the round to the bracket and the row.
        rid = m.get("RoundID")
        rnd = _ROUNDS.get(rid.strip()) if isinstance(rid, str) else None
        # A published match carries the sheet's own wording. Without it "Not
        # before 5:00 PM" was stored as a fixed 17:00 (Guadalajara's Bucsa v
        # Jovic, 2026-09-18), and the chain lost the floor.
        printed = (m.get("NotBefore") or "").strip()
        out.append(Match(
            court=court,
            time=hhmm,
            tour="WTA",
            round=rnd,
            discipline=("doubles" if (m.get("DrawMatchType") or "").upper() == "D"
                        else "singles"),
            # The feed states the time's standing outright, where a sheet makes
            # us read it off wording like "Followed by".
            start_raw=(printed or (f"Est. {hhmm}" if estimated and hhmm else hhmm)),
            printed_score=(m.get("ScoreString") or None),
            printed_status=(m.get("MatchState") or None),
            side_a=names_a, side_b=names_b,
            nations_a=nats_a, nations_b=nats_b,
            published=not cid,
            court_key=id_key,
        ))
    out.sort(key=feed_order)
    return out


def unordered_courts(matches: list[Match]) -> list[str]:
    """The courts whose order of play these rows do NOT state.

    `feed_order` sorts a court by its clocks, untimed last, and that is a
    reading of the feed only while the clocks decide it. They do not when a
    court holds two or more unplayed rows with no clock — the published
    "Followed By" matches, which the feed lists in no court order — or one such
    row and an unplayed timed row after the court's first, since a "Followed
    by" may come before a "Not before 5:00 PM" as easily as after it. Two
    unplayed rows at one clock are no order either. Singapore 2026-09-19: the
    sheet prints Garland v Perez third on CENTER COURT, the feed's own order
    fourth.

    A row in the PLAYED shape (it has a CourtID) carries its real start, so it
    precedes everything still to be played and never makes a court ambiguous.
    MatchState cannot say which rows have begun here: normalize_day strips it
    from the stored bytes as volatile.
    """
    by_court: dict = {}
    for m in matches:
        by_court.setdefault(m.court or "", []).append(m)
    out = []
    for court, ms in by_court.items():
        untimed = [m for m in ms if m.published and not m.time]
        timed = sorted((m for m in ms if m.time), key=lambda m: m.time)
        later = [m for m in timed[1:] if m.published]
        clocks = [m.time for m in ms if m.published and m.time]
        if (len(untimed) > 1 or (untimed and later)
                or len(set(clocks)) < len(clocks)):
            out.append(court)
    return out


def days_available(rows: list[dict],
                   venue_tz: Optional[str] = None) -> list[date]:
    return sorted({d for d in (play_date_of(m, venue_tz) for m in rows) if d})


# Fields that change while a match is played. They are stripped before the
# day's bytes are stored, for the reason the US Open feed taught us: hashing a
# payload that re-serialises its live score on every publish calls every point
# a schedule revision.
_VOLATILE = ("ScoreString", "ScoreSys", "ResultString", "Winner", "MatchState",
             "LastUpdated", "MatchTimeTotal", "PointA", "PointB", "Serve",
             "NumSets", "Message")


def normalize_day(rows: list[dict], day: date,
                  venue_tz: Optional[str] = None) -> bytes:
    """One day's rows as stable bytes: volatile fields dropped, keys sorted.

    A document per DAY, not per tournament, so a revision to Tuesday does not
    look like a revision to Monday — the same shape the PDF ingest already
    stores and the same one revision counting depends on.
    """
    import json
    keep = []
    for m in rows:
        if play_date_of(m, venue_tz) != day:
            continue
        row = {k: v for k, v in sorted(m.items())
               if k not in _VOLATILE and not str(k).startswith("ScoreSet")
               and not str(k).startswith("ScoreTb")}
        # Absent unless true, so a day with no walkover hashes as it always did.
        if _is_walkover(m):
            row[_WALKOVER_KEY] = True
        keep.append(row)
    keep.sort(key=lambda m: (str(m.get("CourtID") or ""),
                             str(m.get("DateSeq") or ""), str(m.get("MatchID") or "")))
    return json.dumps(keep, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_wta_day(doc: bytes, court_names: Optional[dict] = None,
                  venue_tz: Optional[str] = None):
    """(matches, meta) from bytes written by normalize_day — the signature
    ingest_document expects of a parser."""
    import json
    rows = json.loads(doc.decode("utf-8"))
    day = next((d for d in (play_date_of(m, venue_tz) for m in rows) if d), None)
    matches = (matches_for_day(rows, day, court_names=court_names,
                               venue_tz=venue_tz) if day else [])
    return matches, {"source": "wta-api", "day": day.isoformat() if day else None,
                     "count": len(matches)}
