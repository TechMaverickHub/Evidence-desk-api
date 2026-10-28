"""Liveness/readiness endpoint used by Docker, CI and load balancers."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.core.db import check_database

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unreachable"]


@router.get(
    "/health",
    summary="Report service health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Database unreachable"}},
)
def health(
    response: Response,
    is_database_up: Annotated[bool, Depends(check_database)],
) -> HealthResponse:
    if is_database_up:
        return HealthResponse(status="ok", database="ok")
    # Return the same body shape with 503 (not the error envelope) so health probes can
    # read which dependency failed.
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="degraded", database="unreachable")
