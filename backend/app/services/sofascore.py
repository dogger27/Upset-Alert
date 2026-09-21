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
import logging
import os
import re
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

logger = logging.getLogger(__name__)

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


class SofascoreUnavailable(CurlError):
    """
    Sofascore's own servers failed to answer: a 5xx, Cloudflare's 52x included.

    NOT a block, for the same reason a 404 is not. Every sweep catches
    SofascoreBlocked to stand down for at least thirty minutes and tell the
    owner Sofascore refused us — right for a 403, and wrong for a server that
    hiccuped once. A single 503 on a doubles season page paused that sweep for
    half an hour and mailed a warning (2026-09-21) while the breaker was never
    open and the very next request would have been answered. A refusal is
    about this host; a 5xx is about theirs, and nothing we stop doing makes it
    end sooner. So it takes each caller's ordinary failure path: skip this
    page or event and ask again next pass. A real outage still surfaces — the
    live poller counts consecutive failures and escalates on its own.

    A CurlError like its siblings, so is_transient_http_error() files it under
    "the far end, not us".
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
# A BLOCK THAT KEEPS COMING BACK IS NOT A RATE LIMIT, IT IS A BAN.
# The flat 30-minute cooldown assumes the block clears on its own, which is
# true of rate limiting and false of an IP ban: from 2026-08-29 the breaker
# re-armed twice an hour for fourteen hours straight, each retry poking an
# exit Sofascore had already refused — the one thing the comment above says
# never to do — and writing two warnings an hour while it did.
# Consecutive trips with no success between them double the wait, up to six
# hours. The first success resets it, so a proxy coming back or a lifted block
# returns to the tight cadence immediately.
_BLOCK_COOLDOWN_MAX = 21600.0
_consecutive_blocks = 0


# ── WHICH WAY OUT ────────────────────────────────────────────────────────────
#
# Direct is free; the residential proxy is metered. Sofascore banned this
# host's own IP for 26 hours on 2026-08-29, so PROXY IS THE SAFE DEFAULT and
# direct is an optimisation the app may try for itself — rarely, and only well
# after a ban has aged. Held in memory for the sync fetch path and mirrored
# into app_settings so a restart cannot forget a ban and walk back into it.
_egress_direct = False

# How long a direct-route ban must age before the probe touches it again.
# Retrying into a live ban is what extends it, so this is deliberately long
# relative to the probe cadence: the probe simply declines to run. A day —
# the one ban on record lasted 26 hours — and then a SINGLE request.
DIRECT_COOLOFF = 24 * 3600.0


def proxy_refused_tunnel(err) -> bool:
    """curl's wording when the PROXY answers the CONNECT with an error status:
    "CONNECT tunnel failed, response 402". 402 is IPRoyal's balance-spent
    answer; 407 would be bad credentials. Either way the proxy, not the site."""
    text = str(err)
    return "CONNECT tunnel failed" in text and bool(re.search(r"response 4\d\d", text))


def egress_is_direct() -> bool:
    return _egress_direct


def _current_proxy() -> str:
    """The proxy to use, or "" to go straight out from this host."""
    if _egress_direct:
        return ""
    return os.environ.get(_PROXY_ENV) or ""


def blocked_for() -> float:
    """Seconds until the circuit closes; 0.0 when it is not open.

    The sweeps each hardcoded a 30-minute pause to match the circuit breaker,
    which stopped being true when the breaker learned to escalate: they woke
    every half hour into a six-hour block, were refused, and logged it. Asking
    the breaker how long it actually intends to stay shut lets them sleep the
    real interval and log once per block instead of twice an hour.
    """
    try:
        now = asyncio.get_running_loop().time()
    except RuntimeError:      # no loop running — nothing is polling anyway
        return 0.0
    return max(0.0, _blocked_until - now)


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
    proxy = _current_proxy()
    if proxy:
        if rotate:
            proxy = _rotate_session(proxy)
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    r = cr.get(f"{_BASE}{path}", **kwargs)
    if r.status_code != 200:
        return r.status_code, None
    return 200, r.json()


# ── the response cache ────────────────────────────────────────────────────
# NOT GETTING BLOCKED IS THE FIRST REQUIREMENT (owner, 2026-09-21), and the
# identity path is where this project would most easily earn a block: it runs
# from the WikiPageNotFound branch of _refresh_active_tournaments, which fires
# EVERY 30 MINUTES for every draw with no article, for the whole polling
# window. Un-cached, one such draw costs about four requests a pass — roughly
# 200 a day, for an answer that changes at most once.
#
# So the identity endpoints read through a disk cache with a TTL, and a 404 is
# cached too: "Sofascore has not published this bracket" is an answer worth
# remembering, and it is the answer we get most often. Live scores are NEVER
# cached — _get stays the uncached path and the callers that need current data
# keep using it.
#
# On disk rather than in memory because deploy.sh recreates this container
# every couple of minutes on a busy afternoon; an in-process cache would be
# empty almost every time it was asked, which is the same failure recorded for
# app_log's dedup cache.
# UNDER /data, WHICH IS A HOST BIND MOUNT. /tmp is the container's writable
# layer, and deploy.sh runs `up` on every backend push — which discards that
# layer, so a cache there would be cold again within minutes and the whole
# point of it lost. This is the same trap that silently rolled the database
# back for days (see CLAUDE.md on WAL files in a single-file mount): what has
# to survive a recreate must live on the mount.
_SOFA_CACHE_DIR = os.environ.get("SOFA_CACHE_DIR", "/data/sofa-cache")
# A tournament list and its seasons barely move; a cup tree moves once, when
# the draw is published. The 404 TTL is the shortest because it is the one
# standing between us and noticing a release.
CACHE_TTL_SEARCH = 86400.0
CACHE_TTL_SEASONS = 86400.0
CACHE_TTL_CUPTREE = 10800.0
CACHE_TTL_NOT_FOUND = 3600.0


def _cache_file(path: str) -> str:
    import hashlib
    return f"{_SOFA_CACHE_DIR}/{hashlib.sha1(path.encode()).hexdigest()}.json"


def cache_stats() -> dict:
    """What the cache is holding — for the CLI and for answering "is it used?"."""
    import glob
    files = glob.glob(f"{_SOFA_CACHE_DIR}/*.json")
    return {"dir": _SOFA_CACHE_DIR, "entries": len(files)}


async def _get_cached(path: str, ttl: float) -> dict:
    """One paced request, or the last answer if it is still fresh.

    Raises SofascoreNotFound from a CACHED 404 as readily as from a live one,
    so a caller cannot tell the difference and none of them needs to.
    """
    import json as _json
    import time as _time

    # A cache is an optimisation and must never be able to fail a request:
    # a directory that cannot be created means no caching, not no data.
    try:
        os.makedirs(_SOFA_CACHE_DIR, exist_ok=True)
    except OSError:
        return await _get(path)
    f = _cache_file(path)
    try:
        age = _time.time() - os.path.getmtime(f)
        with open(f, "r", encoding="utf-8") as fh:
            held = _json.load(fh)
        limit = CACHE_TTL_NOT_FOUND if held.get("__notfound__") else ttl
        if age < limit:
            if held.get("__notfound__"):
                raise SofascoreNotFound(f"404 on {path} (cached {int(age)}s ago)")
            return held["payload"]
    except (OSError, ValueError, KeyError):
        pass          # no usable entry; fall through and ask

    try:
        payload = await _get(path)
    except SofascoreNotFound:
        try:
            with open(f, "w", encoding="utf-8") as fh:
                _json.dump({"__notfound__": True}, fh)
        except OSError:
            pass
        raise
    try:
        with open(f, "w", encoding="utf-8") as fh:
            _json.dump({"payload": payload}, fh)
    except OSError:
        pass          # a cache that cannot be written is not a failure
    return payload


async def _get(path: str) -> dict:
    """
    One paced request. Raises SofascoreBlocked on 403 and while the breaker is
    open, so a caller mid-draw stops instead of walking the rest of its list.
    A 404 is SofascoreNotFound and a 5xx SofascoreUnavailable — answers, not
    refusals, so neither stops anything.
    """
    global _last_request_at, _blocked_until, _consecutive_blocks

    loop = asyncio.get_running_loop()
    if loop.time() < _blocked_until:
        raise SofascoreBlocked(
            f"circuit open for another {_blocked_until - loop.time():.0f}s")

    async with _gate:
        delay = _MIN_INTERVAL - (loop.time() - _last_request_at)
        if delay > 0:
            await asyncio.sleep(delay)
        _last_request_at = loop.time()

    try:
        status, payload = await asyncio.to_thread(_fetch, path)
    except CurlError as e:
        # THE PROXY ITSELF REFUSING THE TUNNEL is not Sofascore and not the
        # network: "CONNECT tunnel failed, response 402" is IPRoyal saying the
        # balance is spent. Classified transient, it was logged at debug and
        # nobody saw that the only fallback for a ban on this host was gone
        # (2026-09-17). Said once every six hours, as a warning the digest mails.
        if proxy_refused_tunnel(e):
            await app_log("warning", "sofascore",
                          "The residential proxy refused the tunnel (HTTP 402 Payment Required) — "
                          "the IPRoyal balance is spent. Sofascore is reachable only while this "
                          "host's own IP is not banned; top up the proxy.",
                          detail={"path": path, "error": str(e)[:200]},
                          dedup_key="sofa_proxy_402", dedup_hours=6)
        raise

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
    if status == 403 and _rotate_session(_current_proxy()) != _current_proxy():
        status, payload = await asyncio.to_thread(_fetch, path, True)
        if status == 200:
            await app_log(
                "info", "sofascore",
                "Rotated to a new residential exit after a 403 on the previous one",
                detail={"path": path},
                dedup_key="sofa_rotated", dedup_hours=6)

    if status == 403:
        # SMART SWITCHING, ONE STEP EACH WAY, ONE REQUEST EACH.
        # Refused while direct: this host is banned again. Fall back to the
        # proxy, remember when (the probe leaves direct alone for a day), and
        # send THIS request out through the proxy right now — the caller need
        # never know. Only if the proxy refuses too does the breaker trip.
        if _egress_direct:
            await _record_direct_block()
            if _current_proxy():
                status, payload = await asyncio.to_thread(_fetch, path)
                if status == 200:
                    await app_log("info", "sofascore",
                                  "Direct route refused — this request went out through the proxy",
                                  detail={"path": path},
                                  dedup_key="sofa_fell_to_proxy", dedup_hours=6)
        # Refused on the proxy, even from a fresh exit: the free route is the
        # other way out — tried once, and only if its own ban has aged.
        elif await _direct_may_be_tried():
            status, payload = await _try_direct(path)
    if status == 403:
        _consecutive_blocks += 1
        cooldown = min(_BLOCK_COOLDOWN * (2 ** (_consecutive_blocks - 1)),
                       _BLOCK_COOLDOWN_MAX)
        _blocked_until = loop.time() + cooldown
        await app_log(
            "warning", "sofascore",
            # STABLE TEXT, VARYING FACTS IN detail. The triage view groups by
            # the message and the alert digest fingerprints on it, so folding
            # the escalating minute count into the sentence split one problem
            # into a fresh group — and a fresh alert — at every step of the
            # backoff. The numbers are below, where they cost nothing.
            "Sofascore returned 403 — all requests paused",
            detail={"path": path, "paused_minutes": round(cooldown / 60),
                    "consecutive_blocks": _consecutive_blocks,
                    "proxy_configured": bool(os.environ.get(_PROXY_ENV))},
            dedup_key="sofa_blocked", dedup_hours=1)
        raise SofascoreBlocked(f"403 on {path}")
    # A 404 is an ANSWER, not a refusal. Sofascore returns one for a season
    # with no upcoming events, an event id that has aged out, and any path that
    # simply has no data behind it — all states a caller should decide about,
    # none of them a reason to stop talking to the host.
    if status == 404:
        raise SofascoreNotFound(f"404 on {path}")
    if 500 <= status < 600:
        raise SofascoreUnavailable(f"HTTP {status} on {path}")
    if status != 200:
        raise SofascoreBlocked(f"HTTP {status} on {path}")
    # Answered — so whatever was refusing us has stopped. Back to the tight
    # cooldown, or a restored proxy would inherit the six-hour wait its
    # predecessor earned.
    _consecutive_blocks = 0
    return payload


async def _record_direct_block() -> None:
    """Switch to the proxy and write down that direct is banned."""
    global _egress_direct
    from datetime import datetime, timezone as _tz
    from app.database import AsyncSessionLocal
    from app.services import settings as st

    _egress_direct = False
    async with AsyncSessionLocal() as db:
        await st.set_setting(db, st.SOFA_EGRESS, st.SOFA_EGRESS_PROXY)
        await st.set_setting(db, st.SOFA_DIRECT_BLOCKED_AT,
                             datetime.now(_tz.utc).isoformat())
        await db.commit()
    await app_log("warning", "sofascore",
                  "Direct route refused — switched to the residential proxy",
                  detail={"cooloff_hours": round(DIRECT_COOLOFF / 3600)},
                  dedup_key="sofa_egress_to_proxy", dedup_hours=6)


async def load_egress(db) -> bool:
    """Adopt the stored route at startup. Returns True when going direct."""
    global _egress_direct
    from app.services import settings as st

    stored = await st.get_setting(db, st.SOFA_EGRESS)
    # No proxy configured at all: direct is the only way out, whatever is
    # stored. Nothing to fall back to, so nothing to decide.
    if not os.environ.get(_PROXY_ENV):
        _egress_direct = True
    else:
        _egress_direct = stored == st.SOFA_EGRESS_DIRECT
    return _egress_direct


async def probe_direct(db) -> bool:
    """Try the free route once, and adopt it if it answers. Returns True if
    we are now direct.

    ONE request, and only when there is something to gain and little to lose:
    already on the proxy, a proxy actually configured, the circuit closed, and
    the last direct refusal well behind us. Everything else declines silently —
    the point of the cooloff is that a banned IP is left completely alone, not
    polled politely.
    """
    from datetime import datetime, timezone as _tz
    from app.services import settings as st

    if _egress_direct or not os.environ.get(_PROXY_ENV):
        return _egress_direct
    if blocked_for() > 0:
        return False
    blocked_at = await st.get_setting(db, st.SOFA_DIRECT_BLOCKED_AT)
    if blocked_at:
        try:
            age = (datetime.now(_tz.utc)
                   - datetime.fromisoformat(blocked_at)).total_seconds()
        except ValueError:
            age = DIRECT_COOLOFF + 1
        if age < DIRECT_COOLOFF:
            return False

    # Deliberately NOT through _get: that would pace, trip the breaker and
    # count a refusal here against the proxy route, which is not the one being
    # tested. A bare probe, and a 403 costs only this request.
    status, _ = await _try_direct("/sport/tennis/events/live")
    return status == 200


async def _direct_may_be_tried() -> bool:
    """The probe's guards, for the fallback path: on the proxy, a proxy
    configured, and the last direct refusal at least DIRECT_COOLOFF ago."""
    from datetime import datetime, timezone as _tz
    from app.database import AsyncSessionLocal
    from app.services import settings as st
    if _egress_direct or not os.environ.get(_PROXY_ENV):
        return False
    async with AsyncSessionLocal() as db:
        blocked_at = await st.get_setting(db, st.SOFA_DIRECT_BLOCKED_AT)
    if not blocked_at:
        return True
    try:
        age = (datetime.now(_tz.utc) - datetime.fromisoformat(blocked_at)).total_seconds()
    except ValueError:
        return True
    return age >= DIRECT_COOLOFF


async def _try_direct(path: str) -> tuple:
    """ONE request straight out of this host. On 200 the direct route is
    adopted and stored; on anything else the refusal is timestamped so the
    route is left alone for DIRECT_COOLOFF. Returns (status, payload)."""
    global _egress_direct
    from datetime import datetime, timezone as _tz
    from app.database import AsyncSessionLocal
    from app.services import settings as st
    saved = _egress_direct
    try:
        _egress_direct = True
        status, payload = await asyncio.to_thread(_fetch, path)
    except Exception:
        status, payload = 0, None
    ok = status == 200
    _egress_direct = ok if ok else saved
    async with AsyncSessionLocal() as db:
        if ok:
            await st.set_setting(db, st.SOFA_EGRESS, st.SOFA_EGRESS_DIRECT)
        else:
            await st.set_setting(db, st.SOFA_DIRECT_BLOCKED_AT,
                                 datetime.now(_tz.utc).isoformat())
        await db.commit()
    if ok:
        await app_log("info", "sofascore",
                      "Direct route answered — leaving the proxy",
                      detail={"path": path},
                      dedup_key="sofa_egress_to_direct", dedup_hours=6)
    return status, payload


# ---------------------------------------------------------------------------
# Name matching (pure — no I/O, so it can be tested against a saved field)
# ---------------------------------------------------------------------------

def _toks(name: str) -> frozenset:
    return frozenset(_norm(name).split())


_HYPHENS = "-\u2010\u2011\u2012\u2013"


def _joined_toks(name: str) -> frozenset:
    """The words with every hyphen closed up instead of spaced.

    A HYPHEN IS TWO SPELLINGS. 2026 Korea Open (draw 146): our wildcards
    "Park So-hyun" and "Ku Yeon-woo" are "Sohyun Park" and "Yeonwoo Ku" in
    Sofascore's field. `_norm` spaces the hyphen, so {park, so, hyun} could
    never equal {sohyun, park}, and both entries went unresolved — no live
    score could reach their matches. Tried as well as `_toks`, never instead:
    "Auger-Aliassime" is two words in every source.
    """
    return frozenset(_norm(re.sub(f"[{_HYPHENS}]", "", name or "")).split())


def _spellings(name: str) -> set:
    """Every token set a name may be written as: split and joined."""
    return {_toks(name), _joined_toks(name)} - {frozenset()}


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
    __slots__ = ("toks", "joined", "surname", "initials", "team")

    def __init__(self, team: dict):
        name = team.get("name") or ""
        self.toks = _toks(name)
        self.joined = _joined_toks(name)
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
    joined = _joined_toks(name)
    attempts = (
        ("exact", [c for c in cands if c.toks == ours]),
        # Strict, like "exact", so it is tried before every loose rule: the
        # same words once each side's hyphens are closed up. Both sides, since
        # the hyphen may be ours ("Park So-hyun") or theirs ("Ye-Xin Ma").
        ("joined", [c for c in cands if c.joined == joined]),
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


# A BRACKET SHAPE WITH NOBODY IN IT. Sofascore publishes the tree before the
# names: SP Open 2026 came back as thirty teams called R16P1, R16P2 … every one
# of them `disabled`, two days before play (owner's /issues run, 2026-09-12).
# That is not a field, and mistaking it for one made the coverage check report
# "a tournament id but not one player resolved" — a real-sounding failure for
# the ordinary state of a draw Sofascore has not named yet.
_PLACEHOLDER_NAME = re.compile(r"^(?:R\d+P\d+|Q\d*P?\d*|TBD|BYE|QUALIFIER)$", re.I)


def _is_placeholder(team: dict) -> bool:
    """A slot in the tree rather than a person in the draw.

    Also every shape _PLACEHOLDER_SLOT knows ("Qf1", "WSF2", "QFP3"). That is
    the test _resolve_against_field uses to decide a bracket is unpublished and
    take its id on name alone; if this one disagreed, the same tree would be
    "unpublished" when the id was taken and "a field nobody matched" on every
    pass after, which is the coverage warning this exists to prevent.
    """
    if team.get("disabled"):
        return True
    name = (team.get("name") or "").strip()
    return bool(_PLACEHOLDER_NAME.match(name) or _PLACEHOLDER_SLOT.match(name))


def field_is_unnamed(field: list) -> bool:
    """True when Sofascore has the bracket but not the players.

    Every team a placeholder, and at least one of them — an empty field is a
    different state (`cup tree empty`) with its own message.
    """
    return bool(field) and all(_is_placeholder(t) for t in field)


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
        # Cached: the tournament list is the least volatile thing here, and
        # this is the request the identity path repeats most.
        payload = await _get_cached(f"/search/unique-tournaments?q={quote(term)}",
                                    CACHE_TTL_SEARCH)
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
    seasons = (await _get_cached(f"/unique-tournament/{uid}/seasons",
                                 CACHE_TTL_SEASONS)).get("seasons", [])
    y = str(year)
    return (next((s for s in seasons if str(s.get("year") or "") == y), None)
            or next((s for s in seasons if y in str(s.get("name") or "")), None))


def _is_qualifying_round(event: dict) -> bool:
    """Qualifying arrives in the same list as the main draw and starts days
    earlier, so its first match would drag a pick deadline back before the
    bracket was even released."""
    info = event.get("roundInfo") or {}
    name = f"{info.get('name') or ''} {info.get('slug') or ''}".lower()
    return "qualif" in name


def _is_singles_event(event: dict) -> bool:
    """A doubles pairing is one "team" with two names in it, and we hold no
    doubles draw."""
    for side in ("homeTeam", "awayTeam"):
        team = event.get(side) or {}
        if team.get("type") == 2 or "/" in (team.get("name") or ""):
            return False
    return True


def main_draw_starts(payload: dict) -> list:
    """Every scheduled MAIN-DRAW SINGLES start in a season payload, earliest
    first, as aware UTC datetimes. Pure, so it can be tested on a real
    payload without a request."""
    from datetime import datetime as _dt
    out = []
    for e in (payload or {}).get("events", []):
        ts = e.get("startTimestamp")
        if not ts or _is_qualifying_round(e) or not _is_singles_event(e):
            continue
        out.append(_dt.fromtimestamp(int(ts), timezone.utc))
    return sorted(out)


async def first_main_draw_start(uid: int, season_id: int):
    """WHEN THE MAIN DRAW ACTUALLY STARTS, from Sofascore's own schedule.

    Wikipedia gives the calendar — the date range, months ahead, which is what
    every release date and ranking week is built on — but it cannot say when
    the first ball is, and that is what a pick deadline is. ESPN's board can,
    once an order of play is published, and fills the gap before that with a
    placeholder that already set one deadline eighteen hours early.

    This is the real timestamp: one request, the season's upcoming events,
    qualifying and doubles dropped, earliest first. None when Sofascore has
    not scheduled the main draw yet — which is the ordinary state until a day
    or two out, and the caller keeps its estimate.
    """
    payload = await _get(f"/unique-tournament/{uid}/season/{season_id}/events/next/0")
    starts = main_draw_starts(payload)
    return starts[0] if starts else None


async def _cuptree_of(uid: int, season_id: int) -> dict:
    """The whole cup tree. One request, and the caller decides what to read.

    Split out from _field_of because the payload carries far more than the
    names it was reducing to — bracket position, seed, entry type and the byes,
    i.e. everything Wikipedia was sole author of (see sofa_draw_shape.py). A
    caller that wants both gets both from one request.
    """
    return await _get_cached(
        f"/unique-tournament/{uid}/season/{season_id}/cuptrees", CACHE_TTL_CUPTREE)


async def _field_of(uid: int, season_id: int) -> list:
    payload = await _cuptree_of(uid, season_id)
    return _main_draw_teams(payload.get("cupTrees", []))


# How far the main draw's first match may sit from our stored start_date and
# still be the same event. Our date can be a discovery placeholder (the Monday
# of the tournament's week) and an extended-format event starts days later, so
# this has to be loose — but it is the check that separates two events sharing
# a city's name in one year, and those were 25 to 307 days apart (see
# services/events.py), so a week is loose enough and nowhere near enough to
# join them.
IDENTITY_DATE_SLACK_DAYS = 7


def _next_power_of_two(n: int) -> int:
    """The bracket a field of n plays in: 28 -> 32, 96 -> 128, 32 -> 32."""
    if n <= 1:
        return max(n, 1)
    return 1 << (n - 1).bit_length()


def _geometry_agrees(draw_size: int, bracket_size: int) -> bool:
    """Whether a cup tree's bracket could be this draw's.

    Compares BRACKETS, not entrant counts, because `draws.draw_size` is
    recorded both ways in practice — discovery reads the entrant count off the
    main article (28) while a scrape normalises it to the bracket
    (notifications.py:859, "that column holds the bracket size"). Rounding both
    to the next power of two makes 28 and 32 the same answer, and still
    separates a 250 from a 1000.
    """
    if not draw_size or not bracket_size:
        return False
    return _next_power_of_two(draw_size) == bracket_size


# The scheduler's floor on fieldless identity lookups. bootstrap_draw calls
# resolve_without_field last, after the cheap sources; when the floor says
# "not yet" this makes that call decline instantly and cost nothing.
_identity_allowed = True


class identity_gate:
    """`with identity_gate(False): ...` makes resolve_without_field decline."""

    def __init__(self, allowed: bool):
        self.allowed = allowed
        self.prev = True

    def __enter__(self):
        global _identity_allowed
        self.prev = _identity_allowed
        _identity_allowed = self.allowed
        return self

    def __exit__(self, *exc):
        global _identity_allowed
        _identity_allowed = self.prev
        return False


async def resolve_without_field(draw: Draw) -> Optional[tuple]:
    """Identify a tournament for a draw that has NO entries to match against.

    THE GAP THIS CLOSES. `_resolve_against_field` verifies a candidate by
    comparing its published field to OUR draw_entries, which is what makes its
    looser name rules safe — and which a draw with no entries cannot do. That
    is why Hangzhou sat with `sofa_tournament_id` NULL on 2026-09-21 while its
    shape was published: no field, no identity, no shape, no draw. Chicken and
    egg.

    WHAT REPLACES THE FIELD AS EVIDENCE. Three facts that do not depend on
    knowing who is in the draw, and all three must hold:

      the TOUR      `_is_singles_tour_event` already requires the candidate's
                    category to match the draw's gender
      the BRACKET   the cup tree's bracket size must be the one a field of our
                    draw_size plays in — a 32 for a 28, a 128 for a 96
      the DATES     the main draw's first match must fall within
                    IDENTITY_DATE_SLACK_DAYS of our start_date

    AND THE ANSWER MUST BE UNIQUE. If two candidates satisfy all three this
    returns None and says so, because the whole point of the field check was
    that a name is not an identity — "ATP Hong Kong" is two different
    tournaments ten months apart, and picking the first is how January's event
    turned up under ACTIVE in September. NULL IS NOT A DECISION applies here
    exactly as it does to a player: an unresolved draw is reported, never
    guessed at.

    Returns (uid, season_id, shape) or None. Makes no writes.
    """
    from app.services.sofa_draw_shape import draw_shape, main_draw_start

    if not _identity_allowed:
        return None                      # the scheduler's floor: not this pass
    if not draw.draw_size or not draw.start_date:
        return None                      # nothing to corroborate against

    candidates = await _candidate_tournaments(draw)
    if not candidates:
        return None

    passed: list = []
    for cand in candidates:
        uid = cand["id"]
        season = await _season_for(uid, draw.year)
        if not season:
            continue
        try:
            payload = await _cuptree_of(uid, season["id"])
        except SofascoreNotFound:
            # No cup tree yet is the ordinary state until a day or two out.
            continue
        shape = draw_shape(payload)
        if not shape or not shape.entrant_count:
            continue
        if not _geometry_agrees(draw.draw_size, shape.bracket_size):
            continue
        if field_is_unnamed(_main_draw_teams(payload.get("cupTrees", []))):
            # The bracket exists but is a row of placeholders (R16P1, R16P2 …).
            # It corroborates nothing about WHICH event this is.
            continue
        # The cup tree's own block timestamps first: free, and they work for a
        # tournament already played as well as one still to come. /events/next
        # only knows the future and 404s on a finished event — which is how
        # this check first failed, against Guadalajara.
        start = main_draw_start(payload)
        if start is None:
            try:
                start = await first_main_draw_start(uid, season["id"])
            except SofascoreNotFound:
                start = None
        if start is None:
            continue
        if abs((start - draw.start_date).days) > IDENTITY_DATE_SLACK_DAYS:
            continue
        passed.append((uid, season["id"], shape, cand, start))

    if len(passed) == 1:
        uid, season_id, shape, cand, start = passed[0]
        logger.info(
            "Resolved %s %s (%s) without a field: uid %s season %s — "
            "%s, bracket %d, %d entrants, starts %s against our %s",
            draw.year, draw.name, draw.gender, uid, season_id,
            cand.get("name"), shape.bracket_size, shape.entrant_count,
            start, draw.start_date)
        return uid, season_id, shape

    if len(passed) > 1:
        await app_log(
            "warning", "sofascore",
            f"Refusing to identify {draw.year} {draw.name} ({draw.gender}) "
            f"without a field: {len(passed)} candidates satisfy tour, bracket "
            f"and dates — " + ", ".join(
                f"{c.get('name')} (uid {u}, starts {s})"
                for u, _, _, c, s in passed[:4]),
            {"draw_id": draw.id,
             "candidates": [{"uid": u, "name": c.get("name"), "start": str(s)}
                            for u, _, _, c, s in passed]},
            dedup_key=f"ambiguous_identity_{draw.id}", dedup_hours=24)
    return None


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
    ours = [(_spellings(e.name), e) for e in entries if e.name]
    if not ours:
        return None

    best = None
    # Candidates whose season exists but whose bracket is not published yet.
    # See the fallback below for why they are worth remembering.
    unpublished = []
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
        # A cuptree of R16P1, R16P2, ... is a bracket Sofascore has created but
        # not filled in. There are no names to overlap against, which is not the
        # same as no match.
        named = [t for t in field
                 if not _PLACEHOLDER_SLOT.match(str(t.get("name") or ""))]
        if not named:
            unpublished.append((cand["id"], season["id"], field))
            continue
        # Overlap is scored on the NAMES, but the raw cuptree is what gets
        # handed back — the caller needs the unfilled slots to tell a
        # half-published bracket from a complete one.
        theirs = set().union(*(_spellings(t.get("name") or "") for t in named))
        overlap = sum(1 for ts, _ in ours if ts & theirs) / len(ours)
        if best is None or overlap > best[0]:
            best = (overlap, cand["id"], season["id"], field)

    if best is not None and best[0] >= _MIN_FIELD_OVERLAP:
        return best[1], best[2], best[3]

    # NOTHING TO CHECK AGAINST IS NOT THE SAME AS NOTHING MATCHING.
    #
    # A tournament publishes its bracket a day or two before it starts, and
    # until then its cuptree is a row of placeholders. Overlap cannot be
    # computed, so this returned None — and a draw with no uniqueTournament id
    # is invisible to the live poller, the results sweep and the doubles sweep
    # alike. Monterrey sat like that on the morning it started and had to be
    # stamped by hand.
    #
    # So: when exactly ONE candidate survives the name-and-category filter and
    # its bracket simply is not up yet, take it. One candidate is not a choice,
    # and the alternative is no scoring at all on the day of play.
    #
    # This is the ONLY place a tournament is accepted without checking its
    # field, and it is deliberately not silent about it. If the guess is wrong,
    # no player will ever resolve against it, and the coverage check in
    # sofa_resolver says exactly that — "a tournament id but not one player
    # resolved" — within the hour of the names going up, or of play being due.
    # A wrong id that announces itself beats a correct one that arrives after
    # the tournament.
    #
    # The tree it was accepted on is handed back as it is, placeholders and
    # all. This returned [] — so resolve_draw read the pass that took the id as
    # "cup tree empty" rather than "published without names", and the coverage
    # check warned on the very pass that had just done the right thing.
    if len(unpublished) == 1:
        uid, season_id, field = unpublished[0]
        logger.info("Sofascore: accepting %s season %s for %s %s on name alone "
                    "— its bracket is not published yet",
                    uid, season_id, draw.name, draw.gender)
        return uid, season_id, field
    return None


async def _stamp_number_of_sets(db: AsyncSession, draw: Draw) -> None:
    """Record how many sets this tournament plays, from Sofascore's own field.

    `uniqueTournament.numberOfSets` is STATED — 5 for a men's Slam, 3 for
    everything else measured so far — where schedule.py::_best_of had to derive
    it from category, gender and stage and carried a comment conceding those
    were unverified guesses. A stated format beats a good guess.

    One request per draw, once, on a path that already runs rarely. Never
    allowed to fail the resolve: the ids are the point of that function and a
    missing format simply leaves the guess in place.
    """
    try:
        payload = await _get(f"/unique-tournament/{draw.sofa_tournament_id}")
        sets = ((payload or {}).get("uniqueTournament") or {}).get("numberOfSets")
    except Exception as exc:                                       # noqa: BLE001
        logger.info("numberOfSets unavailable for draw %s: %s", draw.id, exc)
        return
    # Tennis is best-of-3 or best-of-5 and nothing else; anything outside that
    # is a field we have misread, and a wrong format is worse than no format.
    if sets in (3, 5) and draw.sofa_number_of_sets != sets:
        draw.sofa_number_of_sets = sets
        await db.commit()
        logger.info("draw %s plays best of %d (Sofascore)", draw.id, sets)


async def resolve_tournament(db: AsyncSession, draw: Draw) -> Optional[tuple]:
    """
    Persisted (uniqueTournament id, season id) for a draw, resolving if needed.

    Already-stamped ids are returned untouched — same rule as atp_ids, and for
    the same reason: a search that comes back empty or ambiguous must leave a
    working id alone rather than replace it with nothing.
    """
    if draw.sofa_tournament_id and draw.sofa_season_id:
        # Ids already known, but the FORMAT may not be — this is one request
        # per draw, once, and only for a draw that has never had it.
        if draw.sofa_number_of_sets is None:
            await _stamp_number_of_sets(db, draw)
        return draw.sofa_tournament_id, draw.sofa_season_id

    entries = (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == draw.id,
                                DrawEntry.name.isnot(None)))).scalars().all()
    found = await _resolve_against_field(draw, entries)
    if found is None:
        return None
    draw.sofa_tournament_id, draw.sofa_season_id = found[0], found[1]
    await db.commit()
    await _stamp_number_of_sets(db, draw)
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
    all_rows = (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id == draw.id,
                                DrawEntry.name.isnot(None)))).scalars().all()
    entries = [e for e in all_rows if (e.name or "").strip()]
    # Slots the draw itself has not filled yet — qualifiers, mostly. Counted
    # (not just filtered out) because the alert below gates on it: see there.
    report["blank_slots"] = len(all_rows) - len(entries)
    report["total"] = len(entries)
    if not entries:
        report["error"] = "draw has no named entries yet"
        return report

    if draw.sofa_tournament_id and draw.sofa_season_id:
        payload = await _cuptree_of(draw.sofa_tournament_id, draw.sofa_season_id)
        field = _main_draw_teams(payload.get("cupTrees", []))
        # EVIDENCE BEFORE AUTHORITY. The same payload states the draw's shape —
        # slot, seed, entry type, byes — which Wikipedia is currently sole
        # author of. Comparing the two here costs NO extra request and builds
        # the record the decision to demote Wikipedia should be made on.
        # Never writes, and never raises into the resolver.
        try:
            from app.services.sofa_draw_shape import (
                compare_to_entries, disagreement_summary, draw_shape)

            shape = draw_shape(payload)
            if shape and shape.entrant_count:
                cmp = compare_to_entries(shape, all_rows)
                report["shape_matched"] = cmp["matched"]
                # FILL WHAT WE LACK AND SOFASCORE STATES. Tennis Explorer does
                # not always print seeds two days out (Chengdu had none the
                # afternoon Hangzhou had all eight) and a Wikipedia draft can
                # miss an entry type; the cup tree's teamSeed carries both
                # once its events exist. Only ever fills a NULL — a seed we
                # hold is never overwritten here; disagreement is logged above.
                filled = 0
                for mine, seed, entry_type in cmp.get("fillable", []):
                    if seed is not None and mine.seed is None:
                        mine.seed, filled = seed, filled + 1
                    if entry_type and not mine.entry_type:
                        mine.entry_type, filled = entry_type, filled + 1
                if filled:
                    await db.commit()
                    report["shape_filled"] = filled
                    await app_log(
                        "info", "sofascore",
                        f"Filled {filled} seed/entry-type value(s) for {draw.year} "
                        f"{draw.name} ({draw.gender}) from the cup tree",
                        {"draw_id": draw.id, "filled": filled})
                why = disagreement_summary(cmp)
                report["shape_disagreement"] = why
                if why:
                    await app_log(
                        "warning", "sofascore",
                        f"Draw shape disagrees with Wikipedia for {draw.year} "
                        f"{draw.name} ({draw.gender}): {why}",
                        {"draw_id": draw.id, "matched": cmp["matched"],
                         "position": cmp["position"][:10], "seed": cmp["seed"][:10],
                         "entry_type": cmp["entry_type"][:10],
                         "byes_ours": cmp["byes_ours"],
                         "byes_sofascore": cmp["byes_sofascore"]},
                        dedup_key=f"shape_disagree_{draw.id}", dedup_hours=24)
                else:
                    logger.info(
                        "Draw shape agrees with Wikipedia for %s %s (%s): "
                        "%d entrant(s), byes %s",
                        draw.year, draw.name, draw.gender,
                        cmp["matched"], cmp["byes_sofascore"])
        except Exception as exc:      # a comparison must never break resolution
            logger.warning("Draw shape comparison failed for draw %s: %s",
                           draw.id, exc)
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
    # The bracket published, the names not yet — an ordinary state days out,
    # and NOT a matching failure. Said here so the coverage check can tell the
    # two apart instead of inferring a fault from "nobody stamped".
    if field_is_unnamed(field):
        report["field_unnamed"] = True
        report["error"] = ("Sofascore has published the bracket shape but not "
                           "the names yet")
        return report
    if not field:
        report["error"] = "cup tree empty (draw not published on Sofascore yet)"
        return report
    cands = [_Candidate(t) for t in field]

    # An id already used by another entry in this same draw means the field held
    # two names that collapsed onto one player. Taking the second would silently
    # move a live score onto the wrong bracket slot, so both are left unresolved
    # and reported instead.
    taken = {e.sofa_player_id for e in entries if e.sofa_player_id}
    by_id = {t.get("id"): t for t in field if isinstance(t, dict) and t.get("id")}
    dirty = False
    for entry in entries:
        if entry.sofa_player_id and not force:
            report["already"] += 1
            # Their spelling, for an entry resolved before we kept it.
            their = (by_id.get(entry.sofa_player_id) or {}).get("name")
            if their and not entry.sofa_name:
                entry.sofa_name = their
                dirty = True
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
        if team.get("name"):
            entry.sofa_name = team["name"]
        taken.add(team["id"])
        dirty = True
        report["resolved"] += 1
        report["rules"][rule] = report["rules"].get(rule, 0) + 1

    if dirty:
        await db.commit()

    # A name we cannot place is only a problem once there is somewhere to place
    # it. While Sofascore's bracket still has unfilled slots the missing players
    # are the ones going INTO those slots, and saying so before the draw is even
    # out is reporting the ordinary passage of time as a fault.
    #
    # OUR OWN blank slots gate it for the same reason, and this half was
    # missing: while qualifier slots in our draw are still empty, Sofascore's
    # bracket is settling too — the four Monterrey names this warned about at
    # 24/28 entries all resolved on the next pass once the qualifiers landed,
    # and the alert had spent itself announcing the retry ladder doing its job.
    # When the draw is full and a name still cannot be placed, THAT is the
    # state retrying does not fix, and it alerts as before.
    incomplete = (report["blank_slots"] > 0
                  or any(_PLACEHOLDER_SLOT.match(str(t.get("name") or ""))
                         for t in field))
    if report["unresolved"] and not incomplete:
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

# The floor for a draw nothing on can score yet — no tournament id, or one and
# not a single player stamped against it. Hourly, the resolver's own cadence:
# these are waiting on a bracket going up, not on names Sofascore lacks.
DARK_RETRY_HOURS = 1.0

# A bracket slot Sofascore has created but not yet filled. It writes these in
# more shapes than one — "R16P1" and "QFP3", but also "Qf1".."Qf8" for the eight
# qualifier slots and "WQF1"/"WSF2" for a winner-of slot — and matching only the
# P-form counted twelve empty slots in Monterrey as published players. That
# makes a half-published bracket look complete, which matters twice: the field
# reads fuller than it is, and a cuptree of nothing BUT placeholders is no
# longer recognised as unpublished, which is the one case the fallback below
# exists to catch.
_PLACEHOLDER_SLOT = re.compile(r"^W?(?:R\d+|QF|SF|F|Q)P?\d+$", re.I)


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
        #
        # A KNOWN ID WITH NOBODY STAMPED IS THE SAME DRAW. The id can be taken
        # from the tree alone, before a single name is in it — Korea Open 2026
        # had 2604 two days out, and a cuptree of thirty disabled R16P slots.
        # It scores nothing either, and fills the same hour. On the six-hour
        # floor it was looked at once in six passes, and the coverage check,
        # which can only trust what THIS pass saw, called the other five a
        # failure (2026-09-19).
        dark = (not draw.sofa_tournament_id
                or (await db.execute(
                    select(DrawEntry.id).where(
                        DrawEntry.draw_id == draw.id,
                        DrawEntry.sofa_player_id.isnot(None)).limit(1))).first() is None)
        wait = min(retry_hours, DARK_RETRY_HOURS) if dark else retry_hours
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
