"""Evaluation runs over the API: queue a run, execute it as a job, read it back.

The scoring itself is `runner.execute_run`, shared with the CLI. This module adds the
rules around it: which datasets may be named, that the dataset is the one that was
queued, and how a run is stored and converted back to a `RunReport`.
"""

import re
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import CurrentUser
from app.core.errors import InvalidInputError, NotFoundError
from app.evaluation import repository
from app.evaluation.dataset import Dataset, DatasetError, load_dataset, read_corpus_texts
from app.evaluation.models import DatasetSplit, EvaluationResult, EvaluationRun
from app.evaluation.records import (
    DatasetRef,
    EffectiveSettings,
    GitState,
    QuestionRecord,
    RunConfig,
    RunHeader,
    RunReport,
    RunResults,
)
from app.evaluation.runner import RunError, effective_query_instruction, execute_run
from app.evaluation.schemas import (
    DATASET_NAME_PATTERN,
    CreateRunRequest,
    CreateRunResponse,
    RunDatasetInfo,
    RunDetail,
    RunListItem,
    RunListResponse,
    RunStatus,
    RunSummary,
)
from app.ingestion.embedding import Embedder
from app.jobs import repository as jobs_repository
from app.jobs.models import Job, JobKind
from app.retrieval.reranking import Reranker

QueryEmbedderFactory = Callable[[str], Embedder]


def create_run(session: Session, user: CurrentUser, request: CreateRunRequest) -> CreateRunResponse:
    dataset = _load_named_dataset(request.dataset)
    if not any(question.split == request.split for question in dataset.questions):
        raise InvalidInputError(field_errors={"split": ["the dataset has no questions here"]})
    run_id = uuid.uuid4()
    job = jobs_repository.add_job(
        session, user.tenant_id, JobKind.EVALUATE, {"run_id": str(run_id)}
    )
    repository.add_run(
        session,
        EvaluationRun(
            id=run_id,
            tenant_id=user.tenant_id,
            created_by=user.id,
            job_id=job.id,
            dataset_name=request.dataset,
            # Recorded now so the worker can refuse a dataset that changed while queued.
            dataset_sha256=dataset.sha256,
            split=request.split,
            config=request.config.model_dump(mode="json"),
        ),
    )
    session.commit()
    return CreateRunResponse(run_id=run_id, job_id=job.id)


def run_evaluation_job(
    session: Session,
    job: Job,
    query_embedder_for: QueryEmbedderFactory,
    load_reranker: Callable[[], Reranker] | None = None,
) -> None:
    """Job handler. Does not commit: the worker's success commit stores the results and
    the job's status together, so a run is never half-written."""
    run = repository.get_run_for_job(session, job.tenant_id, job.id)
    if run is None:
        raise RunError(f"No evaluation run for job {job.id}")
    dataset = _load_named_dataset(run.dataset_name)
    if dataset.sha256 != run.dataset_sha256:
        raise RunError(f"Dataset '{run.dataset_name}' changed after the run was queued")
    config = RunConfig.model_validate(run.config)
    instruction = effective_query_instruction(config)
    reranker = load_reranker() if config.rerank and load_reranker else None
    report = execute_run(
        session,
        job.tenant_id,
        query_embedder_for(instruction),
        config,
        dataset,
        run.split,
        read_corpus_texts(get_settings().eval_corpus_manifest),
        instruction,
        reranker,
    )
    store_report(session, run, report)


def list_runs(
    session: Session,
    tenant_id: uuid.UUID,
    dataset: str | None,
    split: DatasetSplit | None,
    limit: int,
    offset: int,
) -> RunListResponse:
    rows, total = repository.list_runs(session, tenant_id, dataset, split, limit, offset)
    items = [_list_item(run, job) for run, job in rows]
    return RunListResponse(items=items, total=total, limit=limit, offset=offset)


def get_run(
    session: Session, tenant_id: uuid.UUID, run_id: uuid.UUID, include_results: bool
) -> RunDetail:
    found = repository.get_run_in_tenant(session, tenant_id, run_id)
    if found is None:
        raise NotFoundError("Evaluation run not found.")
    run, job = found
    results = None
    if include_results and run.summary is not None:
        # Results are loaded only on request: a run's rows are about 100 KB.
        results = _question_records(repository.list_results(session, tenant_id, run.id))
    return _detail(run, job, results)


# --- Storage <-> record ----------------------------------------------------------------


def store_report(session: Session, run: EvaluationRun, report: RunReport) -> None:
    """Write a run record into the run row and its result rows (`stored_run_report` reverses it)."""
    header, results = report.header, report.results
    run.effective = header.effective.model_dump(mode="json")
    run.git_sha = header.git.sha
    run.git_dirty = header.git.dirty
    run.environment = header.environment
    run.corpus_documents = header.corpus_documents
    run.executed_at = header.created_at
    run.summary = RunSummary(
        metrics=results.metrics,
        overlap_bands=results.overlap_bands,
        latency_ms=results.latency_ms,
    ).model_dump(mode="json")
    repository.add_results(
        session,
        [
            _result_row(run.id, position, record)
            for position, record in enumerate(results.questions)
        ],
    )


def _result_row(run_id: uuid.UUID, position: int, record: QuestionRecord) -> EvaluationResult:
    data = record.model_dump(mode="json")
    return EvaluationResult(
        run_id=run_id,
        position=position,
        question_id=record.id,
        query_type=record.query_type,
        question=record.question,
        answerable=record.answerable,
        word_overlap=record.word_overlap,
        hits=data["hits"],
        scores=data["scores"],
        latency_ms=record.latency_ms,
    )


def stored_run_report(run: EvaluationRun, results: Sequence[EvaluationResult]) -> RunReport:
    """Rebuild the 006a run record from a succeeded run's rows."""
    summary = RunSummary.model_validate(run.summary)
    return RunReport(
        header=_stored_header(run),
        results=RunResults(**summary.model_dump(), questions=_question_records(results)),
    )


def _stored_header(run: EvaluationRun) -> RunHeader:
    config = RunConfig.model_validate(run.config)
    return RunHeader(
        run_name=f"{config.name}-{run.split}",
        created_at=run.executed_at,
        dataset=DatasetRef(name=run.dataset_name, sha256=run.dataset_sha256, split=run.split),
        config=config,
        effective=EffectiveSettings.model_validate(run.effective),
        git=GitState(sha=run.git_sha, dirty=run.git_dirty),
        environment=run.environment,
        corpus_documents=run.corpus_documents,
    )


def _question_records(results: Sequence[EvaluationResult]) -> list[QuestionRecord]:
    return [
        QuestionRecord(
            id=row.question_id,
            query_type=row.query_type,
            question=row.question,
            answerable=row.answerable,
            word_overlap=row.word_overlap,
            hits=row.hits,
            scores=row.scores,
            latency_ms=row.latency_ms,
        )
        for row in results
    ]


# --- Helpers ---------------------------------------------------------------------------


def _load_named_dataset(name: str) -> Dataset:
    # Re-checked here (not only in the request schema): the worker passes stored names too.
    if not re.fullmatch(DATASET_NAME_PATTERN, name):
        raise InvalidInputError(field_errors={"dataset": ["invalid dataset name"]})
    path: Path = get_settings().eval_datasets_dir / f"{name}.jsonl"
    if not path.is_file():
        raise InvalidInputError(field_errors={"dataset": ["unknown dataset"]})
    try:
        dataset = load_dataset(path)
    except DatasetError as exc:
        raise RunError(f"Dataset '{name}' cannot be read: {exc}") from exc
    if dataset.header.name != name:
        # Stored runs are identified by the file name; the header must agree with it.
        raise RunError(f"Dataset file '{name}' declares the name '{dataset.header.name}'")
    return dataset


def _run_status(job: Job) -> RunStatus:
    return RunStatus(
        status=job.status, error=job.error, started_at=job.started_at, finished_at=job.finished_at
    )


def _list_item(run: EvaluationRun, job: Job) -> RunListItem:
    overall = None
    if run.summary is not None:
        metrics = RunSummary.model_validate(run.summary).metrics
        overall = metrics[max(metrics)]["all"]
    return RunListItem(
        id=run.id,
        job_id=run.job_id,
        status=job.status,
        dataset_name=run.dataset_name,
        split=run.split,
        config_name=run.config["name"],
        created_at=run.created_at,
        finished_at=job.finished_at,
        overall=overall,
    )


def _detail(run: EvaluationRun, job: Job, results: list[QuestionRecord] | None) -> RunDetail:
    # Provenance and numbers exist only once the run has succeeded.
    header = _stored_header(run) if run.summary is not None else None
    summary = RunSummary.model_validate(run.summary) if run.summary is not None else None
    return RunDetail(
        id=run.id,
        job_id=run.job_id,
        created_by=run.created_by,
        created_at=run.created_at,
        run=_run_status(job),
        dataset=RunDatasetInfo(name=run.dataset_name, sha256=run.dataset_sha256, split=run.split),
        config=RunConfig.model_validate(run.config),
        executed_at=run.executed_at,
        effective=header.effective if header else None,
        git=header.git if header else None,
        environment=header.environment if header else None,
        corpus_documents=run.corpus_documents,
        summary=summary,
        results=results,
    )
