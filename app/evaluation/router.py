"""HTTP endpoints for evaluation runs: start one (admin), list and read them (viewer)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.auth.models import Role
from app.core.deps import CurrentUser, SessionDep, require_role
from app.core.errors import ErrorResponse
from app.evaluation import service
from app.evaluation.models import DatasetSplit
from app.evaluation.schemas import (
    DATASET_NAME_PATTERN,
    CreateRunRequest,
    CreateRunResponse,
    RunDetail,
    RunListResponse,
)

router = APIRouter(prefix="/evaluations/runs", tags=["evaluations"])

AdminDep = Annotated[CurrentUser, Depends(require_role(Role.ADMIN))]
ViewerDep = Annotated[CurrentUser, Depends(require_role(Role.VIEWER))]

AUTH_ERRORS = {
    401: {"model": ErrorResponse, "description": "Not authenticated"},
    403: {"model": ErrorResponse, "description": "Role too low"},
}


@router.post(
    "",
    summary="Queue an evaluation run on a dataset split",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CreateRunResponse,
    responses={
        **AUTH_ERRORS,
        422: {
            "model": ErrorResponse,
            "description": "Invalid config, unknown dataset, or test split without allow_test",
        },
    },
)
def create_run(
    payload: CreateRunRequest, admin: AdminDep, session: SessionDep
) -> CreateRunResponse:
    return service.create_run(session, admin, payload)


@router.get(
    "",
    summary="List the tenant's evaluation runs, newest first",
    response_model=RunListResponse,
    responses=AUTH_ERRORS,
)
def list_runs(
    viewer: ViewerDep,
    session: SessionDep,
    dataset: Annotated[str | None, Query(pattern=DATASET_NAME_PATTERN)] = None,
    split: DatasetSplit | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunListResponse:
    return service.list_runs(session, viewer.tenant_id, dataset, split, limit, offset)


@router.get(
    "/{run_id}",
    summary="Get one run: status, provenance, metrics, and optionally per-question results",
    response_model=RunDetail,
    responses={**AUTH_ERRORS, 404: {"model": ErrorResponse, "description": "Not found"}},
)
def get_run(
    run_id: uuid.UUID,
    viewer: ViewerDep,
    session: SessionDep,
    include: Literal["results"] | None = None,
) -> RunDetail:
    return service.get_run(session, viewer.tenant_id, run_id, include_results=include == "results")
