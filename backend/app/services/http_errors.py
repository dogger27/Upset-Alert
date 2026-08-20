"""
One definition of "the network failed, not us".

Every caller of an external service used to hand-roll this test, and every one
of them wrote a slightly different tuple — `(ConnectError, ConnectTimeout)` in
espn_monitor and h2h, `(ConnectError, ConnectTimeout, ReadTimeout)` in the
scheduler, and nothing at all in rankings. So a ReadTimeout, which is by far the
most common way a slow site fails, was silenced in one place and logged as an
application error in the others. Once system_logs errors started emailing, those
became false-positive pages for a site being briefly slow.

Import these two helpers instead of matching exception types inline.
"""

import httpx

# Sofascore refuses any client whose TLS handshake does not look like a browser,
# so services/sofascore.py uses curl_cffi rather than httpx. Its errors are a
# separate class hierarchy that httpx.TransportError does not cover, and without
# this a Sofascore timeout would be logged as an application fault. Imported
# defensively so this module keeps working if the package is ever dropped.
try:                                            # pragma: no cover - import guard
    from curl_cffi import CurlError as _CurlError
    _CURL_ERRORS: tuple = (_CurlError,)
except Exception:                               # pragma: no cover
    _CURL_ERRORS = ()

# Every way httpx reports "the request did not complete" — connect failures,
# all four timeout flavours, read/write errors, protocol resets, proxy errors.
# Matching the base class rather than listing leaves means a new httpx subclass
# is covered on arrival instead of quietly becoming an application error.
_TRANSPORT_BUT_OUR_FAULT = (
    httpx.LocalProtocolError,   # we built a malformed request
    httpx.UnsupportedProtocol,  # we passed a bad URL
)

# Server-side "come back later", plus the bot-blocking that Tennis Explorer
# serves as 403 when requests arrive too fast. A 4xx that isn't one of these
# (404, 401, 400) means we asked for the wrong thing and does deserve a log.
_TRANSIENT_STATUS = frozenset({403, 408, 429, 500, 502, 503, 504})


def is_transient_http_error(exc: BaseException) -> bool:
    """
    True when the failure is the network or the far end, not this code.

    Callers log these at debug and move on: the job that raised it runs again
    on its own schedule, and there is nothing a human could do with "a request
    timed out once". Anything that would still be broken on the next run must
    NOT be routed through here — see the freshness checks in
    _check_rankings_health for how a genuinely stuck refresh gets escalated.
    """
    if isinstance(exc, _TRANSPORT_BUT_OUR_FAULT):
        return False
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_STATUS
    if _CURL_ERRORS and isinstance(exc, _CURL_ERRORS):
        return True
    return False


def describe_exception(exc: BaseException) -> str:
    """
    Never return an empty string.

    httpx timeouts stringify to '', which produced the log line
    "ELO refresh failed for M: " — an alert carrying no information about what
    went wrong. Fall back to the class name, which is the whole story for a
    ReadTimeout.
    """
    return str(exc) or type(exc).__name__
