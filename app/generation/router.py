"""HTTP endpoint for grounded answers."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.models import Role
from app.core.deps import CurrentUser, SessionDep, require_role
from app.core.errors import ErrorResponse
from app.generation import service
from app.generation.deps import get_llm_client, get_prompts
from app.generation.llm_client import LLMClient
from app.generation.prompts import AnswerPrompts
from app.generation.schemas import AnswerRequest, AnswerResponse
from app.ingestion.embedding import Embedder
from app.retrieval.deps import get_query_embedder, get_reranker_provider
from app.retrieval.reranking import Reranker

router = APIRouter(tags=["answers"])

ViewerDep = Annotated[CurrentUser, Depends(require_role(Role.VIEWER))]


@router.post(
    "/answers",
    summary="Answer a question from the tenant's documents, with checked citations",
    description=(
        "Retrieves passages (default: dense, reranked top 20, 5 passages as context) and asks "
        "the configured LLM (Groq) for a structured answer. The question and those passages "
        "are sent to the provider. Every citation is checked against the passages sent; "
        "otherwise the status is insufficient_evidence."
    ),
    response_model=AnswerResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Role too low"},
        502: {"model": ErrorResponse, "description": "LLM_INVALID_OUTPUT after one retry"},
        503: {"model": ErrorResponse, "description": "LLM_UNAVAILABLE or not configured"},
    },
)
def answer(
    payload: AnswerRequest,
    viewer: ViewerDep,
    session: SessionDep,
    embedder: Annotated[Embedder, Depends(get_query_embedder)],
    reranker_provider: Annotated[Callable[[], Reranker], Depends(get_reranker_provider)],
    llm: Annotated[LLMClient | None, Depends(get_llm_client)],
    prompts: Annotated[AnswerPrompts, Depends(get_prompts)],
) -> AnswerResponse:
    return service.answer_question(
        session, viewer.tenant_id, payload, embedder, reranker_provider, llm, prompts
    )
