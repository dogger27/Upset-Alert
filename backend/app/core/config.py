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
