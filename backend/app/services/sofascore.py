"""
Sofascore identity resolution — stamp a stable player id on every draw entry.

WHY AN ID AT ALL. Every other external source in this app is pinned to a
persisted id and then joined on: draw_entries.te_player_id / te_slug for Tennis
Explorer, tournaments.atp_id for the order-of-play PDFs. ESPN is the exception —
it publishes no id, so espn_monitor re-derives every name match on every poll,
about 1,440 times a day, and needed a three-tier event fallback (name →
player-set Jaccard → venue city) to do it. Sofascore does publish ids, for both
the player and the tournament, so it can follow the Tennis Explorer pattern
instead: resolve once against the draw's own published field, write the id down,
and never name-match again.

The consequence worth stating plainly: once both players of a Sofascore event
carry ids we have stamped, that event IS a match in that draw. There is nothing
left to match at the tournament level, so none of the Jaccard/venue-city
machinery needs a second implementation here.

WHY TLS IMPERSONATION. Sofascore rejects any client whose TLS handshake does not
look like a browser. httpx, urllib and plain curl all get 403 — including with a
complete set of browser headers, and including on the ordinary website, not just
the API. curl_cffi replays a real Chrome fingerprint and is the only reason any
of this is reachable.

403 IS ALSO HOW THEY RATE-LIMIT, WHICH MAKES IT AMBIGUOUS AND DANGEROUS. The
same status covers "your client looks wrong" and "you asked too much", so the
two cannot be told apart from one response. Building this service earned a
block within a few minutes of enthusiastic querying: every endpoint returned
403, from a fresh session and a different impersonation target alike, so the
ban is on the EGRESS IP and not on a connection. That matters more here than it
would elsewhere — the backend shares Jupiter's IP with everything else, so a
runaway loop does not degrade this feature, it removes Sofascore from the whole
host. Hence the pacing and the circuit breaker below, which exist to protect
production access rather than to be polite. Resolution is a once-per-draw job;
there is no reason for it ever to be fast.

WHY THE CUP TREE, NOT THE EVENT LIST. /events/last/{page} paginates and, more
importantly, mixes qualifying into the same stream — which silently drops the
apparent match rate to ~70% because a main draw does not contain its own
qualifiers. /cuptrees returns the entire bracket in one request with main draw
and qualifying as separate trees, so the candidate set is exactly the field we
are matching against. That difference alone took resolution from 69.5% to 100%.

WHY THE CANDIDATE SET IS CLOSED. Matching inside one tournament's field is what
makes the looser rules safe: `surname+initial` would be reckless against every
tennis player alive and is close to certain against 103 known entrants. It is
also why the /search endpoint is NOT used to resolve players — searching
"J.J. Wolf" returns two Sofascore records for the same person (398806 and
210479) and only 210479 appears in the draw, so search would confidently return
an id that never shows up in a live event.

NULL IS NOT A DECISION. An entry we could not resolve is reported, never
guessed at and never quietly skipped. Resolution is measured against real draws
before it is trusted, and the unresolved list is the output that matters.
"""

import asyncio
import os
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Optional
from urllib.parse import quote

from curl_cffi import CurlError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tournament import Draw, DrawEntry
from app.services.http_errors import describe_exception, is_transient_http_error
from app.services.rankings import _norm
from app.services.system_log import app_log

_BASE = "https://api.sofascore.com/api/v1"

# The Chrome build curl_cffi replays. Bumping this is the LAST thing to try
# when everything 403s, not the first: a rate-limit block presents identically
# and is far more likely, so wait out the cooldown and confirm the block
# survives it before concluding the fingerprint has aged out.
_IMPERSONATE = "chrome124"
_TIMEOUT = 20

# Optional egress override, read per call so it can be set without a rebuild.
#
# The gate is on the EGRESS IP, not the client — proven by driving the real site
# in Camoufox from Jupiter and watching Sofascore's OWN in-page XHRs return 403,
# while a plain phone browser on cellular got 200. So when Jupiter's address is
# in the penalty box there is nothing to fix in this file, and the only lever is
# where the request leaves from.
#
# Typically an SSH SOCKS tunnel to a machine on a different network:
#   ssh -f -N -D 172.17.0.1:1080 <host>      # bind the docker bridge, not
#                                            # 0.0.0.0 — that is an open proxy
#   SOFASCORE_PROXY=socks5h://172.17.0.1:1080
#
# socks5h, not socks5: the h resolves DNS at the far end, so the exit's resolver
# is used rather than leaking lookups from here.
#
# Now also carries the production egress: a rotating residential pool, where the
# session id lives in the PASSWORD segment rather than the username —
#   http://USER:PASS_country-ca_session-XXXX_lifetime-30m@geo.iproyal.com:12321
# That is the opposite of most providers and is documented only in IPRoyal's
# developer docs; every username-segment form is rejected outright. Without
# _country-* the pool exits wherever it likes — a plain connection came out of
# China Mobile.
_PROXY_ENV = "SOFASCORE_PROXY"

# Sofascore splits the tours into separate uniqueTournaments — Cincinnati is
# 2373 (ATP) and 2548 (WTA) — so the category is part of identifying the draw,
# not a detail. Matching without it would cheerfully return the men's bracket
# for a women's draw.
_CATEGORY_BY_GENDER = {"M": "ATP", "F": "WTA"}

# difflib ratio at or above which two name token-sets are the same person.
# Same threshold rankings.py uses for the Tennis Explorer fallback; kept
# identical deliberately so one source cannot drift looser than the other.
_FUZZY_MIN = 0.82

# Share of our entries that must appear in a candidate tournament's field before
# it is accepted as the same event. The gap this sits in is enormous — the right
# tournament matches nearly every player, a wrong one nearly none — so the exact
# value matters far less than having one. Set low enough that a partially
# published bracket still resolves.
_MIN_FIELD_OVERLAP = 0.5

# Sofascore reports countries as ISO 3166 alpha-3; draw_entries.nationality
# holds IOC codes. Only the codes that DIFFER are listed — anything absent is
# identical in both systems, and anything unknown yields no opinion rather than
# a false disagreement. Used solely to veto a loose match, never to make one.
_ISO3_TO_IOC = {
    "AGO": "ANG", "ARE": "UAE", "BFA": "BUR", "BGD": "BAN", "BGR": "BUL",
    "BRB": "BAR", "BWA": "BOT", "CHE": "SUI", "CHL": "CHI", "CRI": "CRC",
    "DEU": "GER", "DNK": "DEN", "DZA": "ALG", "GRC": "GRE", "GTM": "GUA",
    "HRV": "CRO", "IDN": "INA", "IRN": "IRI", "KHM": "CAM", "KWT": "KUW",
    "LKA": "SRI", "LVA": "LAT", "MCO": "MON", "MDG": "MAD", "MMR": "MYA",
    "MNG": "MGL", "MUS": "MRI", "NGA": "NGR", "NLD": "NED", "NPL": "NEP",
    "OMN": "OMA", "PHL": "PHI", "PRI": "PUR", "PRT": "POR", "PRY": "PAR",
    "SAU": "KSA", "SLV": "ESA", "SVN": "SLO", "TWN": "TPE", "URY": "URU",
    "VNM": "VIE", "ZAF": "RSA", "ZMB": "ZAM", "ZWE": "ZIM",
}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class SofascoreNotFound(CurlError):
    """
    The endpoint answered, and the answer is that there is nothing there.

    NOT a block, and the distinction is load-bearing. `events/next/0` returns
    404 for a season with no upcoming matches, which is the ordinary state of
    every tournament from its last day onwards. Treating that as a refusal took
    down the whole doubles sweep — the caller re-raises a block on purpose, to
    trip its thirty-minute breaker — so on the day a tournament finished, its
    finished matches stopped being recorded.

    Subclasses CurlError for the same reason SofascoreBlocked does: that is what
    is_transient_http_error() recognises, so it is logged rather than paged on.
    """


class SofascoreBlocked(CurlError):
    """
    Sofascore is refusing this host.

    Subclasses curl_cffi's CurlError specifically — that is the class
    is_transient_http_error() was taught to recognise, so this is already
    classified as "the far end, not us" and logged at debug rather than paged
    on. Subclassing OSError instead would look equivalent and silently miss:
    the helper tests the curl class, not its base.
    """


# Serialised, paced access. Every request in the process goes through one lock
# so concurrent callers cannot each think they are the only one; _MIN_INTERVAL
# is the floor between any two. Deliberately slow — this runs once per draw.
_gate = asyncio.Lock()
_last_request_at = 0.0
_MIN_INTERVAL = 2.0

# Circuit breaker. Once blocked, further requests do not merely fail — they
# extend the ban. So the first 403 stops ALL traffic from this process for a
# fixed cooldown rather than retrying into it, which is the opposite of the
# usual backoff instinct and the only thing that actually shortens an IP block.
_blocked_until = 0.0
_BLOCK_COOLDOWN = 1800.0


def _rotate_session(proxy: str) -> str:
    """Give a rotating-pool proxy a NEW sticky session id.

    IPRoyal puts session config in the password segment
    (`pass_country-ca_session-XXX_lifetime-30m`), which is the opposite of most
    providers and is not documented on their help site — only in the developer
    docs. Every username-segment form is rejected outright.

    Returns the proxy unchanged when there is no session token to replace, so
    this is safe to call on a direct connection or a fixed-IP proxy.
    """
    import re
    import secrets

    if "_session-" not in proxy:
        return proxy
    return re.sub(r"_session-[^_@]+",
                  f"_session-{secrets.token_hex(4)}", proxy, count=1)


def _fetch(path: str, rotate: bool = False) -> tuple:
    """Blocking GET. curl_cffi has no async API, so callers use _get()."""
    from curl_cffi import requests as cr

    kwargs = {"impersonate": _IMPERSONATE, "timeout": _TIMEOUT}
    proxy = os.environ.get(_PROXY_ENV)
    if proxy:
        if rotate:
            proxy = _rotate_session(proxy)
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    r = cr.get(f"{_BASE}{path}", **kwargs)
    if r.status_code != 200:
        return r.status_code, None
    return 200, r.json()


async def _get(path: str) -> dict:
    """
    One paced request. Raises SofascoreBlocked on 403 and while the breaker is
    open, so a caller mid-draw stops instead of walking the rest of its list.
    """
    global _last_request_at, _blocked_until

    loop = asyncio.get_running_loop()
    if loop.time() < _blocked_until:
        raise SofascoreBlocked(
            f"circuit open for another {_blocked_until - loop.time():.0f}s")

    async with _gate:
        delay = _MIN_INTERVAL - (loop.time() - _last_request_at)
        if delay > 0:
            await asyncio.sleep(delay)
        _last_request_at = loop.time()

    status, payload = await asyncio.to_thread(_fetch, path)

    # A 403 means two different things depending on where we are calling FROM,
    # and treating them alike is either wasteful or dangerous.
    #
    # On a fixed egress it means "this IP is in the penalty box", and the only
    # correct response is to stop — retrying is what turns a short block into a
    # long one, which is how Jupiter's own address was lost for a day.
    #
    # Through a rotating residential pool the exit is one borrowed consumer IP
    # out of thousands, and its reputation is inherited from a stranger. A 403
    # there says nothing about us; it says that particular exit is dirty. Taking
    # a fresh session and trying once more is the right move, and opening a
    # 30-minute breaker over one unlucky draw would idle the poller for nothing.
    if status == 403 and _rotate_session(os.environ.get(_PROXY_ENV) or "") != (
            os.environ.get(_PROXY_ENV) or ""):
        status, payload = await asyncio.to_thread(_fetch, path, True)
        if status == 200:
            await app_log(
                "info", "sofascore",
                "Rotated to a new residential exit after a 403 on the previous one",
                detail={"path": path},
                dedup_key="sofa_rotated", dedup_hours=6)

    if status == 403:
        _blocked_until = loop.time() + _BLOCK_COOLDOWN
        await app_log(
            "warning", "sofascore",
            "Sofascore returned 403 — pausing all requests for "
            f"{_BLOCK_COOLDOWN / 60:.0f} minutes",
            detail={"path": path},
            dedup_key="sofa_blocked", dedup_hours=1)
        raise SofascoreBlocked(f"403 on {path}")
    # A 404 is an ANSWER, not a refusal. Sofascore returns one for a season
    # with no upcoming events, an event id that has aged out, and any path that
    # simply has no data behind it — all states a caller should decide about,
    # none of them a reason to stop talking to the host.
    if status == 404:
        raise SofascoreNotFound(f"404 on {path}")
    if status != 200:
        raise SofascoreBlocked(f"HTTP {status} on {path}")
    return payload


# ---------------------------------------------------------------------------
# Name matching (pure — no I/O, so it can be tested against a saved field)
# ---------------------------------------------------------------------------

def _toks(name: str) -> frozenset:
    return frozenset(_norm(name).split())


def _surname(name: str) -> str:
    parts = _norm(name).split()
    return parts[-1] if parts else ""


def _initials(name: str) -> set:
    """First letters of every given name — the surname itself is excluded."""
    return {w[0] for w in _norm(name).split()[:-1] if w}


def _ioc(alpha3: Optional[str]) -> Optional[str]:
    if not alpha3:
        return None
    return _ISO3_TO_IOC.get(alpha3.upper(), alpha3.upper())


def _countries_conflict(ours: Optional[str], theirs: Optional[str]) -> bool:
    """True only when both sides state a country and they disagree."""
    a, b = (ours or "").upper() or None, _ioc(theirs)
    return bool(a and b and a != b)


# Words that name the EVENT rather than the place. Sofascore indexes most
# tournaments under the bare place ("Cincinnati"), so a search for the draw's
# own name misses; stripping these is what turns "Cincinnati Open" into a term
# that hits. Tried after the verbatim name, never instead of it — "Australian
# Open" and "French Open" are indexed WITH the suffix, and stripping first
# would break exactly the events with the most users.
_EVENT_WORDS = frozenset(
    "open masters championships championship cup classic international trophy "
    "series tour tennis atp wta grand prix the of".split())


def _is_singles_tour_event(entity: dict, want_category: str) -> bool:
    """
    True for the one uniqueTournament that is this tour's SINGLES main event.

    /search/unique-tournaments is tennis-scoped but still returns three kinds of
    near-miss that must never be selected:

      • the doubles event of the same tournament ("Vienna, Doubles"), which is a
        real ATP tournament and therefore passes a category check — it is the
        reason a bare category filter returns two hits and resolves nothing;
      • lower tiers (Challenger, WTA 125, ITF) sharing the venue's name;
      • "Simulated Reality" — Sofascore carries SRL events, which are SIMULATED
        matches between real players' names. Matching one would feed invented
        scores into a live draw, so it is excluded by name as well as category
        rather than trusted to the category test alone.
    """
    category = (entity.get("category") or {}).get("name") or ""
    name = (entity.get("name") or "").lower()
    if category != want_category:
        return False
    if "doubles" in name:
        return False
    if "simulated" in category.lower() or name.startswith("srl "):
        return False
    # Side events that carry the tournament's name but are not its main draw:
    # "Berlin, Qualifiers", "Australian Open Australian Playoff", "Australian
    # Open Asia-Pacific Wildcard Playoff". Each is a real event of the right
    # category, so only the name distinguishes them.
    if any(w in name for w in ("qualif", "playoff", "play-off", "wildcard")):
        return False
    return True


def _search_terms(draw) -> list:
    """
    Ordered, de-duplicated search terms for one draw, most specific first.

    The city is NOT the best first guess and is not treated as one: the
    Cincinnati Open is played in Mason, Ohio, so draws.city reads "Mason" and
    matches nothing. It stays in the list because for most events it is right.
    """
    terms = []
    name = (draw.name or "").strip()
    if name:
        terms.append(name)
        stripped = " ".join(w for w in name.split()
                            if _norm(w) not in _EVENT_WORDS)
        if stripped and stripped != name:
            terms.append(stripped)
    if draw.city:
        terms.append(draw.city.strip())

    seen, out = set(), []
    for t in terms:
        key = _norm(t)
        if key and key not in seen:
            seen.add(key)
            out.append(t)
    return out


class _Candidate:
    __slots__ = ("toks", "surname", "initials", "team")

    def __init__(self, team: dict):
        name = team.get("name") or ""
        self.toks = _toks(name)
        self.surname = _surname(name)
        self.initials = _initials(name)
        self.team = team


def _match_one(name: str, nationality: Optional[str],
               cands: list) -> tuple[Optional[dict], Optional[str]]:
    """
    Resolve one entry name against a closed field.

    Rules are tried in order and each must hit EXACTLY ONE candidate; an
    ambiguous rule falls through to the next rather than picking a winner,
    because two plausible players is precisely the case where a guess does
    real damage. Returns (team, rule) or (None, None).
    """
    ours, osur, oini = _toks(name), _surname(name), _initials(name)
    if not ours:
        return None, None

    sorted_ours = " ".join(sorted(ours))
    attempts = (
        ("exact", [c for c in cands if c.toks == ours]),
        ("subset", [c for c in cands if ours < c.toks]),
        ("superset", [c for c in cands if len(c.toks) >= 2 and c.toks < ours]),
        ("fuzzy", [c for c in cands if SequenceMatcher(
            None, sorted_ours, " ".join(sorted(c.toks)), autojunk=False
        ).ratio() >= _FUZZY_MIN]),
        ("surname+initial",
         [c for c in cands if c.surname and c.surname == osur and (oini & c.initials)]),
    )

    for rule, hits in attempts:
        # The two loose rules match a DIFFERENT spelling, so a stated country
        # disagreement means it is a different person — the one check that
        # separates "Aleksandr/Alexander Shevchenko" from two unrelated players
        # who happen to share a surname.
        if rule in ("fuzzy", "surname+initial"):
            hits = [c for c in hits
                    if not _countries_conflict(
                        nationality, (c.team.get("country") or {}).get("alpha3"))]
        if len(hits) == 1:
            return hits[0].team, rule
    return None, None


def _main_draw_teams(cup_trees: list) -> list:
    """
    Singles players of the MAIN draw, from a /cuptrees payload.

    Qualifying arrives as its own tree and must be dropped: its players are not
    in our field, and leaving them in turns every unmatched qualifier into a
    phantom failure. Falls back to the largest tree if the naming ever changes,
    so a rename degrades the filter rather than emptying the field.
    """
    trees = [t for t in (cup_trees or [])
             if "qualif" not in (t.get("name") or "").lower()]
    if not trees and cup_trees:
        trees = [max(cup_trees,
                     key=lambda t: sum(len(r.get("blocks", []))
                                       for r in t.get("rounds", [])))]

    teams: dict = {}
    for tree in trees:
        for rnd in tree.get("rounds", []):
            for block in rnd.get("blocks", []):
                for part in block.get("participants", []):
                    team = part.get("team") or {}
                    tid, name = team.get("id"), team.get("name") or ""
                    # type 2 is a doubles pairing; we hold no doubles draw, and
                    # a pair's id would resolve to nobody in draw_entries.
                    if tid and team.get("type") != 2 and "/" not in name:
                        teams[tid] = team
    return list(teams.values())


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

async def _candidate_tournaments(draw: Draw) -> list:
    """Every plausible uniqueTournament for this draw, de-duplicated by id."""
    want = _CATEGORY_BY_GENDER.get(draw.gender)
    if not want:
        return []
    found: dict = {}
    for term in _search_terms(draw):
        payload = await _get(f"/search/unique-tournaments?q={quote(term)}")
        for entity in (r.get("entity", r) for r in payload.get("results", [])):
            if _is_singles_tour_event(entity, want) and entity.get("id"):
                found.setdefault(entity["id"], entity)
    return list(found.values())


async def _season_for(uid: int, year: int) -> Optional[dict]:
    """
    This year's season of a tournament, or None if it has not been created.

    year arrives as a STRING ("2025"), so it is compared as one. Written as
    `== draw.year` this silently never matched and every tournament resolved
    through the name fallback instead — which works, but only because Sofascore
    happens to repeat the year inside the season name.
    """
    seasons = (await _get(f"/unique-tournament/{uid}/seasons")).get("seasons", [])
    y = str(year)
    return (next((s for s in seasons if str(s.get("year") or "") == y), None)
            or next((s for s in seasons if y in str(s.get("name") or "")), None))


async def _field_of(uid: int, season_id: int) -> list:
    payload = await _get(f"/unique-tournament/{uid}/season/{season_id}/cuptrees")
    return _main_draw_teams(payload.get("cupTrees", []))


async def _resolve_against_field(draw: Draw, entries: list) -> Optional[tuple]:
    """
    Pick the tournament whose PUBLISHED FIELD matches this draw, not the one
    whose name looks closest.

    Name search alone is not safe here and the near-misses are the dangerous
    kind, not the obvious kind:

      • "French Open" is not indexed under that name, and the fallback to the
        draw's city finds `2404:Paris` — the Paris MASTERS, a different
        tournament on a different surface in a different month;
      • the only "Berlin" hit is `2580:Berlin, Qualifiers`;
      • back-to-back editions at one venue appear as "Adelaide" and
        "Adelaide 2", and Estoril returns two live ids under one name.

    Every one of those resolves confidently to the wrong bracket, which is far
    worse than resolving to nothing — a wrong tournament id would attach live
    scores from another event to this draw. Overlap with our own entry names
    settles it: the right tournament shares nearly all 96 players and a wrong
    one shares almost none, so this is a wide margin rather than a fine call.

    Returns (uid, season_id, field) or None.
    """
    ours = [(_toks(e.name), e) for e in entries if e.name]
    if not ours:
        return None

    best = None
    for cand in await _candidate_tournaments(draw):
        season = await _season_for(cand["id"], draw.year)
        if season is None:
            continue
        try:
            field = await _field_of(cand["id"], season["id"])
        except SofascoreBlocked:
            # Abort rather than score the candidates we happen to have: a
            # partial sweep could crown a wrong tournament simply because the
            # right one's cup tree was the request that got refused.
            raise
        except Exception as exc:
            if is_transient_http_error(exc):
                continue
            raise
        if not field:
            continue
        theirs = {_toks(t.get("name") or "") for t in field}
        overlap = sum(1 for ts, _ in ours if ts in theirs) / len(ours)
        if best is None or overlap > best[0]:
            best = (overlap, cand["id"], season["id"], field)

    if best is None or best[0] < _MIN_FIELD_OVERLAP:
        return None
    return best[1], best[2], best[3]


async def resolve_tournament(db: AsyncSession, draw: Draw) -> Optional[tuple]:
    """
    Persisted (uniqueTournament id, season id) for a draw, resolving if needed.

    Already-stamped ids are returned untouched — same rule as atp_ids, and for
    the same reason: a search that comes back empty or ambiguous must leave a
    working id alone rather than replace it with nothing.
    """
    if draw.sofa_tournament_id and draw.sofa_season_id:
        return draw.sofa_tournament_id, draw.sofa_season_id

    entries = (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == draw.id,
                                DrawEntry.name.isnot(None)))).scalars().all()
    found = await _resolve_against_field(draw, entries)
    if found is None:
        return None
    draw.sofa_tournament_id, draw.sofa_season_id = found[0], found[1]
    await db.commit()
    return found[0], found[1]


async def resolve_draw(db: AsyncSession, draw: Draw, *, force: bool = False) -> dict:
    """
    Stamp sofa_player_id across one draw. Returns a report; writes nothing else.

    force=True re-resolves entries that already carry an id. Off by default so
    a routine run cannot overwrite a hand-pinned correction.
    """
    report = {
        "draw_id": draw.id, "draw": f"{draw.name} {draw.year} {draw.gender}",
        "total": 0, "resolved": 0, "already": 0, "rules": {},
        "unresolved": [], "field_size": 0, "error": None,
    }

    # `is not None` is not the same as "has a name". An unfilled qualifier slot
    # is stored as an empty string, not NULL, so eight of Winston-Salem's forty
    # eight "unresolved entries" were four real names and four blanks that could
    # never resolve and were never meant to — reported as failures every day
    # until the qualifiers came through.
    entries = [e for e in (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == draw.id,
                                DrawEntry.name.isnot(None)))).scalars().all()
               if (e.name or "").strip()]
    report["total"] = len(entries)
    if not entries:
        report["error"] = "draw has no named entries yet"
        return report

    if draw.sofa_tournament_id and draw.sofa_season_id:
        field = await _field_of(draw.sofa_tournament_id, draw.sofa_season_id)
    else:
        # Resolving the tournament already had to read the field to verify it;
        # reuse that rather than fetching the same cup tree twice.
        found = await _resolve_against_field(draw, entries)
        if found is None:
            report["error"] = "no tournament on Sofascore matched this field"
            return report
        draw.sofa_tournament_id, draw.sofa_season_id, field = found
        await db.commit()

    report["field_size"] = len(field)
    if not field:
        report["error"] = "cup tree empty (draw not published on Sofascore yet)"
        return report
    cands = [_Candidate(t) for t in field]

    # An id already used by another entry in this same draw means the field held
    # two names that collapsed onto one player. Taking the second would silently
    # move a live score onto the wrong bracket slot, so both are left unresolved
    # and reported instead.
    taken = {e.sofa_player_id for e in entries if e.sofa_player_id}
    dirty = False
    for entry in entries:
        if entry.sofa_player_id and not force:
            report["already"] += 1
            continue
        team, rule = _match_one(entry.name, entry.nationality, cands)
        if team is None:
            report["unresolved"].append({"entry_id": entry.id, "name": entry.name,
                                         "nationality": entry.nationality,
                                         "reason": "no unique match"})
            continue
        if team["id"] in taken and entry.sofa_player_id != team["id"]:
            report["unresolved"].append({"entry_id": entry.id, "name": entry.name,
                                         "nationality": entry.nationality,
                                         "reason": f"id {team['id']} already claimed"})
            continue
        entry.sofa_player_id = team["id"]
        taken.add(team["id"])
        dirty = True
        report["resolved"] += 1
        report["rules"][rule] = report["rules"].get(rule, 0) + 1

    if dirty:
        await db.commit()

    if report["unresolved"]:
        await app_log(
            "warning", "sofascore",
            f"{len(report['unresolved'])} unresolved entries in {report['draw']}",
            detail={"draw_id": draw.id,
                    "names": [u["name"] for u in report["unresolved"]][:20],
                    "resolved": report["resolved"], "total": report["total"]},
            dedup_key=f"sofa_unresolved_{draw.id}", dedup_hours=24)
    return report


# How long before a draw that still has unresolved names is tried again.
# Entries arrive over days — qualifiers fill the last slots on the morning of
# play — so one pass can only stamp who was in the field at the time, and a
# retry is genuinely needed. But some names Sofascore simply does not carry, and
# without a floor those four or five would be re-resolved every pass forever,
# spending a request each time on an answer that will not change.
RESOLVE_RETRY_HOURS = 6.0


async def resolve_pending_draws(db: AsyncSession, *, force: bool = False,
                                retry_hours: float = 0.0) -> list:
    """
    Resolve every draw that has entries and at least one unstamped one.

    Completed draws are skipped: their ids would never be read, and a finished
    edition's cup tree is exactly the payload most likely to have been rotated
    away by Sofascore.

    `retry_hours` puts a floor under repeat attempts, for the scheduled caller
    that runs this every hour forever. Zero — the default, and what a human at a
    terminal wants — means "try everything now".
    """
    rows = (await db.execute(
        select(Draw)
        .join(DrawEntry, DrawEntry.draw_id == Draw.id)
        .where(Draw.status != "completed")
        .distinct())).scalars().all()

    reports = []
    for draw in rows:
        pending = (await db.execute(
            select(DrawEntry.id).where(
                DrawEntry.draw_id == draw.id,
                DrawEntry.name.isnot(None),
                DrawEntry.sofa_player_id.is_(None)).limit(1))).first()
        if pending is None and not force:
            continue
        # Tried recently and still short of a full field? Leave it. The names
        # that did not resolve an hour ago are the same names now.
        #
        # Except when the TOURNAMENT itself is still unresolved, which is a
        # different situation wearing the same clothes. A draw missing a few
        # players scores every other match on it; a draw missing its
        # uniqueTournament id scores nothing at all, and the usual reason is
        # that Sofascore has not published the bracket yet — its cuptree comes
        # back as R16P1, R16P2, placeholders with no names to match against.
        # That resolves itself the hour the draw goes up, so check every hour
        # rather than leaving a tournament dark for most of its first day.
        wait = retry_hours if draw.sofa_tournament_id else min(retry_hours, 1.0)
        if wait and draw.sofa_resolved_at is not None:
            last = draw.sofa_resolved_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - last).total_seconds() < wait * 3600:
                continue
        try:
            draw.sofa_resolved_at = datetime.now(timezone.utc)
            reports.append(await resolve_draw(db, draw, force=force))
            await db.commit()
        except SofascoreBlocked:
            # Stop the whole sweep. Continuing would issue a request per
            # remaining draw against a host that has already refused us, which
            # is what turns a short block into a long one.
            #
            # Re-raised rather than swallowed. Breaking quietly returned an empty
            # list, which the caller could not tell apart from "there was nothing
            # to resolve" — so a run that was refused on its very first request
            # reported total success and left the operator none the wiser.
            # Anything stamped before the block is already committed by
            # resolve_draw, so nothing is lost by unwinding here.
            raise
        except Exception as exc:
            if is_transient_http_error(exc):
                # The job runs again on its own schedule; a timeout is not news.
                continue
            await app_log(
                "error", "sofascore",
                f"Sofascore resolution failed for draw {draw.id}: {describe_exception(exc)}",
                detail={"draw_id": draw.id, "draw": draw.name},
                dedup_key=f"sofa_resolve_fail_{draw.id}", dedup_hours=6)
    return reports
