"""Documents and their chunks (text slices with embeddings)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, string_enum

# Output size of BAAI/bge-small-en-v1.5. A model with another size needs a migration.
EMBEDDING_DIMENSION = 384


class DocumentStatus(StrEnum):
    PENDING = "pending"
    INGESTED = "ingested"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"
    # (slug, version) is immutable per tenant: new content must be a new version, so
    # character-span evidence labels stay valid.
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", "version", name="uq_documents_tenant_slug_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    source: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    # "metadata" is reserved on SQLAlchemy models, so the attribute is named differently.
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )
    status: Mapped[DocumentStatus] = mapped_column(string_enum(DocumentStatus, "document_status"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class DocumentChunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunker", "ordinal", name="uq_chunks_document_chunker"),
        CheckConstraint("char_start >= 0 AND char_end > char_start", name="ck_chunks_offsets"),
        Index("ix_chunks_tenant_chunker", "tenant_id", "chunker"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    # Copied from the document so retrieval can filter by tenant without a join.
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    # Lets several chunking strategies coexist for the same document (Experiment D).
    chunker: Mapped[str] = mapped_column(String(50))
    ordinal: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int]
    char_end: Mapped[int]
    heading_path: Mapped[str] = mapped_column(String(500))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION))
    # Makes vectors from different models detectable instead of silently compared.
    embedding_model: Mapped[str] = mapped_column(String(100))
