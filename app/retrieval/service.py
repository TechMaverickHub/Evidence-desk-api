"""Search orchestration: pick a retriever by mode, optionally rerank, time each stage.

Modes are entries in `RETRIEVERS`, not branches: a new retriever is a new function.
Reranking (task 008) is a step after any retriever, so the retrievers never change.
"""

import logging
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Literal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion.chunking import chunker_name
from app.ingestion.embedding import Embedder
from app.retrieval import repository
from app.retrieval.fusion import DEFAULT_RRF_K, fuse_rankings_rrf
from app.retrieval.repository import SearchHit, SearchScope
from app.retrieval.reranking import Reranker, rerank_hits

logger = logging.getLogger(__name__)

SearchMode = Literal["dense", "keyword", "hybrid"]
ScoreKind = Literal["cosine", "ts_rank_cd", "rrf", "cross_encoder"]
_SCORE_KIND_BY_MODE: dict[str, ScoreKind] = {
    "dense": "cosine",
    "keyword": "ts_rank_cd",
    "hybrid": "rrf",
}
# Candidates each retriever contributes before fusion; deeper lists let a chunk ranked
# low by one retriever still win when the other ranks it highly.
DEFAULT_FUSION_DEPTH = 50
# Candidates re-scored by the cross-encoder; each costs one model forward pass.
DEFAULT_RERANK_DEPTH = 50


@dataclass(frozen=True)
class SearchOptions:
    k: int = 10
    mode: SearchMode = "dense"
    fusion_depth: int = DEFAULT_FUSION_DEPTH
    rrf_k: int = DEFAULT_RRF_K
    rerank: bool = False
    rerank_depth: int = DEFAULT_RERANK_DEPTH
    source: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class SearchOutcome:
    hits: list[SearchHit]
    chunker: str
    embedding_model: str
    # Stage name -> milliseconds: embed_query, dense, keyword, fuse, rerank (as used), total.
    latency_ms: dict[str, float]


@dataclass
class _Search:
    """Everything a retriever needs, plus the stage timings it records."""

    session: Session
    scope: SearchScope
    embedder: Embedder
    query: str
    options: SearchOptions
    latency_ms: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def timed(self, stage: str) -> Iterator[None]:
        started = time.perf_counter()
        yield
        self.latency_ms[stage] = _ms(started, time.perf_counter())


def search(
    session: Session,
    tenant_id: uuid.UUID,
    embedder: Embedder,
    query: str,
    options: SearchOptions,
    reranker: Reranker | None = None,
) -> SearchOutcome:
    if options.rerank and reranker is None:
        raise ValueError("Reranking was requested but no reranker was provided")
    scope = SearchScope(
        tenant_id=tenant_id,
        chunker=configured_chunker(),
        # The embedder's own model name, so a query never meets another model's vectors.
        embedding_model=embedder.model_name,
        source=options.source,
        version=options.version,
    )
    run = _Search(session, scope, embedder, query, options)
    started = time.perf_counter()
    hits = _ranked_hits(run, reranker)
    run.latency_ms["total"] = _ms(started, time.perf_counter())
    # The query text is deliberately not logged.
    fields = {"mode": options.mode, "rerank": options.rerank, "k": options.k}
    logger.info("search", extra={"fields": fields | {"results": len(hits)} | run.latency_ms})
    return SearchOutcome(hits, scope.chunker, scope.embedding_model, run.latency_ms)


def _ranked_hits(run: _Search, reranker: Reranker | None) -> list[SearchHit]:
    options = run.options
    if not options.rerank:
        return RETRIEVERS[options.mode](run, options.k)
    # The reranker reorders a deeper candidate list, then cuts it to k.
    candidates = RETRIEVERS[options.mode](run, max(options.k, options.rerank_depth))
    with run.timed("rerank"):
        return rerank_hits(reranker, run.query, candidates, options.k)


def score_kind(mode: SearchMode, rerank: bool) -> ScoreKind:
    """What a hit's `score` means; reranking replaces the retriever's score."""
    return "cross_encoder" if rerank else _SCORE_KIND_BY_MODE[mode]


def configured_chunker() -> str:
    """The chunker whose chunks search reads; the worker writes chunks with the same settings."""
    settings = get_settings()
    return chunker_name(settings.chunk_max_tokens, settings.chunk_overlap_tokens)


def _dense(run: _Search, k: int) -> list[SearchHit]:
    with run.timed("embed_query"):
        query_vector = run.embedder.embed_query(run.query)
    with run.timed("dense"):
        return repository.dense_search(run.session, run.scope, query_vector, k)


def _keyword(run: _Search, k: int) -> list[SearchHit]:
    with run.timed("keyword"):
        return repository.keyword_search(run.session, run.scope, run.query, k)


def _hybrid(run: _Search, k: int) -> list[SearchHit]:
    """Fuse dense and keyword candidates with RRF; the score becomes the RRF score."""
    depth = max(k, run.options.fusion_depth)
    dense_hits = _dense(run, depth)
    keyword_hits = _keyword(run, depth)
    with run.timed("fuse"):
        fused = fuse_rankings_rrf(
            [[hit.chunk_id for hit in dense_hits], [hit.chunk_id for hit in keyword_hits]],
            k=run.options.rrf_k,
        )
        by_id = {hit.chunk_id: hit for hit in [*keyword_hits, *dense_hits]}
        return [
            replace(
                by_id[item.item],
                score=item.score,
                dense_rank=item.ranks[0],
                keyword_rank=item.ranks[1],
            )
            for item in fused[:k]
        ]


RETRIEVERS: dict[str, Callable[[_Search, int], list[SearchHit]]] = {
    "dense": _dense,
    "keyword": _keyword,
    "hybrid": _hybrid,
}


def _ms(start: float, end: float) -> float:
    return round((end - start) * 1000, 2)
