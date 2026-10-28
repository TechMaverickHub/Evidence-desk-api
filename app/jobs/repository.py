"""Database queries for the job queue. Never commits; callers own transactions."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.jobs.models import Job, JobStatus

# Keeps a runaway traceback from bloating the jobs table; the full one is in the logs.
MAX_ERROR_LENGTH = 2000


def add_job(session: Session, tenant_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> Job:
    job = Job(tenant_id=tenant_id, kind=kind, payload=payload, status=JobStatus.QUEUED)
    session.add(job)
    session.flush()
    return job


def claim_next_job(session: Session) -> Job | None:
    """Lock the oldest queued job and mark it running.

    SKIP LOCKED lets several workers poll at once: a job locked by one worker is invisible
    to the others until that transaction ends, so no job is processed twice.
    """
    job = session.scalar(
        select(Job)
        .where(Job.status == JobStatus.QUEUED)
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    session.flush()
    return job


def mark_job_finished(
    session: Session, job_id: uuid.UUID, status: JobStatus, error: str | None = None
) -> None:
    session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(
            status=status,
            error=error[:MAX_ERROR_LENGTH] if error else None,
            finished_at=datetime.now(UTC),
        )
    )


def get_job_in_tenant(session: Session, tenant_id: uuid.UUID, job_id: uuid.UUID) -> Job | None:
    return session.scalar(select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id))


def get_latest_job_for_document(
    session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> Job | None:
    return session.scalar(
        select(Job)
        .where(Job.tenant_id == tenant_id, Job.payload["document_id"].astext == str(document_id))
        .order_by(Job.created_at.desc())
        .limit(1)
    )
