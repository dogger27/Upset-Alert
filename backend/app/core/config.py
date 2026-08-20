from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./tennis_fantasy.db"
    secret_key: str = "change-me-to-a-long-random-string"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 1 week
    wiki_api_url: str = "https://en.wikipedia.org/w/api.php"
    resend_api_key: str = ""
    environment: str = "development"
    # Web Push (VAPID). Empty keys disable push entirely rather than erroring,
    # so dev and any environment without them configured just skips the channel.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    # Contact URI the push service can use to reach us about a misbehaving
    # sender; required by the VAPID spec.
    vapid_subject: str = "mailto:pdwiens@gmail.com"

    # Master switch for anything that leaves this machine and reaches a USER —
    # email and Web Push. Default True so production is unchanged and no deploy
    # can silently go quiet.
    #
    # This exists because staging runs a COPY OF THE PRODUCTION DATABASE, which
    # carries every real address and every real push subscription. Staging also
    # has to run with environment="production", because that is the flag the
    # scheduler and the scrapers gate on — so the existing `environment !=
    # production` guard inside send_async cannot help there. Without a second,
    # independent switch, standing up staging would mean every competitor gets a
    # duplicate of every notification, from a box whose whole purpose is to run
    # unfinished code.
    #
    # Deliberately NOT derived from environment, hostname, port or database
    # path. A guard that infers what it is protecting against gets it wrong the
    # first time something is renamed; this one has to be set to false on
    # purpose, and says so in the log at boot.
    outbound_notifications: bool = True

    # Sofascore live-score polling. Off by default so merging the poller changes
    # nothing anywhere until an instance opts in — staging first, production only
    # once it has been watched through a real tournament day.
    sofascore_live_enabled: bool = False

    # Poll even though ESPN has not reported anything on court.
    #
    # For staging only, and it exists because of a specific asymmetry: staging
    # runs with the scrapers OFF, so that a second instance does not double the
    # load on Wikipedia and Tennis Explorer or risk the rate limits production
    # depends on. But espn_monitor is part of that same scheduler, which means
    # live_scores_json — the cheap signal the poll gate reads — never updates
    # there. Without this the staging poller would gate itself off on a copied,
    # frozen view of what is live.
    #
    # It costs real requests: the gate is what makes the loop free overnight and
    # between tournaments. Never set it in production.
    sofascore_live_force: bool = False

    # Sweep finished matches into the sofa_* SHADOW columns. Reads nothing back
    # and changes nothing a user can see — it exists so ESPN and Sofascore can be
    # diffed over a real tournament before Sofascore is allowed to own a result.
    # Separate from the live flag because the two answer different questions and
    # one may want turning off without the other.
    sofascore_results_enabled: bool = False

    # Treat Sofascore as the SOURCE OF RECORD rather than a second opinion.
    #
    # Applied at the READ layer, not by changing who writes: the sofa_* columns
    # keep being written beside ESPN's, and this decides which set the API
    # serves. That makes the cutover reversible by restarting with the flag off,
    # with no data to migrate back — as opposed to swapping espn_monitor's
    # writes, which would be a one-way door.
    #
    # Evidence before enabling (scripts/sofa_diff.py): 174 winners agreed, zero
    # mismatched; 172 of 174 scorelines identical; no retirement or walkover
    # marker lost. Staging runs with it on and no ESPN scraper at all, which is
    # the only honest test of "could Sofascore carry this alone".
    sofascore_authoritative: bool = False

    class Config:
        env_file = ".env"


settings = Settings()

# The signing key must never fall back to the placeholder in production. This
# repo is public, so that literal string is known to anyone who reads it — and
# because tokens carry only str(user.id), a known HS256 key lets anyone mint a
# valid session for any account, admin included. On 2026-08-18 production was
# found running exactly that: docker-compose interpolates
# ${SECRET_KEY:-change-me-...} and the host .env never set SECRET_KEY, so the
# fallback applied silently — no error, no log line, nothing to notice.
# Fail loudly at boot instead: a container that refuses to start is a page you
# act on, an unsigned-in-effect JWT is a breach you don't find.
if settings.environment == "production" and (
    not settings.secret_key
    or settings.secret_key == "change-me-to-a-long-random-string"
):
    raise RuntimeError(
        "SECRET_KEY is unset or still the public placeholder while "
        "ENVIRONMENT=production. Set a strong random value (e.g. "
        "`python -c 'import secrets; print(secrets.token_urlsafe(64))'`) in the "
        "host .env beside docker-compose.yml. Refusing to start: this key signs "
        "every session token."
    )
