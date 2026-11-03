"""Evaluation runs started over the API, and their per-question results.

A run's status lives on its job (`job_id`), not here, so the two can never disagree.
The columns mirror `records.RunReport`: a stored run converts back to the same record.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, string_enum


class DatasetSplit(StrEnum):
    DEV = "dev"
    TEST = "test"


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    # Serves the run list: newest first within a tenant.
    __table_args__ = (Index("ix_evaluation_runs_tenant_created_at", "tenant_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), unique=True
    )
    dataset_name: Mapped[str] = mapped_column(String(64))
    # Recorded when the run is queued; the worker refuses to run if the file has changed.
    dataset_sha256: Mapped[str] = mapped_column(String(64))
    split: Mapped[DatasetSplit] = mapped_column(string_enum(DatasetSplit, "dataset_split"))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Filled by the worker when the run succeeds; null while queued, running or failed.
    effective: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    git_sha: Mapped[str | None] = mapped_column(String(64))
    git_dirty: Mapped[bool | None]
    environment: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    corpus_documents: Mapped[int | None]
    # {"metrics", "overlap_bands", "latency_ms"} as in records.RunResults.
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # When the worker finished scoring (header.created_at of the run record).
    executed_at: Mapped[datetime | None]


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (Index("ix_evaluation_results_run_position", "run_id", "position"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"))
    # Dataset order, so results come back in the order the runner produced them.
    position: Mapped[int]
    question_id: Mapped[str] = mapped_column(String(16))
    query_type: Mapped[str] = mapped_column(String(32))
    question: Mapped[str] = mapped_column(Text)
    answerable: Mapped[bool]
    word_overlap: Mapped[float | None]
    hits: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # Cutoff -> scores; null for unanswerable questions.
    scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    latency_ms: Mapped[dict[str, float]] = mapped_column(JSONB)
