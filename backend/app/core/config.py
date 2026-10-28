from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "web-messenger"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://messenger:messenger@localhost:5432/messenger"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    # Browsers only send Secure cookies over HTTPS (localhost is exempt); enable in production.
    refresh_cookie_secure: bool = False

    # Anti-spam: at most send_rate_limit messages per user per window.
    send_rate_limit: int = 20
    send_rate_window_seconds: int = 10

    # Attachments are stored on the server's disk (a Docker volume in production).
    upload_dir: str = "uploads"
    max_upload_bytes: int = 10 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
