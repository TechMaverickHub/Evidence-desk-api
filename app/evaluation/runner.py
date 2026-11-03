"""Score one retrieval configuration on one dataset split, through the real search service.

The runner calls `retrieval.service.search`, the code `/v1/search` serves, so an evaluation
measures exactly what users get. Labels are character offsets, so before any query runs the
tenant's documents are checked byte-for-byte against the corpus.
"""

import math
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

import yaml
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth.repository import get_tenant_by_name
from app.core.config import get_settings
from app.documents.models import DocumentStatus
from app.documents.service import compute_content_hash
from app.evaluation import provenance, repository
from app.evaluation.dataset import BuiltQuestion, Dataset
from app.evaluation.metrics import QueryScores, aggregate, score_query
from app.evaluation.records import (
    DatasetRef,
    EffectiveSettings,
    HitRecord,
    MetricRow,
    OverlapBands,
    Percentiles,
    QueryScoreRow,
    QuestionRecord,
    RunConfig,
    RunHeader,
    RunReport,
    RunResults,
    run_score_kind,
)
from app.evaluation.relevance import MIN_OVERLAP_FRACTION, EvidenceItem, Span, match_evidence
from app.ingestion.embedding import Embedder
from app.retrieval.repository import SearchHit
from app.retrieval.reranking import Reranker
from app.retrieval.service import SearchOptions, configured_chunker, search


class RunError(Exception):
    """A run that cannot start or produce valid numbers, reported without a traceback."""


def load_run_config(path: Path) -> RunConfig:
    try:
        return RunConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise RunError(f"Invalid run config {path}: {exc}") from exc


def effective_query_instruction(config: RunConfig) -> str:
    """The config's instruction, or the EMBEDDING_QUERY_INSTRUCTION setting when it has none."""
    if config.query_instruction is not None:
        return config.query_instruction
    return get_settings().embedding_query_instruction


def tenant_id_by_name(session: Session, tenant_name: str) -> uuid.UUID:
    """The CLI names tenants; the worker already has the id from the job."""
    tenant = get_tenant_by_name(session, tenant_name)
    if tenant is None:
        raise RunError(f"Unknown tenant '{tenant_name}'")
    return tenant.id


def execute_run(
    session: Session,
    tenant_id: uuid.UUID,
    embedder: Embedder,
    config: RunConfig,
    dataset: Dataset,
    split: str,
    corpus_texts: dict[tuple[str, str], str],
    query_instruction: str,
    reranker: Reranker | None = None,
) -> RunReport:
    """Verify the tenant's corpus, score every question of the split, and record provenance.

    `query_instruction` is the one the embedder was built with; it is recorded, not applied.
    """
    if config.rerank and reranker is None:
        raise RunError(f"Config '{config.name}' reranks, but no reranker was provided")
    chunker = configured_chunker()
    document_count = verify_corpus(
        session, tenant_id, corpus_texts, chunker=chunker, embedding_model=embedder.model_name
    )
    questions = [question for question in dataset.questions if question.split == split]
    results = run_evaluation(session, tenant_id, embedder, questions, config, reranker)
    header = RunHeader(
        run_name=f"{config.name}-{split}",
        created_at=datetime.now(UTC),
        dataset=DatasetRef(name=dataset.header.name, sha256=dataset.sha256, split=split),
        config=config,
        effective=EffectiveSettings(
            chunker=chunker,
            embedding_model=embedder.model_name,
            query_instruction=query_instruction,
            min_overlap_fraction=MIN_OVERLAP_FRACTION,
            score_kind=run_score_kind(config),
            reranker_model=reranker.model_name if config.rerank else None,
        ),
        git=provenance.git_state(),
        environment=provenance.environment(repository.postgres_version(session)),
        corpus_documents=document_count,
    )
    return RunReport(header=header, results=results)


# --- Corpus check -----------------------------------------------------------------------


def verify_corpus(
    session: Session,
    tenant_id: uuid.UUID,
    corpus_texts: dict[tuple[str, str], str],
    *,
    chunker: str,
    embedding_model: str,
) -> int:
    """Require the tenant to hold exactly the corpus: same documents, same bytes, all chunked.

    Every document is checked, not only the cited ones: a missing or extra distractor
    changes the ranking just as surely as a changed evidence page.
    """
    stored = {
        (document.slug, document.version): document
        for document in repository.list_stored_documents(
            session, tenant_id, chunker=chunker, embedding_model=embedding_model
        )
    }
    problems = [
        f"{slug}@{version}: in the tenant but not in the corpus manifest"
        for slug, version in sorted(stored.keys() - corpus_texts.keys())
    ]
    for (slug, version), content in sorted(corpus_texts.items()):
        problem = _document_problem(stored.get((slug, version)), content, chunker)
        if problem:
            problems.append(f"{slug}@{version}: {problem}")
    if problems:
        raise RunError("Tenant does not match the corpus:\n" + "\n".join(problems))
    return len(corpus_texts)


def _document_problem(
    document: repository.StoredDocument | None, content: str, chunker: str
) -> str | None:
    if document is None:
        return "not ingested"
    if document.content_hash != compute_content_hash(content):
        return "stored content differs from the corpus file"
    if document.status != DocumentStatus.INGESTED or document.chunk_count == 0:
        return f"no {chunker} chunks for this embedding model"
    return None


# --- Running ----------------------------------------------------------------------------


def run_evaluation(
    session: Session,
    tenant_id: uuid.UUID,
    embedder: Embedder,
    questions: Sequence[BuiltQuestion],
    config: RunConfig,
    reranker: Reranker | None = None,
) -> RunResults:
    if not questions:
        raise RunError("The split has no questions")
    # One unmeasured query first: the first call pays one-off costs that would skew p95.
    options = search_options(config)
    search(session, tenant_id, embedder, questions[0].question, options, reranker)

    records = []
    for question in questions:
        outcome = search(session, tenant_id, embedder, question.question, options, reranker)
        records.append(score_question(question, outcome.hits, config.cutoffs, outcome.latency_ms))
    return summarise(records, config.cutoffs)


def search_options(config: RunConfig) -> SearchOptions:
    return SearchOptions(
        k=config.depth,
        mode=config.retriever,
        fusion_depth=config.fusion_depth,
        rrf_k=config.rrf_k,
        rerank=config.rerank,
        rerank_depth=config.rerank_depth,
    )


def evidence_items(question: BuiltQuestion) -> list[EvidenceItem]:
    """The question's labelled evidence in the shape `match_evidence` expects."""
    return [
        EvidenceItem(
            grade=item.grade,
            spans=tuple(Span(s.slug, s.version, s.char_start, s.char_end) for s in item.spans),
        )
        for item in question.evidence
    ]


def score_question(
    question: BuiltQuestion,
    hits: Sequence[SearchHit],
    cutoffs: Sequence[int],
    latency_ms: dict[str, float],
) -> QuestionRecord:
    evidence = evidence_items(question)
    chunks = [Span(hit.slug, hit.version, hit.char_start, hit.char_end) for hit in hits]
    matches = match_evidence(chunks, evidence)
    grades = [item.grade for item in evidence]
    scores = None
    if question.answerable:
        scores = {
            k: QueryScoreRow.from_scores(
                score_query(question.id, question.query_type, matches, grades, k)
            )
            for k in cutoffs
        }
    return QuestionRecord(
        id=question.id,
        query_type=question.query_type,
        question=question.question,
        answerable=question.answerable,
        word_overlap=question.word_overlap,
        hits=[
            _hit_record(rank, hit, matched)
            for rank, (hit, matched) in enumerate(zip(hits, matches, strict=True), start=1)
        ],
        scores=scores,
        latency_ms=latency_ms,
    )


def _hit_record(rank: int, hit: SearchHit, matched: frozenset[int]) -> HitRecord:
    return HitRecord(
        rank=rank,
        slug=hit.slug,
        version=hit.version,
        char_start=hit.char_start,
        char_end=hit.char_end,
        heading_path=hit.heading_path,
        score=hit.score,
        matched_items=sorted(matched),
    )


# --- Aggregation ------------------------------------------------------------------------


def summarise(records: Sequence[QuestionRecord], cutoffs: Sequence[int]) -> RunResults:
    scored = [record for record in records if record.scores is not None]
    metrics = {
        k: {
            name: MetricRow.from_summary(summary)
            for name, summary in aggregate(_query_scores(record, k) for record in scored).items()
        }
        for k in cutoffs
    }
    return RunResults(
        metrics=metrics,
        overlap_bands=overlap_bands(scored, max(cutoffs)),
        latency_ms=latency_percentiles(records),
        questions=list(records),
    )


def overlap_bands(scored: Sequence[QuestionRecord], cutoff: int) -> OverlapBands | None:
    """Split at the median word overlap: does retrieval favour questions that reuse the
    passage's words? (A drafting-bias check; see eval/datasets/README.md.)"""
    with_overlap = [record for record in scored if record.word_overlap is not None]
    if not with_overlap:
        return None
    threshold = median(record.word_overlap for record in with_overlap)
    banded = [
        replace(
            _query_scores(record, cutoff),
            query_type="low" if record.word_overlap < threshold else "high",
        )
        for record in with_overlap
    ]
    groups = aggregate(banded)
    groups.pop("all")
    return OverlapBands(
        cutoff=cutoff,
        threshold=threshold,
        groups={name: MetricRow.from_summary(summary) for name, summary in groups.items()},
    )


def latency_percentiles(records: Sequence[QuestionRecord]) -> dict[str, Percentiles]:
    by_stage: dict[str, list[float]] = defaultdict(list)
    for record in records:
        for stage, milliseconds in record.latency_ms.items():
            by_stage[stage].append(milliseconds)
    return {
        stage: Percentiles(p50=percentile(values, 0.5), p95=percentile(values, 0.95))
        for stage, values in by_stage.items()
    }


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile: always an observed value, no interpolation."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _query_scores(record: QuestionRecord, k: int) -> QueryScores:
    row = record.scores[k]
    return QueryScores(
        query_id=record.id,
        query_type=record.query_type,
        precision=row.precision,
        recall=row.recall,
        reciprocal_rank=row.reciprocal_rank,
        ndcg=row.ndcg,
    )
