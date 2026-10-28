"""Turn one stored document into embedded chunks: chunk → embed → store."""

import logging
import uuid

from sqlalchemy.orm import Session

from app.documents import repository as documents_repository
from app.documents.models import Document, DocumentChunk, DocumentStatus
from app.ingestion.chunking import TokenWindowChunker
from app.ingestion.embedding import Embedder
from app.jobs.models import Job

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """A document that cannot be ingested; the worker records the message on the job."""


def process_document(
    session: Session, document: Document, chunker: TokenWindowChunker, embedder: Embedder
) -> int:
    """Replace the document's chunks for this chunker and mark it ingested. Does not commit."""
    chunks = chunker.chunk(document.content)
    if not chunks:
        raise IngestionError("Document has no indexable text (only headings or whitespace).")

    vectors = embedder.embed_documents([chunk.text for chunk in chunks])
    rows = [
        DocumentChunk(
            document_id=document.id,
            tenant_id=document.tenant_id,
            chunker=chunker.name,
            ordinal=chunk.ordinal,
            text=chunk.text,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            heading_path=chunk.heading_path,
            embedding=vector,
            embedding_model=embedder.model_name,
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    documents_repository.replace_chunks(session, document, chunker.name, rows)
    document.status = DocumentStatus.INGESTED
    return len(rows)


def run_ingest_job(
    session: Session, job: Job, chunker: TokenWindowChunker, embedder: Embedder
) -> None:
    """Job handler: chunks, vectors and the status change commit together or not at all."""
    document = _load_job_document(session, job)
    chunk_count = process_document(session, document, chunker, embedder)
    session.commit()
    logger.info(
        "document ingested",
        extra={"fields": {"document_id": str(document.id), "chunks": chunk_count}},
    )


def mark_document_failed(session: Session, job: Job) -> None:
    """Failure hook: called by the worker after rolling back a failed ingest job."""
    document = _load_job_document(session, job)
    document.status = DocumentStatus.FAILED


def _load_job_document(session: Session, job: Job) -> Document:
    # The job's own tenant_id scopes the lookup, so a payload can't point across tenants.
    document_id = uuid.UUID(job.payload["document_id"])
    document = documents_repository.get_document_in_tenant(session, job.tenant_id, document_id)
    if document is None:
        raise IngestionError(f"Document {document_id} no longer exists.")
    return document
