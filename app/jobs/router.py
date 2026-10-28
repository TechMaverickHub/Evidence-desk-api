"""HTTP endpoint for polling a background job."""

import uuid

from fastapi import APIRouter

from app.core.deps import CurrentUserDep, SessionDep
from app.core.errors import ErrorResponse, NotFoundError
from app.jobs import repository
from app.jobs.schemas import JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "/{job_id}",
    summary="Get a job's status",
    response_model=JobResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Not found"},
    },
)
def get_job(job_id: uuid.UUID, current_user: CurrentUserDep, session: SessionDep) -> JobResponse:
    # A single tenant-scoped read with no rules around it, so there is no service layer here.
    job = repository.get_job_in_tenant(session, current_user.tenant_id, job_id)
    if job is None:
        raise NotFoundError("Job not found.")
    return JobResponse.model_validate(job)
