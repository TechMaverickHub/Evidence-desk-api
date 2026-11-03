"""Application settings, read once from environment variables and `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
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

    # Cross-encoder for optional second-stage ranking (task 008). Loaded on first use unless
    # preloaded, so APIs that never rerank don't pay for it.
    reranker_model_name: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    reranker_batch_size: int = Field(default=32, gt=0)
    preload_reranker: bool = False

    # The worker writes chunks with these sizes and search reads chunks with the same name,
    # so both must come from here.
    chunk_max_tokens: int = Field(default=300, gt=0)
    chunk_overlap_tokens: int = Field(default=50, ge=0)
    worker_poll_seconds: float = Field(default=1.0, gt=0)

    # Answer generation (task 009a). No default key: without one, /v1/answers returns 503
    # and everything else still works.
    groq_api_key: SecretStr | None = None
    # A Groq production model that supports strict json_schema output (constrained decoding).
    llm_model: str = "openai/gpt-oss-20b"
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    # The SDK retries timeouts, 429s and 5xx with backoff; 011 adds failure-scenario tests.
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    # gpt-oss spends completion tokens on reasoning too, so this must leave room for the JSON.
    llm_max_completion_tokens: int = Field(default=2048, gt=0)
    # Top chunks sent as context (each <= 300 tokens); the budget is Experiment D (010).
    answer_context_chunks: int = Field(default=5, ge=1, le=20)

    # Evaluation runs started over the API read datasets by name from this directory and
    # verify the tenant's documents against this corpus manifest (task 006b).
    eval_datasets_dir: Path = Path("eval/datasets")
    eval_corpus_manifest: Path = Path("corpus/manifest.yaml")

    @field_validator("groq_api_key", mode="before")
    @classmethod
    def blank_key_means_unset(cls, value: object) -> object:
        # "GROQ_API_KEY=" in .env (as in .env.example) must mean "not configured".
        return None if isinstance(value, str) and not value.strip() else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
