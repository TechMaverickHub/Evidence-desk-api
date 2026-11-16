"""Answer a question from retrieved passages, or abstain.

retrieve → (nothing? abstain without an LLM call) → number passages → LLM with a strict
schema → check the reply against what was sent → at most one corrective retry → respond.
Malformed or unsupported output is never returned.
"""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import LLMInvalidOutputError, LLMNotConfiguredError
from app.generation.citations import (
    CheckedAnswer,
    InvalidReplyError,
    LabelledPassage,
    check_reply,
    format_passages,
    label_passages,
)
from app.generation.llm_client import LLMClient, LLMOutputRejectedError, LLMReply, Messages
from app.generation.prompts import AnswerPrompts
from app.generation.schemas import (
    AnswerRequest,
    AnswerResponse,
    AnswerUsage,
    Citation,
    RetrievalSummary,
    model_answer_schema,
)
from app.ingestion.embedding import Embedder
from app.retrieval.reranking import Reranker
from app.retrieval.schemas import DocumentRef
from app.retrieval.service import SearchOptions, score_kind, search

logger = logging.getLogger(__name__)

SCHEMA_NAME = "evidence_answer"
# Experiment C (task 008): reranking the dense top 20 gave the best quality per second.
ANSWER_RERANK_DEPTH = 20
SNIPPET_CHARS = 240
_ABSTAIN = CheckedAnswer("insufficient_evidence", "", [])


@dataclass
class _Usage:
    model: str | None = None
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_ms: float = 0.0


def answer_question(
    session: Session,
    tenant_id: uuid.UUID,
    request: AnswerRequest,
    embedder: Embedder,
    reranker_provider: Callable[[], Reranker],
    llm: LLMClient | None,
    prompts: AnswerPrompts,
) -> AnswerResponse:
    if llm is None:
        raise LLMNotConfiguredError("Answering is not configured on this server (no LLM API key).")
    started = time.perf_counter()
    options = _search_options(request)
    reranker = reranker_provider() if options.rerank else None
    outcome = search(session, tenant_id, embedder, request.question, options, reranker)
    passages = label_passages(outcome.hits)
    usage = _Usage()
    # Nothing retrieved, or too weak a best match: don't pay for an LLM call.
    checked = (
        _ask(llm, prompts, request.question, passages, usage)
        if passages and not _below_gate(outcome.hits[0].score, options)
        else _ABSTAIN
    )
    latency_ms = {
        "retrieval": outcome.latency_ms["total"],
        "llm": round(usage.llm_ms, 2),
        "total": round((time.perf_counter() - started) * 1000, 2),
    }
    return _response(checked, passages, options, usage, latency_ms)


def _below_gate(top_score: float, options: SearchOptions) -> bool:
    """The optional abstention gate (task 009b). It compares cross-encoder scores only,
    because that is the scale it was calibrated on."""
    threshold = get_settings().answer_min_rerank_score
    return threshold is not None and options.rerank and top_score < threshold


def _search_options(request: AnswerRequest) -> SearchOptions:
    retrieval = request.retrieval
    return SearchOptions(
        k=get_settings().answer_context_chunks,
        mode=retrieval.mode,
        rerank=retrieval.rerank,
        rerank_depth=ANSWER_RERANK_DEPTH,
        source=retrieval.filters.source,
        version=retrieval.filters.version,
    )


def _ask(
    llm: LLMClient,
    prompts: AnswerPrompts,
    question: str,
    passages: list[LabelledPassage],
    usage: _Usage,
) -> CheckedAnswer:
    """One call, and one corrective retry if the reply can't be accepted."""
    messages: Messages = [
        {"role": "system", "content": prompts.system},
        {"role": "user", "content": prompts.user_message(question, format_passages(passages))},
    ]
    try:
        return _attempt(llm, messages, passages, usage)
    except InvalidReplyError as first:
        messages.append({"role": "user", "content": prompts.retry_message(first.problem)})
    try:
        return _attempt(llm, messages, passages, usage)
    except InvalidReplyError as second:
        if second.kind == "format":
            raise LLMInvalidOutputError() from second
        # An answer we can't tie to the passages is downgraded, never passed through.
        return _ABSTAIN


def _attempt(
    llm: LLMClient, messages: Messages, passages: list[LabelledPassage], usage: _Usage
) -> CheckedAnswer:
    usage.llm_calls += 1
    try:
        reply = llm.complete_json(messages, model_answer_schema(), SCHEMA_NAME)
    except LLMOutputRejectedError as exc:
        _log_call(llm.model_name, usage.llm_calls, None, "rejected")
        raise InvalidReplyError("format", "the provider rejected the generated output") from exc
    usage.model = reply.model
    usage.prompt_tokens += reply.prompt_tokens
    usage.completion_tokens += reply.completion_tokens
    usage.llm_ms += reply.latency_ms
    try:
        checked = check_reply(reply.content, passages)
    except InvalidReplyError as invalid:
        _log_call(reply.model, usage.llm_calls, reply, invalid.kind)
        raise
    _log_call(reply.model, usage.llm_calls, reply, checked.status)
    return checked


def _log_call(model: str, attempt: int, reply: LLMReply | None, outcome: str) -> None:
    # Metadata only: never the question, passages or answer text.
    fields: dict[str, object] = {"model": model, "attempt": attempt, "outcome": outcome}
    if reply is not None:
        fields |= {
            "latency_ms": reply.latency_ms,
            "prompt_tokens": reply.prompt_tokens,
            "completion_tokens": reply.completion_tokens,
        }
    logger.info("llm call", extra={"fields": fields})


def _response(
    checked: CheckedAnswer,
    passages: list[LabelledPassage],
    options: SearchOptions,
    usage: _Usage,
    latency_ms: dict[str, float],
) -> AnswerResponse:
    return AnswerResponse(
        status=checked.status,
        answer=checked.answer,
        citations=[_citation(passage) for passage in checked.cited],
        retrieval=RetrievalSummary(
            mode=options.mode,
            rerank=options.rerank,
            context_chunk_ids=[passage.hit.chunk_id for passage in passages],
            top_score=passages[0].hit.score if passages else None,
            score_kind=score_kind(options.mode, options.rerank),
        ),
        usage=AnswerUsage(
            model=usage.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            llm_calls=usage.llm_calls,
        ),
        latency_ms=latency_ms,
    )


def _citation(passage: LabelledPassage) -> Citation:
    hit = passage.hit
    return Citation(
        chunk_id=hit.chunk_id,
        document=DocumentRef(
            id=hit.document_id,
            source=hit.source,
            slug=hit.slug,
            version=hit.version,
            title=hit.title,
        ),
        heading_path=hit.heading_path,
        char_start=hit.char_start,
        char_end=hit.char_end,
        snippet=hit.text[:SNIPPET_CHARS],
    )
