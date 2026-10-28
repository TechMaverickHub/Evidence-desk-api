import uuid
from collections.abc import Callable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.core.db import get_sessionmaker
from app.documents import service as documents_service
from app.documents.models import DocumentChunk, DocumentStatus
from app.ingestion.chunking import TokenWindowChunker
from app.jobs import repository as jobs_repository
from app.jobs.models import Job, JobStatus
from app.worker import build_handlers, process_next_job
from tests.conftest import ingest_request
from tests.fakes import FakeEmbedder, WhitespaceTokenizer

CHUNKER = TokenWindowChunker(WhitespaceTokenizer(), max_tokens=50, overlap_tokens=10)


def _chunk_count(session: Session, document_id: uuid.UUID) -> int:
    query = select(func.count()).where(DocumentChunk.document_id == document_id)
    return session.scalar(query) or 0


def test_successful_job_ingests_the_document(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    result = documents_service.ingest_document(db_session, tenant.id, ingest_request())

    processed = process_next_job(db_session, build_handlers(CHUNKER, FakeEmbedder()))

    assert processed is True
    job = jobs_repository.get_job_in_tenant(db_session, tenant.id, result.job_id)
    assert job is not None
    assert (job.status, job.attempts, job.error) == (JobStatus.SUCCEEDED, 1, None)
    document = documents_service.get_document(db_session, tenant.id, result.document_id)
    assert document.status == DocumentStatus.INGESTED
    assert _chunk_count(db_session, document.id) > 0


def test_failure_mid_document_leaves_no_chunks_and_records_the_error(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    result = documents_service.ingest_document(db_session, tenant.id, ingest_request())

    process_next_job(db_session, build_handlers(CHUNKER, FakeEmbedder(fail_on="Depends")))

    job = jobs_repository.get_job_in_tenant(db_session, tenant.id, result.job_id)
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.error == "fake embedder failure"
    document = documents_service.get_document(db_session, tenant.id, result.document_id)
    assert document.status == DocumentStatus.FAILED
    assert _chunk_count(db_session, document.id) == 0


def test_failed_document_can_be_resubmitted_and_succeed(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    first = documents_service.ingest_document(db_session, tenant.id, ingest_request())
    process_next_job(db_session, build_handlers(CHUNKER, FakeEmbedder(fail_on="Depends")))

    retry = documents_service.ingest_document(db_session, tenant.id, ingest_request())
    process_next_job(db_session, build_handlers(CHUNKER, FakeEmbedder()))

    assert retry.is_new_job is True
    assert retry.job_id != first.job_id
    document = documents_service.get_document(db_session, tenant.id, first.document_id)
    assert document.status == DocumentStatus.INGESTED


def test_unknown_job_kind_is_marked_failed(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    job = jobs_repository.add_job(db_session, make_tenant().id, "mystery", {})

    process_next_job(db_session, build_handlers(CHUNKER, FakeEmbedder()))

    db_session.refresh(job)
    assert job.status == JobStatus.FAILED
    assert "No handler" in (job.error or "")


def test_empty_queue_reports_nothing_processed(db_session: Session) -> None:
    assert process_next_job(db_session, build_handlers(CHUNKER, FakeEmbedder())) is False


def test_concurrent_workers_never_claim_the_same_job() -> None:
    # Needs committed rows and separate connections, so it cannot use the rolled-back
    # db_session; it cleans up after itself instead.
    session_factory = get_sessionmaker()
    with session_factory() as setup:
        tenant = Tenant(name=f"concurrency-{uuid.uuid4().hex[:8]}")
        setup.add(tenant)
        setup.flush()
        job_ids = {jobs_repository.add_job(setup, tenant.id, "ingest", {}).id for _ in range(2)}
        setup.commit()
        tenant_id = tenant.id

    worker_a, worker_b, worker_c = session_factory(), session_factory(), session_factory()
    try:
        claimed_by_a = jobs_repository.claim_next_job(worker_a)  # holds its row lock
        claimed_by_b = jobs_repository.claim_next_job(worker_b)
        claimed_by_c = jobs_repository.claim_next_job(worker_c)

        assert claimed_by_a is not None and claimed_by_b is not None
        assert {claimed_by_a.id, claimed_by_b.id} == job_ids
        assert claimed_by_c is None
    finally:
        for session in (worker_a, worker_b, worker_c):
            session.rollback()
            session.close()
        with session_factory() as cleanup:
            cleanup.execute(delete(Job).where(Job.tenant_id == tenant_id))
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()
