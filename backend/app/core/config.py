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
