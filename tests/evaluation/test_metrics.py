"""Metric values checked against hand-worked examples (log2 2 = 1, log2 3 ≈ 1.585, log2 4 = 2)."""

import math

import pytest

from app.evaluation.metrics import (
    QueryScores,
    aggregate,
    hit_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    score_query,
)

NONE: frozenset[int] = frozenset()
# Two evidence items: item 0 (grade 3) and item 1 (grade 1).
GRADES = [3, 1]
# Rank:      1     2               3               4 (repeats item 0)  5
RANKING = [NONE, frozenset({0}), frozenset({1}), frozenset({0}), NONE]


def test_precision_counts_relevant_slots_and_divides_by_k() -> None:
    assert precision_at_k(RANKING, 5) == pytest.approx(3 / 5)
    assert precision_at_k(RANKING, 2) == pytest.approx(1 / 2)
    # Only 2 results returned for k=5: still divided by 5.
    assert precision_at_k(RANKING[:2], 5) == pytest.approx(1 / 5)


def test_recall_counts_items_not_chunks() -> None:
    assert recall_at_k(RANKING, item_count=2, k=5) == 1.0
    assert recall_at_k(RANKING, item_count=2, k=2) == 0.5
    assert recall_at_k([], item_count=2, k=5) == 0.0
    # Item 0 matched three times is still one item out of two.
    assert recall_at_k([frozenset({0})] * 3, item_count=2, k=3) == 0.5


def test_reciprocal_rank_uses_first_relevant_rank() -> None:
    assert reciprocal_rank(RANKING, 5) == 0.5
    assert reciprocal_rank(RANKING, 1) == 0.0
    assert reciprocal_rank([NONE, NONE], 5) == 0.0


def test_ndcg_with_graded_items_and_a_repeat() -> None:
    # Item 0 first matched at rank 2 (gain 2^3-1 = 7), item 1 at rank 3 (gain 1);
    # the repeat at rank 4 earns nothing. Ideal: grade 3 at rank 1, grade 1 at rank 2.
    dcg = 7 / math.log2(3) + 1 / math.log2(4)
    idcg = 7 / math.log2(2) + 1 / math.log2(3)

    assert ndcg_at_k(RANKING, GRADES, 5) == pytest.approx(dcg / idcg, abs=1e-9)
    assert ndcg_at_k(RANKING, GRADES, 5) == pytest.approx(0.644287, abs=1e-6)


def test_ndcg_is_one_for_the_ideal_ranking_and_zero_without_matches() -> None:
    assert ndcg_at_k([frozenset({0}), frozenset({1})], GRADES, 5) == pytest.approx(1.0)
    assert ndcg_at_k([NONE, NONE], GRADES, 5) == 0.0


def test_chunk_matching_two_items_counts_the_better_grade_once() -> None:
    # One chunk covers both items (grades 3 and 2): rank 1 earns 7, and both are credited.
    ranking = [frozenset({0, 1}), frozenset({1})]
    idcg = 7 + 3 / math.log2(3)

    assert ndcg_at_k(ranking, [3, 2], 5) == pytest.approx(7 / idcg, abs=1e-9)
    assert ndcg_at_k(ranking, [3, 2], 5) <= 1.0


def test_ideal_dcg_is_cut_at_k() -> None:
    # Three items but k=1: the ideal is only the best item at rank 1.
    assert ndcg_at_k([frozenset({0})], [3, 3, 3], 1) == pytest.approx(1.0)


def test_score_query_rejects_unanswerable_questions() -> None:
    with pytest.raises(ValueError, match="no evidence"):
        score_query("q-0001", "unanswerable", RANKING, [], 5)


def test_aggregate_reports_means_and_counts_per_type() -> None:
    scores = [
        QueryScores("q-1", "factual", 1.0, 1.0, 1.0, 1.0, 1.0),
        QueryScores("q-2", "factual", 0.0, 0.5, 0.5, 0.2, 1.0),
        QueryScores("q-3", "paraphrase", 0.5, 0.0, 0.0, 0.0, 0.0),
    ]

    summary = aggregate(scores)

    assert set(summary) == {"all", "factual", "paraphrase"}
    assert summary["factual"].count == 2
    assert summary["factual"].recall == pytest.approx(0.75)
    assert summary["factual"].mrr == pytest.approx(0.75)
    assert summary["all"].count == 3
    assert summary["all"].precision == pytest.approx(0.5)


def test_hit_at_k_is_whether_any_evidence_is_in_the_top_k() -> None:
    matches = [frozenset(), frozenset(), frozenset({1}), frozenset({0})]

    assert hit_at_k(matches, 2) == 0.0
    assert hit_at_k(matches, 3) == 1.0
    assert hit_at_k([], 5) == 0.0


def test_hit_is_averaged_per_group() -> None:
    summary = aggregate(
        [
            QueryScores("q-1", "factual", 0, 0, 0, 0, 1.0),
            QueryScores("q-2", "factual", 0, 0, 0, 0, 0.0),
        ]
    )

    assert summary["factual"].hit == pytest.approx(0.5)
