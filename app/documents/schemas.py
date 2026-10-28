"""Request and response models for documents. Document content is never listed."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.documents.models import DocumentStatus

MAX_CONTENT_CHARS = 1_000_000
MAX_METADATA_KEYS = 20

MetadataValue = str | int | float | bool


class IngestDocumentRequest(BaseModel):
    # extra="forbid": a client cannot smuggle in tenant_id or status.
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=100, examples=["fastapi-docs"])
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9/_.-]{0,199}$", examples=["fastapi/dependencies"])
    version: str = Field(min_length=1, max_length=50, examples=["0.115"])
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def content_must_have_text(cls, content: str) -> str:
        if not content.strip():
            raise ValueError("must contain non-whitespace text")
        return content

    @field_validator("metadata")
    @classmethod
    def metadata_must_be_small(cls, metadata: dict[str, MetadataValue]) -> dict[str, MetadataValue]:
        if len(metadata) > MAX_METADATA_KEYS:
            raise ValueError(f"at most {MAX_METADATA_KEYS} keys allowed")
        return metadata


class IngestDocumentResponse(BaseModel):
    document_id: uuid.UUID
    job_id: uuid.UUID
    status: DocumentStatus


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    slug: str
    version: str
    title: str
    status: DocumentStatus
    created_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    total: int
    limit: int
    offset: int


class DocumentDetail(DocumentSummary):
    content_hash: str
    metadata: dict[str, MetadataValue]
    chunk_count: int
