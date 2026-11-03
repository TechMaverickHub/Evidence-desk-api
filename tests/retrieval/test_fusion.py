import pytest

from app.retrieval.fusion import fuse_rankings_rrf


def test_scores_sum_reciprocal_ranks_over_rankings() -> None:
    fused = fuse_rankings_rrf([["a", "b", "c"], ["b", "d"]], k=60)

    by_item = {f.item: f for f in fused}
    assert by_item["b"].score == pytest.approx(1 / 62 + 1 / 61)
    assert by_item["a"].score == pytest.approx(1 / 61)
    assert by_item["d"].score == pytest.approx(1 / 62)
    assert by_item["b"].ranks == (2, 1)
    assert by_item["d"].ranks == (None, 2)
    # b appears in both lists, so it beats a, which is first in only one.
    assert [f.item for f in fused] == ["b", "a", "d", "c"]


def test_equal_scores_are_ordered_by_best_rank_then_item() -> None:
    # x and y both score 1/61 + 1/63; z and w score 1/62 each.
    fused = fuse_rankings_rrf([["x", "z", "y"], ["y", "w", "x"]], k=60)

    assert [f.item for f in fused] == ["x", "y", "w", "z"]


def test_an_empty_ranking_leaves_the_other_order_unchanged() -> None:
    fused = fuse_rankings_rrf([["a", "b"], []])

    assert [f.item for f in fused] == ["a", "b"]
    assert fused[0].ranks == (1, None)


def test_no_rankings_fuse_to_nothing() -> None:
    assert fuse_rankings_rrf([[], []]) == []
