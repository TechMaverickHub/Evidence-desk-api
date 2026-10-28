"""Response model for job status. Payloads stay internal."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.jobs.models import JobStatus


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    status: JobStatus
    attempts: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
