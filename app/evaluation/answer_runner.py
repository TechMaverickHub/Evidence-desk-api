"""Run every question of a split through the answer pipeline and record what happened.

Calls `generation.service.answer_question`, the code `/v1/answers` serves. Runs are paced
(provider rate limits) and resumable: each finished question is appended to a partial
file, and a rerun skips it, so an interrupted run never pays twice for the same answer.
"""

import json
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import LLMInvalidOutputError, LLMUnavailableError
from app.evaluation import provenance, repository
from app.evaluation.answer_records import (
    AnswerRecord,
    AnswerRunConfig,
    AnswerRunHeader,
    AnswerRunReport,
    GeneratorSettings,
    SpanRef,
)
from app.evaluation.dataset import BuiltQuestion, Dataset
from app.evaluation.records import DatasetRef
from app.evaluation.relevance import Span, match_evidence
from app.evaluation.runner import RunError, evidence_items, verify_corpus
from app.generation.llm_client import LLMClient
from app.generation.prompts import AnswerPrompts
from app.generation.schemas import AnswerRequest, AnswerResponse, AnswerRetrieval
from app.generation.service import ANSWER_RERANK_DEPTH, answer_question
from app.ingestion.embedding import Embedder
from app.retrieval.reranking import Reranker
from app.retrieval.service import configured_chunker


@dataclass(frozen=True)
class AnswerDeps:
    embedder: Embedder
    reranker_provider: Callable[[], Reranker]
    llm: LLMClient
    prompts: AnswerPrompts


class Pacer:
    """Keeps at least `interval` seconds between calls (provider rate limits)."""

    def __init__(
        self,
        interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def __call__(self) -> None:
        if self._last is not None:
            wait = self._interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()


def load_answer_config(path: Path) -> AnswerRunConfig:
    try:
        return AnswerRunConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise RunError(f"Invalid answer config {path}: {exc}") from exc


def execute_answer_run(
    session: Session,
    tenant_id: uuid.UUID,
    config: AnswerRunConfig,
    dataset: Dataset,
    split: str,
    corpus_texts: dict[tuple[str, str], str],
    deps: AnswerDeps,
    partial_path: Path,
    pace: Callable[[], None],
) -> AnswerRunReport:
    document_count = verify_corpus(
        session,
        tenant_id,
        corpus_texts,
        chunker=configured_chunker(),
        embedding_model=deps.embedder.model_name,
    )
    questions = [question for question in dataset.questions if question.split == split]
    if not questions:
        raise RunError("The split has no questions")
    run_key = {"config": config.model_dump(), "dataset": dataset.sha256, "split": split}
    records = run_answers(session, tenant_id, questions, config, deps, partial_path, run_key, pace)
    settings = get_settings()
    header = AnswerRunHeader(
        run_name=f"answers-{config.name}-{split}",
        created_at=datetime.now(UTC),
        dataset=DatasetRef(name=dataset.header.name, sha256=dataset.sha256, split=split),
        config=config,
        generator=GeneratorSettings(
            model=deps.llm.model_name,
            context_chunks=settings.answer_context_chunks,
            rerank_depth=ANSWER_RERANK_DEPTH,
            min_rerank_score=settings.answer_min_rerank_score,
        ),
        git=provenance.git_state(),
        environment=provenance.environment(repository.postgres_version(session)),
        corpus_documents=document_count,
    )
    return AnswerRunReport(header=header, records=records)


def run_answers(
    session: Session,
    tenant_id: uuid.UUID,
    questions: Sequence[BuiltQuestion],
    config: AnswerRunConfig,
    deps: AnswerDeps,
    partial_path: Path,
    run_key: dict,
    pace: Callable[[], None],
) -> list[AnswerRecord]:
    done = read_partial(partial_path, run_key)
    for question in questions:
        if question.id in done:
            continue
        pace()
        record = answer_one(session, tenant_id, question, config, deps)
        _append_partial(partial_path, record)
        done[question.id] = record
    return [done[question.id] for question in questions]


def answer_one(
    session: Session,
    tenant_id: uuid.UUID,
    question: BuiltQuestion,
    config: AnswerRunConfig,
    deps: AnswerDeps,
) -> AnswerRecord:
    request = AnswerRequest(
        question=question.question,
        retrieval=AnswerRetrieval(mode=config.mode, rerank=config.rerank),
    )
    try:
        response = answer_question(
            session,
            tenant_id,
            request,
            deps.embedder,
            deps.reranker_provider,
            deps.llm,
            deps.prompts,
        )
    except (LLMUnavailableError, LLMInvalidOutputError) as exc:
        # Recorded, not retried here: a rerun of the same run picks these up again.
        return _error_record(question, exc.error_code)
    return _answered_record(session, tenant_id, question, response)


def _answered_record(
    session: Session, tenant_id: uuid.UUID, question: BuiltQuestion, response: AnswerResponse
) -> AnswerRecord:
    evidence = evidence_items(question)
    context_chunks = repository.chunks_by_id(
        session, tenant_id, response.retrieval.context_chunk_ids
    )
    context = [context_chunks[chunk_id] for chunk_id in response.retrieval.context_chunk_ids]
    cited = [
        (c.chunk_id, c.document.slug, c.document.version, c.char_start, c.char_end)
        for c in response.citations
    ]
    return AnswerRecord(
        id=question.id,
        query_type=question.query_type,
        question=question.question,
        answerable=question.answerable,
        evidence_items=len(evidence),
        outcome=response.status,
        answer=response.answer,
        citations=_span_refs(cited, evidence),
        context=_span_refs(
            [(c.chunk_id, c.slug, c.version, c.char_start, c.char_end) for c in context], evidence
        ),
        top_score=response.retrieval.top_score,
        llm_calls=response.usage.llm_calls,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        latency_ms=response.latency_ms,
    )


def _span_refs(chunks: list[tuple], evidence: list) -> list[SpanRef]:
    """Each chunk with the evidence items it overlaps (same rule as retrieval metrics)."""
    matches = match_evidence([Span(slug, ver, s, e) for _, slug, ver, s, e in chunks], evidence)
    return [
        SpanRef(
            chunk_id=str(chunk_id),
            slug=slug,
            version=version,
            char_start=start,
            char_end=end,
            matched_items=sorted(matched),
        )
        for (chunk_id, slug, version, start, end), matched in zip(chunks, matches, strict=True)
    ]


def _error_record(question: BuiltQuestion, error_code: str) -> AnswerRecord:
    return AnswerRecord(
        id=question.id,
        query_type=question.query_type,
        question=question.question,
        answerable=question.answerable,
        evidence_items=len(question.evidence),
        outcome="error",
        error_code=error_code,
        answer="",
        citations=[],
        context=[],
        top_score=None,
        llm_calls=0,
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms={},
    )


# --- Partial file (resume) -------------------------------------------------------------------


def read_partial(path: Path, run_key: dict) -> dict[str, AnswerRecord]:
    """Finished records of an interrupted run with the same key. Errors are dropped, so a
    rerun retries them. A file from a different config, dataset or split is refused."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps({"run_key": run_key}) + "\n").encode())
        return {}
    first, *lines = path.read_bytes().decode("utf-8").splitlines()
    if json.loads(first).get("run_key") != run_key:
        raise RunError(f"{path} belongs to a different run; move it away to start over")
    records = [AnswerRecord.model_validate_json(line) for line in lines if line.strip()]
    return {record.id: record for record in records if record.outcome != "error"}


def _append_partial(path: Path, record: AnswerRecord) -> None:
    with path.open("ab") as handle:
        handle.write((record.model_dump_json() + "\n").encode())
