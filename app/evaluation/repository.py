"""Evaluation queries: the tenant's ingested documents, stored runs and their results."""

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from app.documents.models import Document, DocumentChunk, DocumentStatus
from app.evaluation.models import DatasetSplit, EvaluationResult, EvaluationRun
from app.jobs.models import Job


@dataclass(frozen=True)
class StoredDocument:
    slug: str
    version: str
    content_hash: str
    status: DocumentStatus
    # Chunks of the run's chunker and embedding model only; other strategies don't count.
    chunk_count: int


def list_stored_documents(
    session: Session, tenant_id: uuid.UUID, *, chunker: str, embedding_model: str
) -> list[StoredDocument]:
    chunk_join = and_(
        DocumentChunk.document_id == Document.id,
        DocumentChunk.chunker == chunker,
        DocumentChunk.embedding_model == embedding_model,
    )
    query = (
        select(
            Document.slug,
            Document.version,
            Document.content_hash,
            Document.status,
            func.count(DocumentChunk.id),
        )
        .outerjoin(DocumentChunk, chunk_join)
        .where(Document.tenant_id == tenant_id)
        .group_by(Document.id)
    )
    return [StoredDocument(*row) for row in session.execute(query)]


def postgres_version(session: Session) -> str:
    return session.scalar(text("SHOW server_version"))


# --- Runs and results (task 006b) -------------------------------------------------------


def add_run(session: Session, run: EvaluationRun) -> EvaluationRun:
    session.add(run)
    session.flush()
    return run


def get_run_in_tenant(
    session: Session, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> tuple[EvaluationRun, Job] | None:
    row = session.execute(
        select(EvaluationRun, Job)
        .join(Job, Job.id == EvaluationRun.job_id)
        .where(EvaluationRun.id == run_id, EvaluationRun.tenant_id == tenant_id)
    ).first()
    return None if row is None else (row[0], row[1])


def get_run_for_job(
    session: Session, tenant_id: uuid.UUID, job_id: uuid.UUID
) -> EvaluationRun | None:
    return session.scalar(
        select(EvaluationRun).where(
            EvaluationRun.job_id == job_id, EvaluationRun.tenant_id == tenant_id
        )
    )


def list_runs(
    session: Session,
    tenant_id: uuid.UUID,
    dataset: str | None,
    split: DatasetSplit | None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[EvaluationRun, Job]], int]:
    filters = [EvaluationRun.tenant_id == tenant_id]
    if dataset is not None:
        filters.append(EvaluationRun.dataset_name == dataset)
    if split is not None:
        filters.append(EvaluationRun.split == split)
    total = session.scalar(select(func.count(EvaluationRun.id)).where(*filters))
    rows = session.execute(
        select(EvaluationRun, Job)
        .join(Job, Job.id == EvaluationRun.job_id)
        .where(*filters)
        # Id breaks ties so pages never overlap when runs share a timestamp.
        .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [(run, job) for run, job in rows], total or 0


def add_results(session: Session, results: list[EvaluationResult]) -> None:
    session.add_all(results)
    session.flush()


def list_results(
    session: Session, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> list[EvaluationResult]:
    # Results have no tenant column; the join through their run scopes them.
    return list(
        session.scalars(
            select(EvaluationResult)
            .join(EvaluationRun, EvaluationRun.id == EvaluationResult.run_id)
            .where(EvaluationResult.run_id == run_id, EvaluationRun.tenant_id == tenant_id)
            .order_by(EvaluationResult.position)
        )
    )
