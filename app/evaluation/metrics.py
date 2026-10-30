"""Retrieval metrics over ranked evidence matches.

Every function takes `matches`: for each ranked chunk (rank 1 first), the set of evidence-item
indexes it matches (see `relevance.match_evidence`). Recall and nDCG are measured per evidence
item, so they don't depend on chunk size, and an item is credited only once however many
chunks repeat it.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import fmean

Matches = Sequence[frozenset[int]]


def precision_at_k(matches: Matches, k: int) -> float:
    """Fraction of the top-k slots holding a relevant chunk. Divides by k even when fewer
    than k chunks were returned, so returning less is not rewarded."""
    return sum(1 for matched in matches[:k] if matched) / k


def recall_at_k(matches: Matches, item_count: int, k: int) -> float:
    """Fraction of evidence items matched by at least one chunk in the top k."""
    found = set().union(*matches[:k]) if matches[:k] else set()
    return len(found) / item_count


def reciprocal_rank(matches: Matches, k: int) -> float:
    """1 / rank of the first relevant chunk in the top k, else 0 (averaged into MRR@k)."""
    for rank, matched in enumerate(matches[:k], start=1):
        if matched:
            return 1 / rank
    return 0.0


def ndcg_at_k(matches: Matches, grades: Sequence[int], k: int) -> float:
    """Normalised discounted cumulative gain with graded relevance.

    DCG = sum over ranks i <= k of (2^g_i - 1) / log2(i + 1), where g_i is the highest grade
    among items matched for the first time at rank i (0 if none). Crediting each item once
    keeps nDCG <= 1. The ideal ranking puts one item per rank, best grade first.
    """
    credited: set[int] = set()
    dcg = 0.0
    for rank, matched in enumerate(matches[:k], start=1):
        new_items = matched - credited
        if not new_items:
            continue
        credited |= new_items
        dcg += _gain(max(grades[index] for index in new_items), rank)

    ideal_grades = sorted(grades, reverse=True)[:k]
    idcg = sum(_gain(grade, rank) for rank, grade in enumerate(ideal_grades, start=1))
    return dcg / idcg


def _gain(grade: int, rank: int) -> float:
    return (2**grade - 1) / math.log2(rank + 1)


@dataclass(frozen=True)
class QueryScores:
    query_id: str
    query_type: str
    precision: float
    recall: float
    reciprocal_rank: float
    ndcg: float


@dataclass(frozen=True)
class MetricSummary:
    count: int
    precision: float
    recall: float
    mrr: float
    ndcg: float


def score_query(
    query_id: str, query_type: str, matches: Matches, grades: Sequence[int], k: int
) -> QueryScores:
    if not grades:
        # Unanswerable questions have no evidence; they are scored for abstention instead.
        raise ValueError(f"{query_id} has no evidence; retrieval metrics are undefined")
    return QueryScores(
        query_id=query_id,
        query_type=query_type,
        precision=precision_at_k(matches, k),
        recall=recall_at_k(matches, len(grades), k),
        reciprocal_rank=reciprocal_rank(matches, k),
        ndcg=ndcg_at_k(matches, grades, k),
    )


def aggregate(scores: Iterable[QueryScores]) -> dict[str, MetricSummary]:
    """Means over queries: key "all" plus one key per query type, each with its count."""
    groups: dict[str, list[QueryScores]] = defaultdict(list)
    for score in scores:
        groups["all"].append(score)
        groups[score.query_type].append(score)
    return {name: _summarise(group) for name, group in groups.items()}


def _summarise(group: Sequence[QueryScores]) -> MetricSummary:
    return MetricSummary(
        count=len(group),
        precision=fmean(score.precision for score in group),
        recall=fmean(score.recall for score in group),
        mrr=fmean(score.reciprocal_rank for score in group),
        ndcg=fmean(score.ndcg for score in group),
    )
