"""Application settings, read once from environment variables and `.env`."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # `extra="ignore"` lets `.env` also hold values meant for other tools
    # (e.g. POSTGRES_HOST_PORT for docker compose) without failing validation.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"
    database_url: str
    test_database_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
