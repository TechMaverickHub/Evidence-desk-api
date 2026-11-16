"""The answer-run config and record (`eval/reports/answers-<config>-<split>.json`).

Each record holds raw facts (what was answered, what was cited, which evidence items each
citation and the context matched); metrics are computed from them, never stored twice.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.records import DatasetRef, GitState
from app.retrieval.service import SearchMode

ANSWER_RUN_FORMAT = "evidencedesk-answers/1"

Outcome = Literal["answered", "insufficient_evidence", "error"]
Criterion = Literal["correctness", "faithfulness"]


class AnswerRunConfig(BaseModel):
    """One answering configuration, read from `eval/configs/answers-<name>.yaml`."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    mode: SearchMode = "dense"
    rerank: bool = True


class SpanRef(BaseModel):
    """A chunk sent or cited, with the labelled evidence items it overlaps."""

    chunk_id: str
    slug: str
    version: str
    char_start: int
    char_end: int
    matched_items: list[int]


class Judgment(BaseModel):
    # A criterion's verdict, or "unjudged" when the judge's reply could not be accepted.
    verdict: str
    reason: str


class AnswerRecord(BaseModel):
    id: str
    query_type: str
    question: str
    answerable: bool
    evidence_items: int
    outcome: Outcome
    error_code: str | None = None
    answer: str
    citations: list[SpanRef]
    context: list[SpanRef]
    # Best retrieved chunk's score (cross-encoder when reranked); None if nothing retrieved.
    top_score: float | None
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    latency_ms: dict[str, float]
    judgments: dict[Criterion, Judgment] = Field(default_factory=dict)


class GeneratorSettings(BaseModel):
    model: str | None
    context_chunks: int
    rerank_depth: int
    # The gate in force during the run (None = off); calibration sweeps it offline.
    min_rerank_score: float | None
    # Chunks read for the context (task 010); None in records written before it.
    chunker: str | None = None
    # USD per million [input, output] tokens in force for the run (task 012); None = unpriced.
    prices: tuple[float, float] | None = None


class JudgeAgreement(BaseModel):
    checked: int
    agreed: int


class AnswerRunHeader(BaseModel):
    run_name: str
    created_at: datetime
    dataset: DatasetRef
    config: AnswerRunConfig
    generator: GeneratorSettings
    judge_model: str | None = None
    judge_agreement: JudgeAgreement | None = None
    git: GitState
    environment: dict[str, str]
    corpus_documents: int


class AnswerRunReport(BaseModel):
    format: Literal["evidencedesk-answers/1"] = ANSWER_RUN_FORMAT
    header: AnswerRunHeader
    records: list[AnswerRecord]
