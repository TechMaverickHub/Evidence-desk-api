"""Request and response models for search."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_QUERY_CHARS = 1000
MAX_K = 50


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str | None = Field(default=None, max_length=100)
    version: str | None = Field(default=None, max_length=50)


class SearchRequest(BaseModel):
    # extra="forbid": tenant_id or unknown options are rejected, not silently ignored.
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    k: int = Field(default=10, ge=1, le=MAX_K)
    # Only dense retrieval exists so far; task 007 adds "keyword" and "hybrid".
    mode: Literal["dense"] = "dense"
    filters: SearchFilters = Field(default_factory=SearchFilters)

    @field_validator("query")
    @classmethod
    def query_must_have_text(cls, query: str) -> str:
        if not query.strip():
            raise ValueError("must contain non-whitespace text")
        return query


class DocumentRef(BaseModel):
    id: uuid.UUID
    source: str
    slug: str
    version: str
    title: str


class SearchResult(BaseModel):
    rank: int
    chunk_id: uuid.UUID
    score: float = Field(
        description="Cosine similarity between query and chunk (higher is closer)."
    )
    text: str
    char_start: int
    char_end: int
    heading_path: str
    document: DocumentRef


class SearchDiagnostics(BaseModel):
    mode: str
    k: int
    chunker: str
    embedding_model: str
    query_instruction: bool
    latency_ms: dict[str, float]


class SearchResponse(BaseModel):
    results: list[SearchResult]
    diagnostics: SearchDiagnostics
