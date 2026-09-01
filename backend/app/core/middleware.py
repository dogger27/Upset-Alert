import threading
import time
from collections import defaultdict

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers[name] = value
        return response


# ── Rate limiting ──────────────────────────────────────────────────────────────

# Tight limit for authentication endpoints (brute-force protection)
_AUTH_PATHS = frozenset({
    "/auth/login",
    "/auth/register",
    "/auth/forgot-password",
    "/auth/reset-password",
})
_AUTH_LIMIT = 8      # per minute
_API_LIMIT = 300     # per minute (general endpoints)
_WINDOW = 60.0       # seconds

# Registration and Live Activity lifecycle. Tighter than the general limit
# because a client retry loop is the realistic failure here, not a person —
# and a bug in one install should not spend the whole budget for the account.
_APP_PREFIXES = ("/app/devices", "/app/live-activities")
_APP_LIMIT = 60


class _SlidingWindow:
    def __init__(self):
        self._lock = threading.Lock()
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = time.monotonic()

    def allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        cutoff = now - _WINDOW
        with self._lock:
            hits = self._buckets[key]
            trimmed = [t for t in hits if t > cutoff]
            if len(trimmed) >= limit:
                return False
            trimmed.append(now)
            self._buckets[key] = trimmed
            # Prune stale keys every 5 min to prevent unbounded memory growth
            if now - self._last_cleanup > 300:
                self._last_cleanup = now
                self._buckets = defaultdict(list, {k: v for k, v in self._buckets.items() if v})
            return True


_window = _SlidingWindow()


def _client_ip(request: Request) -> str:
    # CF-Connecting-IP is the real client IP set by Cloudflare (cannot be spoofed
    # by the client when the request arrives through the Cloudflare proxy).
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


def _actor(request: Request) -> str:
    """Who to charge this request to: the signed-in user, else the IP.

    KEYING ON IP ALONE DOES NOT SURVIVE A PHONE APP. Mobile carriers put
    thousands of subscribers behind one NAT address, and so does any office or
    university. Once native clients exist, an IP bucket is shared by strangers:
    one busy user throttles people they have never met, and the site looks
    broken for everyone on that carrier.

    The token is VERIFIED, not merely parsed. Reading the `sub` claim without
    checking the signature would let anyone mint their own bucket by inventing
    a user id — an easier limit to escape than the IP one it replaces.

    An unauthenticated or expired token falls back to the IP, which is correct:
    the request is anonymous, and rejecting it is the route's job rather than
    this middleware's.
    """
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        from app.core.security import decode_token
        subject = decode_token(auth[7:].strip())
        if subject:
            return f"u:{subject}"
    return f"ip:{_client_ip(request)}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in _AUTH_PATHS and request.method == "POST":
            # Deliberately still per IP. These endpoints are unauthenticated by
            # definition, and the limit exists to slow down someone guessing
            # passwords — charging it to the account being attacked would let
            # an attacker lock a victim out of their own login.
            key, limit = f"auth:{_client_ip(request)}", _AUTH_LIMIT
        elif path.startswith(_APP_PREFIXES):
            key, limit = f"app:{_actor(request)}", _APP_LIMIT
        else:
            key, limit = f"api:{_actor(request)}", _API_LIMIT

        if not _window.allow(key, limit):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": "60"},
            )

        return await call_next(request)
