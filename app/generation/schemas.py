"""The model's reply contract and the /v1/answers request and response models."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.retrieval.schemas import MAX_QUERY_CHARS, DocumentRef, SearchFilters
from app.retrieval.service import ScoreKind, SearchMode

AnswerStatus = Literal["answered", "insufficient_evidence"]


class ModelAnswer(BaseModel):
    """What the LLM must return. Also the source of the strict JSON schema sent to Groq,
    so the schema the model is constrained by and the one we validate are the same."""

    # extra="forbid" also emits additionalProperties: false, which strict mode requires.
    model_config = ConfigDict(extra="forbid")

    status: AnswerStatus
    answer: str
    citations: list[int]


def strict_json_schema(model: type[BaseModel]) -> dict:
    """A model's JSON schema for strict structured output. The docstring is for readers of
    this code, not for the LLM, so it is left out."""
    schema = model.model_json_schema()
    schema.pop("description", None)
    return schema


def model_answer_schema() -> dict:
    return strict_json_schema(ModelAnswer)


class AnswerRetrieval(BaseModel):
    """Retrieval overrides. Defaults are Experiment C's choice: dense, rerank top 20."""

    model_config = ConfigDict(extra="forbid")

    mode: SearchMode = "dense"
    rerank: bool = True
    filters: SearchFilters = Field(default_factory=SearchFilters)


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    retrieval: AnswerRetrieval = Field(default_factory=AnswerRetrieval)

    @field_validator("question")
    @classmethod
    def question_must_have_text(cls, question: str) -> str:
        if not question.strip():
            raise ValueError("must contain non-whitespace text")
        return question


class Citation(BaseModel):
    chunk_id: uuid.UUID
    document: DocumentRef
    heading_path: str
    char_start: int
    char_end: int
    snippet: str = Field(description="The start of the cited chunk, for display.")


class AnswerUsage(BaseModel):
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    llm_calls: int
    # Estimated USD from LLM_PRICES; null when the model has no configured price.
    cost_usd: float | None = None


class RetrievalSummary(BaseModel):
    mode: SearchMode
    rerank: bool
    context_chunk_ids: list[uuid.UUID]
    # The best retrieved chunk's score (null when nothing was retrieved); with rerank, the
    # cross-encoder score the optional abstention gate compares against.
    top_score: float | None
    score_kind: ScoreKind


class AnswerResponse(BaseModel):
    status: AnswerStatus
    answer: str
    citations: list[Citation]
    retrieval: RetrievalSummary
    usage: AnswerUsage
    latency_ms: dict[str, float]
