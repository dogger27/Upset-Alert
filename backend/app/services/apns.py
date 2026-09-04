"""
Apple Push Notification service: the transport, and only the transport.

What to send and when to send it live elsewhere — this file knows how to get
one payload to one token and what Apple's answer means. Same separation
push.py keeps from push_content.py, and for the same reason: a transport that
also decides policy cannot be tested without inventing the policy.

Deliberately NOT a third-party APNs library. This codebase owns its transports
where the details matter (sofascore.py owns curl_cffi because the TLS
fingerprint IS the feature), httpx is already a dependency used everywhere, and
APNs is one POST with five headers. A library would add a dependency to hide
about forty lines.

NEVER RAISES. Every call returns an ApnsResult. A push channel outage must not
take down a score poller, which is the contract push.py already sets.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

PRODUCTION_HOST = "https://api.push.apple.com"
SANDBOX_HOST = "https://api.sandbox.push.apple.com"

# Apple requires the provider token be refreshed at least hourly and REJECTS a
# refresh more often than every 20 minutes (TooManyProviderTokenUpdates). Fifty
# minutes sits safely inside both bounds.
_TOKEN_TTL = 50 * 60

# Live Activity payloads are capped at 4KB. Assert well under it so a payload
# that has quietly grown is caught here rather than by Apple.
_MAX_PAYLOAD = 3072

# ── What Apple's `reason` means ─────────────────────────────────────────────

# The token is finished. Stop using it — but see the 410 note in send(): a
# timestamp check has to gate the actual deactivation.
#
# WHICH token is finished depends on the push type, and that distinction cost
# a live outage on 2026-09-04 01:49 UTC. A `liveactivity` push is addressed to
# a PER-ACTIVITY token, so every one of these reasons then describes that one
# activity — dismissed, ended, or registered a moment too late — and says
# nothing about the device. The old code disabled the whole AppDevice on one
# BadDeviceToken from one activity, the dispatcher's read filters disabled
# devices out, and every card on the phone froze mid-match while the matches
# played on. Only an `alert` push (device token) may kill a device; see
# ApnsResult.token_is_dead / activity_is_over.
DEAD_TOKEN = frozenset({
    "Unregistered", "BadDeviceToken", "DeviceTokenNotForTopic",
})

# The ACTIVITY is over, not the device. Entirely normal: the user dismissed it,
# or it aged out. Not an error, and it must never disable a device.
# ExpiredToken (410) is Apple's own wording for an activity token that has
# aged out; ExpiredActivityToken was the guess this set began with.
ACTIVITY_OVER = frozenset({"ExpiredActivityToken", "ExpiredToken"})

# We built the request wrong. Never retry, never blame the token, and say so
# loudly — every one of these is a bug on this side.
OUR_BUG = frozenset({
    "BadTopic", "TopicDisallowed", "BadCollapseId", "BadExpirationDate",
    "BadPriority", "BadMessageId", "PayloadEmpty", "PayloadTooLarge",
    "MissingDeviceToken", "BadPath", "MethodNotAllowed",
})


@dataclass
class ApnsResult:
    ok: bool
    status: Optional[int] = None
    reason: Optional[str] = None
    apns_id: Optional[str] = None
    # Set when Apple reports a token as invalid AS OF a moment in time.
    unregistered_at: Optional[datetime] = None
    # What kind of token the request addressed — send() stamps it. The two
    # properties below are meaningless without it: the same reason string
    # names a dead DEVICE on an alert push and a dead ACTIVITY on a
    # liveactivity push.
    push_type: Optional[str] = None

    @property
    def token_is_dead(self) -> bool:
        """The DEVICE token is finished — only ever true for an alert push."""
        return self.push_type != "liveactivity" and self.reason in DEAD_TOKEN

    @property
    def activity_is_over(self) -> bool:
        """This one ACTIVITY is finished; the device is fine. Any dead-token
        reason on a liveactivity push lands here, never on token_is_dead."""
        return (self.push_type == "liveactivity"
                and (self.reason in ACTIVITY_OVER or self.reason in DEAD_TOKEN))


def apns_enabled() -> bool:
    """Configured well enough to try, mirroring push.py's push_enabled().

    A missing key disables the channel rather than erroring, so development and
    any instance without credentials simply skips it.
    """
    if not (settings.apns_key_id and settings.apns_team_id
            and settings.apns_bundle_id):
        return False
    try:
        with open(settings.apns_key_path, "r"):
            return True
    except OSError:
        return False


# ── Provider token ──────────────────────────────────────────────────────────

_token: Optional[str] = None
_token_made_at: float = 0.0
_key_pem: Optional[str] = None


def _read_key() -> str:
    global _key_pem
    if _key_pem is None:
        with open(settings.apns_key_path, "r") as fh:
            _key_pem = fh.read()
    return _key_pem


def _provider_token(force: bool = False) -> str:
    """The ES256 JWT Apple wants in the authorization header.

    Signed with python-jose, already a dependency and already what
    core/security.py uses — no new crypto library for one signature.
    """
    global _token, _token_made_at
    now = time.time()
    if force or _token is None or (now - _token_made_at) > _TOKEN_TTL:
        from jose import jwt
        _token = jwt.encode(
            {"iss": settings.apns_team_id, "iat": int(now)},
            _read_key(),
            algorithm="ES256",
            headers={"kid": settings.apns_key_id},
        )
        _token_made_at = now
    return _token


# ── Client ──────────────────────────────────────────────────────────────────

_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        async with _client_lock:
            if _client is None or _client.is_closed:
                _client = httpx.AsyncClient(
                    http2=True,
                    timeout=httpx.Timeout(10.0),
                    # APNs sends GOAWAY periodically and this is a residential
                    # connection behind consumer NAT, which drops idle
                    # conversations in about five minutes. Keep the pool small
                    # and let it expire rather than discovering a dead socket.
                    limits=httpx.Limits(max_keepalive_connections=4,
                                        keepalive_expiry=240.0),
                )
    return _client


async def aclose() -> None:
    """Shut the pool down cleanly on app shutdown."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


# ── Send ────────────────────────────────────────────────────────────────────

def _host(env: Optional[str]) -> str:
    return SANDBOX_HOST if (env or settings.apns_default_env) == "sandbox" else PRODUCTION_HOST


async def send(
    *,
    token: str,
    payload: dict,
    push_type: str = "alert",          # alert | liveactivity
    env: Optional[str] = None,
    priority: int = 10,
    expiration: Optional[int] = None,
    collapse_id: Optional[str] = None,
    topic: Optional[str] = None,
) -> ApnsResult:
    """One payload to one token. Never raises. Every result carries the
    push_type it was sent as, which is what makes token_is_dead and
    activity_is_over answer the right question (see DEAD_TOKEN)."""
    result = await _send(token=token, payload=payload, push_type=push_type,
                         env=env, priority=priority, expiration=expiration,
                         collapse_id=collapse_id, topic=topic)
    result.push_type = push_type
    return result


async def _send(
    *,
    token: str,
    payload: dict,
    push_type: str,
    env: Optional[str],
    priority: int,
    expiration: Optional[int],
    collapse_id: Optional[str],
    topic: Optional[str],
) -> ApnsResult:
    """
    One payload to one token. Never raises.

    `env` is the DEVICE's environment, not a server setting: which host a token
    is valid on is a property of the build that produced it — Xcode gives
    sandbox tokens, TestFlight and the App Store give production ones.
    """
    if not apns_enabled():
        return ApnsResult(ok=False, reason="not_configured")

    body = json.dumps(payload, separators=(",", ":")).encode()
    if len(body) > _MAX_PAYLOAD:
        # Ours to fix, and Apple would only tell us the same thing more slowly.
        logger.error("APNs payload too large: %d bytes (cap %d) — %s",
                     len(body), _MAX_PAYLOAD, str(payload)[:200])
        return ApnsResult(ok=False, reason="PayloadTooLarge")

    # The .push-type.liveactivity suffix is mandatory for Live Activities and
    # is the single most common cause of BadTopic.
    if topic is None:
        topic = settings.apns_bundle_id
        if push_type == "liveactivity":
            topic += ".push-type.liveactivity"

    headers = {
        "apns-push-type": push_type,
        "apns-topic": topic,
        "apns-priority": str(priority),
    }
    if expiration is not None:
        # NOTE: 0 means "discard if not immediately deliverable", NOT "never
        # expires". Callers pass an absolute epoch.
        headers["apns-expiration"] = str(expiration)
    if collapse_id:
        headers["apns-collapse-id"] = collapse_id[:64]

    result = await _post(token, body, headers, _host(env))

    # SELF-HEALING ON THE COMMONEST MISCONFIGURATION.
    # A sandbox token sent to production (or the reverse) comes back
    # BadDeviceToken and looks exactly like a dead token. One retry against the
    # other host costs one request in a rare path and turns a silent
    # non-delivery — the worst failure mode here — into a fact the caller can
    # act on. The caller is expected to rewrite the device's stored env when
    # `env_corrected` comes back set.
    if result.reason == "BadDeviceToken":
        other = SANDBOX_HOST if _host(env) == PRODUCTION_HOST else PRODUCTION_HOST
        retry = await _post(token, body, headers, other)
        if retry.ok:
            logger.warning(
                "APNs token was registered for the OTHER environment; "
                "delivered via %s — correct the device's apns_env", other)
            retry.reason = "env_corrected"
            return retry

    return result


async def _post(token: str, body: bytes, headers: dict, host: str) -> ApnsResult:
    """A single attempt, with the retries Apple's own behaviour requires."""
    url = f"{host}/3/device/{token}"

    for attempt in range(3):
        try:
            client = await _get_client()
            hdrs = dict(headers)
            hdrs["authorization"] = f"bearer {_provider_token()}"

            # THE LAST LINE BEFORE THE NETWORK — same choke point as
            # push._send_one and email._send. Staging runs a copy of the
            # production database and will therefore hold real device tokens,
            # so this guard has to sit where no future caller can route around
            # it.
            if not settings.outbound_notifications:
                logger.warning("BLOCKED outbound APNs to %s… — "
                               "outbound_notifications=false", token[:12])
                return ApnsResult(ok=False, reason="blocked")

            resp = await client.post(url, content=body, headers=hdrs)
        except (httpx.RemoteProtocolError, httpx.ConnectError,
                httpx.ReadError, httpx.WriteError) as exc:
            # Routine rather than exceptional: APNs sends GOAWAY, and consumer
            # NAT drops idle connections. Rebuild the pool and try again.
            logger.info("APNs connection reset (%s); rebuilding client", type(exc).__name__)
            await aclose()
            if attempt == 2:
                return ApnsResult(ok=False, reason="connection_failed")
            await asyncio.sleep(0.5 * (attempt + 1))
            continue
        except Exception as exc:                                  # noqa: BLE001
            logger.warning("APNs send failed: %s", exc)
            return ApnsResult(ok=False, reason="transport_error")

        apns_id = resp.headers.get("apns-id")
        if resp.status_code == 200:
            return ApnsResult(ok=True, status=200, apns_id=apns_id)

        reason, ts = _parse_error(resp)

        if resp.status_code == 403 and reason in (
                "ExpiredProviderToken", "InvalidProviderToken", "MissingProviderToken"):
            # Force a new JWT and try once more before believing it.
            _provider_token(force=True)
            if attempt == 0:
                continue
            return ApnsResult(ok=False, status=403, reason=reason, apns_id=apns_id)

        if resp.status_code in (429, 500, 503):
            if attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

        if reason in OUR_BUG:
            logger.error("APNs rejected our request: %s (status %s, topic %s)",
                         reason, resp.status_code, headers.get("apns-topic"))

        return ApnsResult(ok=False, status=resp.status_code, reason=reason,
                          apns_id=apns_id, unregistered_at=ts)

    return ApnsResult(ok=False, reason="retries_exhausted")


def _parse_error(resp: httpx.Response):
    """Apple's JSON error body: {"reason": "...", "timestamp": ms}."""
    try:
        data = resp.json()
    except Exception:                                             # noqa: BLE001
        return (f"http_{resp.status_code}", None)
    reason = data.get("reason")
    ts = data.get("timestamp")
    when = None
    if ts:
        try:
            # Milliseconds since the epoch, and it means "the token stopped
            # being valid at this moment" — which is only actionable when
            # compared against when we learned about the token.
            when = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        except Exception:                                         # noqa: BLE001
            when = None
    return (reason, when)
