"""Application settings, read once from environment variables and `.env`."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # `extra="ignore"` lets `.env` also hold values meant for other tools
    # (e.g. POSTGRES_HOST_PORT for docker compose) without failing validation.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"
    database_url: str
    test_database_url: str | None = None

    # No default: the app must refuse to start without a real signing key.
    # 32+ characters keeps HS256 keys out of brute-force range.
    jwt_secret_key: str = Field(min_length=32)
    access_token_expire_minutes: int = Field(default=60, gt=0)

    # Changing the model to one with a different output size needs a migration,
    # because chunks.embedding is vector(384).
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    embedding_batch_size: int = Field(default=32, gt=0)
    worker_poll_seconds: float = Field(default=1.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
