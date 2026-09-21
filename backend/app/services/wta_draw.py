"""THE WTA'S OWN DRAW SHEET, AS JSON — the official shape, no PDF, no Wikipedia.

    https://api.wtatennis.com/tennis/tournaments/{event_id}/{year}/draw

Public, unauthenticated, and keyed by the same event id `wta_feed` already uses
for the order of play (Tournament.wta_live_scoring_id). Found 2026-09-21 while
looking for a reliable JSON draw source: the response carries `drawInfo`, a
JSON DOCUMENT AS A STRING, which is the tour's draw sheet:

    Draws.Events.Event[]          one per event: LS singles, LD doubles,
                                  RS singles qualifying
      .Draw.DrawLine[]            ONE LINE PER SLOT, Pos 1..DrawSize
        Pos, Seed, EntryType      slot, seed number, "" / Q / WC / ALT
        DisplayLine               "Marta Kostyuk", or "Bye"
        Rank                      the entry ranking
        Players.Player            {id, FirstName, SurName, Country, ...}
                                  a Bye has id 0 and SurName "Bye"

`drawInfo` is null until the draw is published, which is a clean release
signal in its own right. No results are mixed into the lines (the Event has a
separate `Results` block, which this module never reads — Sofascore decides
results, and nothing else).

MEASURED AGAINST OUR WIKIPEDIA-BUILT DRAW, not assumed. 2026 Guadalajara
(event 2075, draw 142, 28 in a 32 bracket): 28 of 32 slots identical by name,
every seed and nationality agreeing. The other four were the two bottom-half
bye pairs — the official sheet lists the BYE above the seed there (Bye at 23,
Bejlek at 24) where Wikipedia's template and Sofascore's cup tree both put the
player on the odd slot (Bejlek 23, bye 24). Same pairs, same players; the
parser normalises to the odd-slot convention because every draw already in
the database uses it, and a later Wikipedia pass over a WTA-built draw must
not find its seeds one slot away from where it left them.

WHAT THIS IS FOR TODAY: bootstrapping a WTA draw that has no entries — the
official sheet is preferred over Sofascore (which fills incrementally) and
over Wikipedia (which is a volunteer's page). It produces the same DrawShape
the Sofascore path does, so it rides the same `shape_to_parsed` adapter into
the same `_do_scrape` writer.
"""
import hashlib
import json
import logging
import math
import os
import time
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.sofa_draw_shape import DrawShape, ShapeEntrant
from app.services.wta_feed import HEADERS, TIMEOUT

logger = logging.getLogger(__name__)

BASE = "https://api.wtatennis.com/tennis/tournaments"

# The sheet's entry vocabulary, in this project's spelling (scraper.ENTRY_TYPES).
_ENTRY = {"Q": "Q", "WC": "WC", "LL": "LL", "PR": "PR", "SE": "SE",
          "ALT": "Alt", "A": "Alt", "NG": "NG"}


CACHE_DIR = os.environ.get("WTA_CACHE_DIR", "/data/wta-cache")
CACHE_TTL = 3600.0


def _cached_json(url: str) -> dict:
    """One request an hour per URL; the refresh loop asks every thirty minutes."""
    f = f"{CACHE_DIR}/{hashlib.sha1(url.encode()).hexdigest()}.json"
    try:
        if time.time() - os.path.getmtime(f) < CACHE_TTL:
            with open(f, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except (OSError, ValueError):
        pass
    with urlopen(Request(url, headers=HEADERS), timeout=TIMEOUT) as r:
        payload = json.loads(r.read())
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except OSError:
        pass
    return payload


def fetch_draw(event_id: int, year: int) -> Optional[dict]:
    """The published draw document, or None when the tour has not published it.

    A missing `drawInfo` is the ORDINARY pre-release state, not a failure.
    Network trouble raises, so a caller can tell "not yet" from "could not ask".
    """
    url = f"{BASE}/{event_id}/{year}/draw"
    payload = _cached_json(url)
    info = payload.get("drawInfo")
    if not info:
        return None
    raw = info[0] if isinstance(info, list) else info
    return json.loads(raw) if isinstance(raw, str) else raw


def singles_event(doc: dict) -> Optional[dict]:
    """The main-draw singles event: LS. Never RS (qualifying) or LD."""
    try:
        events = doc["Draws"]["Events"]["Event"]
    except (KeyError, TypeError):
        return None
    if isinstance(events, dict):
        events = [events]
    for e in events:
        if (e.get("EventTypeCode") or "").upper() == "LS":
            return e
    return None


def _is_bye(line: dict) -> bool:
    player = ((line.get("Players") or {}).get("Player") or {})
    return ((line.get("DisplayLine") or "").strip().lower() == "bye"
            or (player.get("SurName") or "").strip().lower() == "bye")


def _is_placeholder(line: dict) -> bool:
    """A slot the draw holds for somebody not yet known — a qualifier before
    qualifying is done. Represented the way Wikipedia's is: an entry with an
    empty name and the entry type, so the writer counts the slot as taken."""
    player = ((line.get("Players") or {}).get("Player") or {})
    return not _is_bye(line) and (player.get("id") in (0, None, "0")
                                  or not (line.get("DisplayLine") or "").strip()
                                  or (line.get("DisplayLine") or "").strip().lower()
                                  in ("qualifier", "q", "lucky loser", "ll", "tbd"))


def _seed(v) -> Optional[int]:
    try:
        n = int(str(v).strip())
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def parse_draw(doc: dict) -> Optional[DrawShape]:
    """Every shape fact the sheet states, as the same DrawShape Sofascore yields.

    Byes are normalised so the PLAYER holds the odd slot of the pair and the
    bye the even one — see the module docstring for why.
    """
    ev = singles_event(doc)
    if not ev:
        return None
    lines = ((ev.get("Draw") or {}).get("DrawLine") or [])
    if isinstance(lines, dict):
        lines = [lines]
    if not lines:
        return None
    by_pos = {}
    for l in lines:
        try:
            by_pos[int(l.get("Pos"))] = l
        except (TypeError, ValueError):
            continue
    if not by_pos:
        return None
    size = max(by_pos)
    declared = _seed(ev.get("DrawSize"))
    bracket = declared if declared and declared >= size else size
    shape = DrawShape(bracket_size=bracket,
                      num_rounds=max(1, int(math.log2(bracket))) if bracket > 1 else 1)

    for pos in range(1, bracket + 1):
        line = by_pos.get(pos)
        if line is None:
            continue                       # a slot the sheet did not print
        if _is_bye(line):
            continue                       # handled pair-wise below
        player = ((line.get("Players") or {}).get("Player") or {})
        if _is_placeholder(line):
            name = ""
        else:
            first = (player.get("FirstName") or "").strip()
            last = (player.get("SurName") or "").strip()
            name = f"{first} {last}".strip() or (line.get("DisplayLine") or "").strip()
        shape.entrants.append(ShapeEntrant(
            bracket_position=pos, name=name,
            sofa_player_id=None, sofa_slug=None,
            seed=_seed(line.get("Seed")),
            entry_type=_ENTRY.get((line.get("EntryType") or "").strip().upper() or "", None),
            nationality=(player.get("Country") or "").strip() or None,
            ranking=_seed(line.get("Rank"))))

    # Byes, normalised: in each pair {odd, even} that holds one, the player
    # takes the odd slot and the bye the even.
    taken = {e.bracket_position: e for e in shape.entrants}
    for pos in range(1, bracket + 1):
        line = by_pos.get(pos)
        if line is None or not _is_bye(line):
            continue
        odd = pos if pos % 2 else pos - 1
        even = odd + 1
        partner = taken.get(even) if pos == odd else taken.get(odd)
        if pos == odd and partner is not None:
            # The bye was printed on the odd slot; move the player up to it.
            del taken[even]
            partner.bracket_position = odd
            taken[odd] = partner
        shape.byes.append(even)
    shape.entrants.sort(key=lambda e: e.bracket_position)
    shape.byes = sorted(set(shape.byes))
    return shape


def event_id_for(draw, tournament) -> Optional[int]:
    """The WTA event id this draw is keyed by, if the tournament row knows it."""
    if tournament is None or (draw.gender or "").upper() != "F":
        return None
    return getattr(tournament, "wta_live_scoring_id", None)


def fetch_shape(event_id: int, year: int) -> Optional[DrawShape]:
    """One request. None when unpublished; raises on network trouble."""
    doc = fetch_draw(event_id, year)
    return parse_draw(doc) if doc else None


__all__ = ["fetch_draw", "fetch_shape", "parse_draw", "singles_event", "event_id_for",
           "HTTPError", "URLError"]
