"""HTTP endpoints for submitting and reading documents."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.auth.models import Role
from app.core.deps import CurrentUser, SessionDep, require_role
from app.core.errors import ErrorResponse
from app.documents import service
from app.documents.models import Document
from app.documents.schemas import (
    DocumentDetail,
    DocumentListResponse,
    DocumentSummary,
    IngestDocumentRequest,
    IngestDocumentResponse,
)

router = APIRouter(prefix="/documents", tags=["documents"])

EditorDep = Annotated[CurrentUser, Depends(require_role(Role.EDITOR))]
ViewerDep = Annotated[CurrentUser, Depends(require_role(Role.VIEWER))]

AUTH_ERRORS = {
    401: {"model": ErrorResponse, "description": "Not authenticated"},
    403: {"model": ErrorResponse, "description": "Role too low"},
}


@router.post(
    "/ingest",
    summary="Submit a document for ingestion",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestDocumentResponse,
    responses={
        **AUTH_ERRORS,
        200: {"model": IngestDocumentResponse, "description": "Already submitted; no new job"},
        409: {"model": ErrorResponse, "description": "Same slug and version, different content"},
    },
)
def ingest_document(
    payload: IngestDocumentRequest, editor: EditorDep, session: SessionDep, response: Response
) -> IngestDocumentResponse:
    result = service.ingest_document(session, editor.tenant_id, payload)
    if not result.is_new_job:
        response.status_code = status.HTTP_200_OK
    return IngestDocumentResponse(
        document_id=result.document_id, job_id=result.job_id, status=result.status
    )


@router.get(
    "",
    summary="List the tenant's documents",
    response_model=DocumentListResponse,
    responses=AUTH_ERRORS,
)
def list_documents(
    viewer: ViewerDep,
    session: SessionDep,
    source: str | None = None,
    version: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    documents, total = service.list_documents(
        session, viewer.tenant_id, source, version, limit, offset
    )
    return DocumentListResponse(
        items=[DocumentSummary.model_validate(document) for document in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{document_id}",
    summary="Get one document's metadata",
    response_model=DocumentDetail,
    responses={**AUTH_ERRORS, 404: {"model": ErrorResponse, "description": "Not found"}},
)
def get_document(document_id: uuid.UUID, viewer: ViewerDep, session: SessionDep) -> DocumentDetail:
    document = service.get_document(session, viewer.tenant_id, document_id)
    return _to_detail(document, service.count_chunks(session, document))


def _to_detail(document: Document, chunk_count: int) -> DocumentDetail:
    summary = DocumentSummary.model_validate(document)
    return DocumentDetail(
        **summary.model_dump(),
        content_hash=document.content_hash,
        metadata=document.doc_metadata,
        chunk_count=chunk_count,
    )
