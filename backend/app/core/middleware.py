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
_API_LIMIT = 300     # per minute per IP (general endpoints)
_WINDOW = 60.0       # seconds


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


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip = _client_ip(request)
        path = request.url.path

        if path in _AUTH_PATHS and request.method == "POST":
            key, limit = f"auth:{ip}", _AUTH_LIMIT
        else:
            key, limit = f"api:{ip}", _API_LIMIT

        if not _window.allow(key, limit):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": "60"},
            )

        return await call_next(request)
