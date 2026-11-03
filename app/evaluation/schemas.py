"""Request and response models for evaluation runs over the API."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.evaluation.models import DatasetSplit
from app.evaluation.records import (
    EffectiveSettings,
    GitState,
    MetricRow,
    OverlapBands,
    Percentiles,
    QuestionRecord,
    RunConfig,
)
from app.jobs.models import JobStatus

# Checked before any file access, so a dataset name can never become a path.
DATASET_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"


class CreateRunRequest(BaseModel):
    # extra="forbid": tenant and user come only from the token.
    model_config = ConfigDict(extra="forbid")

    dataset: str = Field(pattern=DATASET_NAME_PATTERN, examples=["evidencedesk-v1"])
    split: DatasetSplit
    config: RunConfig
    # validate_default: the guard below must also run when the field is omitted.
    allow_test: bool = Field(default=False, validate_default=True)

    @field_validator("allow_test")
    @classmethod
    def test_split_must_be_explicit(cls, allow_test: bool, info: ValidationInfo) -> bool:
        # Tuning happens on dev; a test run is a deliberate act (same rule as the CLI).
        if info.data.get("split") == DatasetSplit.TEST and not allow_test:
            raise ValueError("split 'test' requires allow_test: true")
        return allow_test


class CreateRunResponse(BaseModel):
    run_id: uuid.UUID
    job_id: uuid.UUID


class RunStatus(BaseModel):
    """The run's state, read from its job."""

    status: JobStatus
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class RunListItem(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    status: JobStatus
    dataset_name: str
    split: DatasetSplit
    config_name: str
    created_at: datetime
    finished_at: datetime | None
    # The "all" row at the largest cutoff; null until the run has succeeded.
    overall: MetricRow | None


class RunListResponse(BaseModel):
    items: list[RunListItem]
    total: int
    limit: int
    offset: int


class RunSummary(BaseModel):
    metrics: dict[int, dict[str, MetricRow]]
    overlap_bands: OverlapBands | None
    latency_ms: dict[str, Percentiles]


class RunDatasetInfo(BaseModel):
    name: str
    sha256: str
    split: DatasetSplit


class RunDetail(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    created_by: uuid.UUID
    created_at: datetime
    run: RunStatus
    dataset: RunDatasetInfo
    config: RunConfig
    # Provenance and numbers: null until the run has succeeded.
    executed_at: datetime | None
    effective: EffectiveSettings | None
    git: GitState | None
    environment: dict[str, Any] | None
    corpus_documents: int | None
    summary: RunSummary | None
    # Per-question results, only with ?include=results.
    results: list[QuestionRecord] | None
