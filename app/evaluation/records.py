"""The run configuration and the JSON record of an evaluation run (`eval/reports/<run>.json`).

The JSON is the record; Markdown reports are rendered from it, and comparisons read it back.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evaluation.metrics import MetricSummary, QueryScores
from app.retrieval.fusion import DEFAULT_RRF_K
from app.retrieval.service import (
    DEFAULT_FUSION_DEPTH,
    DEFAULT_RERANK_DEPTH,
    ScoreKind,
    score_kind,
)

RUN_FORMAT = "evidencedesk-run/1"


class RunConfig(BaseModel):
    """One retrieval configuration, read from `eval/configs/<name>.yaml`."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    retriever: Literal["dense", "keyword", "hybrid"] = "dense"
    # Chunks retrieved per question; metrics are computed at each cutoff up to this depth.
    depth: int = Field(default=10, ge=1, le=50)
    # Hybrid only: candidates per retriever before fusion, and the RRF constant.
    fusion_depth: int = Field(default=DEFAULT_FUSION_DEPTH, ge=1, le=200)
    rrf_k: int = Field(default=DEFAULT_RRF_K, ge=1)
    # Re-score this many first-stage candidates with the cross-encoder (task 008).
    rerank: bool = False
    rerank_depth: int = Field(default=DEFAULT_RERANK_DEPTH, ge=1, le=200)
    cutoffs: list[int] = Field(default=[5, 10], min_length=1)
    # None uses the EMBEDDING_QUERY_INSTRUCTION setting; "" sends queries without one.
    query_instruction: str | None = None
    # A chunker variant to evaluate (task 010), e.g. "tokens-150-overlap-30"; None = settings.
    chunker: str | None = Field(default=None, pattern=r"^tokens-\d+-overlap-\d+(-ctx)?$")

    @model_validator(mode="after")
    def _cutoffs_within_depth(self) -> "RunConfig":
        if any(cutoff < 1 or cutoff > self.depth for cutoff in self.cutoffs):
            raise ValueError(f"every cutoff must be between 1 and depth ({self.depth})")
        self.cutoffs = sorted(set(self.cutoffs))
        return self


def run_score_kind(config: "RunConfig") -> ScoreKind:
    return score_kind(config.retriever, config.rerank)


class MetricRow(BaseModel):
    count: int
    precision: float
    recall: float
    mrr: float
    ndcg: float
    # Share of questions with any evidence in the top k (task 010); None in older records.
    hit: float | None = None

    @classmethod
    def from_summary(cls, summary: MetricSummary) -> "MetricRow":
        return cls(
            count=summary.count,
            precision=summary.precision,
            recall=summary.recall,
            mrr=summary.mrr,
            ndcg=summary.ndcg,
            hit=summary.hit,
        )


class QueryScoreRow(BaseModel):
    precision: float
    recall: float
    reciprocal_rank: float
    ndcg: float
    hit: float | None = None

    @classmethod
    def from_scores(cls, scores: QueryScores) -> "QueryScoreRow":
        return cls(
            precision=scores.precision,
            recall=scores.recall,
            reciprocal_rank=scores.reciprocal_rank,
            ndcg=scores.ndcg,
            hit=scores.hit,
        )


class HitRecord(BaseModel):
    """A retrieved chunk, identified by its document offsets (chunk text is not stored)."""

    rank: int
    slug: str
    version: str
    char_start: int
    char_end: int
    heading_path: str
    score: float
    # Indexes into the question's evidence list; empty means not relevant.
    matched_items: list[int]


class QuestionRecord(BaseModel):
    id: str
    query_type: str
    question: str
    answerable: bool
    word_overlap: float | None
    hits: list[HitRecord]
    # Cutoff -> scores; None for unanswerable questions, which retrieval metrics exclude.
    scores: dict[int, QueryScoreRow] | None
    latency_ms: dict[str, float]


class Percentiles(BaseModel):
    p50: float
    p95: float


class OverlapBands(BaseModel):
    """Metrics for questions below vs at-or-above the split's median word overlap."""

    cutoff: int
    threshold: float
    groups: dict[str, MetricRow]


class RunResults(BaseModel):
    # Cutoff -> "all" and one row per query type.
    metrics: dict[int, dict[str, MetricRow]]
    overlap_bands: OverlapBands | None
    latency_ms: dict[str, Percentiles]
    questions: list[QuestionRecord]


class DatasetRef(BaseModel):
    name: str
    sha256: str
    split: Literal["dev", "test"]


class EffectiveSettings(BaseModel):
    """What the run actually used, including values that come from settings, not the config."""

    chunker: str
    embedding_model: str
    query_instruction: str
    min_overlap_fraction: float
    # What hit scores mean in this run; records written before task 008 were all cosine.
    score_kind: ScoreKind = "cosine"
    reranker_model: str | None = None


class GitState(BaseModel):
    sha: str
    # True when tracked files had uncommitted changes; None when git was unavailable.
    dirty: bool | None


class RunHeader(BaseModel):
    run_name: str
    created_at: datetime
    dataset: DatasetRef
    config: RunConfig
    effective: EffectiveSettings
    git: GitState
    environment: dict[str, str]
    corpus_documents: int


class RunReport(BaseModel):
    format: Literal["evidencedesk-run/1"] = RUN_FORMAT
    header: RunHeader
    results: RunResults
