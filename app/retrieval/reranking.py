"""Second-stage ranking: re-score retrieved chunks against the query and reorder them.

The real model lives in `app/ingestion/local_models.py` (the only torch importer); tests
use a fake. Anything with this shape can rerank any retriever's output.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Protocol

from app.retrieval.repository import SearchHit


class Reranker(Protocol):
    """Scores (query, passage) pairs; higher means more relevant. One score per passage."""

    model_name: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


def rerank_hits(
    reranker: Reranker,
    query: str,
    hits: Sequence[SearchHit],
    k: int,
    passage: Callable[[SearchHit], str] = lambda hit: hit.text,
) -> list[SearchHit]:
    """Reorder `hits` by rerank score and keep the top k.

    `passage` is the text the reranker reads for a hit (by default the chunk text; with a
    contextual-header chunker, the same header + text that was embedded). Each hit keeps its
    first-stage position; `score` becomes the rerank score. Ties fall back to the
    first-stage order, so the result is deterministic.
    """
    if not hits:
        return []
    scores = reranker.score(query, [passage(hit) for hit in hits])
    rescored = [
        replace(hit, score=score, rerank_score=score, first_stage_rank=position)
        for position, (hit, score) in enumerate(zip(hits, scores, strict=True), start=1)
    ]
    rescored.sort(key=lambda hit: (-hit.score, hit.first_stage_rank))
    return rescored[:k]
