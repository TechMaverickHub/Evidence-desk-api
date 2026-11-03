"""Application settings, read once from environment variables and `.env`."""

from functools import lru_cache
from pathlib import Path

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
    # BGE's recommended prefix for short queries against passages. The model card says to keep
    # whichever setting scores better on your task, so it is configurable ("" disables it).
    embedding_query_instruction: str = "Represent this sentence for searching relevant passages: "
    # Load the model when the API starts, so the first search is not slow. Tests turn it off.
    preload_embedding_model: bool = True

    # The worker writes chunks with these sizes and search reads chunks with the same name,
    # so both must come from here.
    chunk_max_tokens: int = Field(default=300, gt=0)
    chunk_overlap_tokens: int = Field(default=50, ge=0)
    worker_poll_seconds: float = Field(default=1.0, gt=0)

    # Evaluation runs started over the API read datasets by name from this directory and
    # verify the tenant's documents against this corpus manifest (task 006b).
    eval_datasets_dir: Path = Path("eval/datasets")
    eval_corpus_manifest: Path = Path("corpus/manifest.yaml")


@lru_cache
def get_settings() -> Settings:
    return Settings()
