import pytest

from app.evaluation.relevance import EvidenceItem, Span, match_evidence, overlaps


def span(start: int, end: int, slug: str = "fastapi/deps", version: str = "0.115") -> Span:
    return Span(slug, version, start, end)


@pytest.mark.parametrize(
    ("chunk", "label", "expected"),
    [
        pytest.param(span(0, 100), span(20, 60), True, id="label-inside-chunk"),
        pytest.param(span(0, 100), span(80, 120), True, id="exactly-half-of-short-label"),
        pytest.param(span(0, 100), span(81, 121), False, id="just-under-half"),
        pytest.param(span(0, 100), span(100, 140), False, id="touching-only"),
        pytest.param(span(0, 100), span(-500, 500), True, id="chunk-inside-long-label"),
        pytest.param(span(0, 100), span(51, 1000), False, id="long-label-covers-under-half"),
        pytest.param(span(0, 100), span(20, 60, version="0.110"), False, id="other-version"),
        pytest.param(span(0, 100), span(20, 60, slug="other"), False, id="other-document"),
    ],
)
def test_overlap_rule(chunk: Span, label: Span, expected: bool) -> None:
    assert overlaps(chunk, label) is expected


def test_threshold_is_a_parameter() -> None:
    assert overlaps(span(0, 100), span(90, 110), min_fraction=0.5) is True
    assert overlaps(span(0, 100), span(90, 110), min_fraction=0.6) is False


def test_match_evidence_keeps_rank_order_and_alternatives() -> None:
    evidence = [
        # The same fact in two versions: either location satisfies it.
        EvidenceItem(3, (span(0, 50), span(0, 50, version="0.110"))),
        EvidenceItem(1, (span(200, 260),)),
    ]
    ranked = [span(300, 400), span(0, 40, version="0.110"), span(190, 270), span(10, 50)]

    assert match_evidence(ranked, evidence) == [
        frozenset(),
        frozenset({0}),
        frozenset({1}),
        frozenset({0}),
    ]
