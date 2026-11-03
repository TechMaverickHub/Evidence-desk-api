"""Reciprocal Rank Fusion: combine rankings from retrievers whose scores are not comparable."""

from collections.abc import Hashable, Sequence
from dataclasses import dataclass

# Cormack, Clarke & Büttcher (2009). Larger k flattens the advantage of the very top ranks.
DEFAULT_RRF_K = 60


@dataclass(frozen=True)
class FusedItem:
    item: Hashable
    score: float
    # 1-based rank in each input ranking, None where the item was absent.
    ranks: tuple[int | None, ...]


def fuse_rankings_rrf(
    rankings: Sequence[Sequence[Hashable]], k: int = DEFAULT_RRF_K
) -> list[FusedItem]:
    """RRF score(d) = sum over rankings r containing d of 1 / (k + rank_r(d)).

    Only ranks are used, so cosine similarity and ts_rank_cd never need normalising.
    Ties are broken by the best single rank, then by the item itself, so the order is
    deterministic.
    """
    ranks: dict[Hashable, list[int | None]] = {}
    for position, ranking in enumerate(rankings):
        for rank, item in enumerate(ranking, start=1):
            ranks.setdefault(item, [None] * len(rankings))[position] = rank
    fused = [
        FusedItem(item, sum(1 / (k + rank) for rank in item_ranks if rank), tuple(item_ranks))
        for item, item_ranks in ranks.items()
    ]
    return sorted(fused, key=lambda f: (-f.score, min(r for r in f.ranks if r), str(f.item)))
