"""Request and response models for search."""

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.retrieval.service import SearchMode

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
    # dense: vectors; keyword: Postgres full-text search; hybrid: both, fused with RRF.
    mode: SearchMode = "dense"
    # Re-score the top candidates with the cross-encoder (task 008); slower, often better.
    rerank: bool = False
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
        description=(
            "Higher is better. dense: cosine similarity; keyword: ts_rank_cd; "
            "hybrid: reciprocal rank fusion score; with rerank: the cross-encoder score."
        )
    )
    dense_rank: int | None = Field(
        default=None, description="Rank in the dense candidate list, if the chunk was in it."
    )
    keyword_rank: int | None = Field(
        default=None, description="Rank in the keyword candidate list, if the chunk was in it."
    )
    rerank_score: float | None = Field(
        default=None, description="Cross-encoder score (raw model output); null unless reranked."
    )
    first_stage_rank: int | None = Field(
        default=None, description="Position before reranking; null unless reranked."
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
    reranker_model: str | None
    latency_ms: dict[str, float]


class SearchResponse(BaseModel):
    results: list[SearchResult]
    diagnostics: SearchDiagnostics
