"""Failure scenario 10 (task 011): a worker dies mid-job; the next worker recovers it."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.core.config import get_settings
from app.documents import service as documents_service
from app.documents.models import DocumentStatus
from app.ingestion.chunking import TokenWindowChunker
from app.jobs import repository as jobs_repository
from app.jobs.models import Job, JobStatus
from app.worker import build_handlers, process_next_job, recover_stale_jobs
from tests.conftest import ingest_request
from tests.fakes import FakeEmbedder, WhitespaceTokenizer

STALE_AFTER = timedelta(minutes=30)


@pytest.fixture
def handlers() -> dict:
    settings = get_settings()
    chunker = TokenWindowChunker(
        WhitespaceTokenizer(), settings.chunk_max_tokens, settings.chunk_overlap_tokens
    )
    return build_handlers(chunker, FakeEmbedder())


def _crashed_job(session: Session, tenant: Tenant) -> tuple[Job, object]:
    """Submit a document and claim its job, as a worker that then dies would."""
    result = documents_service.ingest_document(session, tenant.id, ingest_request())
    job = jobs_repository.claim_next_job(session)
    session.commit()
    assert job is not None and job.id == result.job_id
    return job, result.document_id


def test_an_orphaned_job_is_requeued_and_then_processed(
    db_session: Session, make_tenant: Callable[..., Tenant], handlers: dict
) -> None:
    tenant = make_tenant()
    job, document_id = _crashed_job(db_session, tenant)
    later = job.started_at + STALE_AFTER + timedelta(seconds=1)

    assert recover_stale_jobs(db_session, handlers, STALE_AFTER, 3, later) == (1, 0)
    assert job.status == JobStatus.QUEUED
    assert process_next_job(db_session, handlers)

    db_session.refresh(job)
    document = documents_service.get_document(db_session, tenant.id, document_id)
    assert job.status == JobStatus.SUCCEEDED
    assert job.attempts == 2
    assert document.status == DocumentStatus.INGESTED
    assert documents_service.count_chunks(db_session, document) > 0


def test_a_job_that_used_every_attempt_fails_with_its_document(
    db_session: Session, make_tenant: Callable[..., Tenant], handlers: dict
) -> None:
    tenant = make_tenant()
    job, document_id = _crashed_job(db_session, tenant)
    job.attempts = 3
    later = job.started_at + STALE_AFTER + timedelta(seconds=1)

    assert recover_stale_jobs(db_session, handlers, STALE_AFTER, 3, later) == (0, 1)

    db_session.refresh(job)
    assert job.status == JobStatus.FAILED
    assert job.error == "worker stopped while running (3 attempts)"
    document = documents_service.get_document(db_session, tenant.id, document_id)
    assert document.status == DocumentStatus.FAILED


def test_a_job_still_within_its_window_is_left_alone(
    db_session: Session, make_tenant: Callable[..., Tenant], handlers: dict
) -> None:
    job, _ = _crashed_job(db_session, make_tenant())

    assert recover_stale_jobs(db_session, handlers, STALE_AFTER, 3, datetime.now(UTC)) == (0, 0)
    assert job.status == JobStatus.RUNNING
