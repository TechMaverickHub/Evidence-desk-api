"""HTTP endpoint for searching the caller's documents."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.core.deps import CurrentUserDep, SessionDep
from app.core.errors import ErrorResponse
from app.ingestion.embedding import Embedder
from app.retrieval import service
from app.retrieval.deps import get_query_embedder
from app.retrieval.repository import SearchHit
from app.retrieval.schemas import (
    DocumentRef,
    SearchDiagnostics,
    SearchRequest,
    SearchResponse,
    SearchResult,
)

router = APIRouter(tags=["search"])


@router.post(
    "/search",
    summary="Search the tenant's documents",
    response_model=SearchResponse,
    responses={401: {"model": ErrorResponse, "description": "Not authenticated"}},
)
def search(
    payload: SearchRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
    embedder: Annotated[Embedder, Depends(get_query_embedder)],
) -> SearchResponse:
    options = service.SearchOptions(
        k=payload.k,
        mode=payload.mode,
        source=payload.filters.source,
        version=payload.filters.version,
    )
    outcome = service.search(session, current_user.tenant_id, embedder, payload.query, options)
    return SearchResponse(
        results=[_to_result(rank, hit) for rank, hit in enumerate(outcome.hits, start=1)],
        diagnostics=SearchDiagnostics(
            mode=payload.mode,
            k=payload.k,
            chunker=outcome.chunker,
            embedding_model=outcome.embedding_model,
            query_instruction=bool(get_settings().embedding_query_instruction),
            latency_ms=outcome.latency_ms,
        ),
    )


def _to_result(rank: int, hit: SearchHit) -> SearchResult:
    return SearchResult(
        rank=rank,
        chunk_id=hit.chunk_id,
        score=hit.score,
        dense_rank=hit.dense_rank,
        keyword_rank=hit.keyword_rank,
        text=hit.text,
        char_start=hit.char_start,
        char_end=hit.char_end,
        heading_path=hit.heading_path,
        document=DocumentRef(
            id=hit.document_id,
            source=hit.source,
            slug=hit.slug,
            version=hit.version,
            title=hit.title,
        ),
    )
