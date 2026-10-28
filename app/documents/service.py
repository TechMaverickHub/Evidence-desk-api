"""Document rules: idempotent ingestion requests, reads scoped to the caller's tenant."""

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.documents import repository
from app.documents.models import Document, DocumentStatus
from app.documents.schemas import IngestDocumentRequest
from app.jobs import repository as jobs_repository
from app.jobs.models import JobKind


@dataclass(frozen=True)
class IngestResult:
    document_id: uuid.UUID
    job_id: uuid.UUID
    status: DocumentStatus
    # False when the request matched an existing document and nothing new was queued.
    is_new_job: bool


def ingest_document(
    session: Session, tenant_id: uuid.UUID, request: IngestDocumentRequest
) -> IngestResult:
    """Store a document and queue it for processing, unless it is already known.

    - New (slug, version): create it and queue an ingest job.
    - Same slug, version and content: return the existing ids (idempotent retry).
    - Same slug and version, different content: 409, because versions are immutable.
    - Same content but the last attempt failed: queue a new job (manual retry).
    """
    content_hash = hashlib.sha256(request.content.encode()).hexdigest()
    existing = repository.get_document_by_slug(session, tenant_id, request.slug, request.version)
    if existing is not None:
        return _resubmit(session, existing, content_hash)
    try:
        return _create(session, tenant_id, request, content_hash)
    except IntegrityError:
        # A concurrent request created the same (slug, version) first; treat it as a resubmit.
        session.rollback()
        existing = repository.get_document_by_slug(
            session, tenant_id, request.slug, request.version
        )
        if existing is None:
            raise
        return _resubmit(session, existing, content_hash)


def get_document(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    document = repository.get_document_in_tenant(session, tenant_id, document_id)
    if document is None:
        raise NotFoundError("Document not found.")
    return document


def list_documents(
    session: Session,
    tenant_id: uuid.UUID,
    source: str | None,
    version: str | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Document], int]:
    return repository.list_documents(session, tenant_id, source, version, limit, offset)


def count_chunks(session: Session, document: Document) -> int:
    return repository.count_chunks(session, document.tenant_id, document.id)


def _create(
    session: Session, tenant_id: uuid.UUID, request: IngestDocumentRequest, content_hash: str
) -> IngestResult:
    fields = request.model_dump(exclude={"metadata"}) | {"doc_metadata": request.metadata}
    document = repository.add_document(session, tenant_id, fields, content_hash)
    job_id = _queue_ingest_job(session, document)
    session.commit()
    return IngestResult(document.id, job_id, document.status, is_new_job=True)


def _resubmit(session: Session, document: Document, content_hash: str) -> IngestResult:
    if document.content_hash != content_hash:
        raise ConflictError(
            "This slug and version already exist with different content. "
            "Ingest the new content as a new version."
        )
    if document.status == DocumentStatus.FAILED:
        document.status = DocumentStatus.PENDING
        job_id = _queue_ingest_job(session, document)
        session.commit()
        return IngestResult(document.id, job_id, document.status, is_new_job=True)

    latest_job = jobs_repository.get_latest_job_for_document(
        session, document.tenant_id, document.id
    )
    if latest_job is None:
        # Every document is created together with its job, so this means corrupted state.
        raise RuntimeError(f"Document {document.id} has no ingest job")
    return IngestResult(document.id, latest_job.id, document.status, is_new_job=False)


def _queue_ingest_job(session: Session, document: Document) -> uuid.UUID:
    job = jobs_repository.add_job(
        session, document.tenant_id, JobKind.INGEST, {"document_id": str(document.id)}
    )
    return job.id
