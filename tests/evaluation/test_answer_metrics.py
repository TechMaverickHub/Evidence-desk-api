"""Answer metrics on hand-built records: each number is checked against a hand count."""

import pytest

from app.evaluation.answer_metrics import (
    GatePoint,
    choose_gate,
    gate_sweep,
    is_abstained,
    summarise_answers,
)
from app.evaluation.answer_records import AnswerRecord, Judgment, SpanRef


def _span(*matched: int) -> SpanRef:
    return SpanRef(
        chunk_id="c", slug="s", version="1", char_start=0, char_end=1, matched_items=list(matched)
    )


def _record(
    outcome: str = "answered",
    *,
    answerable: bool = True,
    query_type: str = "factual",
    citations: list[SpanRef] | None = None,
    context: list[SpanRef] | None = None,
    evidence_items: int = 2,
    top_score: float | None = 1.0,
    judgments: dict | None = None,
) -> AnswerRecord:
    return AnswerRecord(
        id="q",
        query_type=query_type if answerable else "unanswerable",
        question="?",
        answerable=answerable,
        evidence_items=evidence_items if answerable else 0,
        outcome=outcome,
        answer="a" if outcome == "answered" else "",
        citations=citations or [],
        context=context or [],
        top_score=top_score,
        llm_calls=1,
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms={},
        judgments=judgments or {},
    )


def test_rates_and_failure_attribution_are_counted_by_hand() -> None:
    records = [
        # Answered, cites one on-evidence and one off-evidence chunk, covers 1 of 2 items.
        _record(citations=[_span(0), _span()], context=[_span(0)]),
        # Answered, both items covered.
        _record(citations=[_span(0), _span(1)], context=[_span(0, 1)]),
        # Abstained although the evidence was in the context: a generation failure.
        _record("insufficient_evidence", context=[_span(1)]),
        # Abstained and the evidence never reached the context: a retrieval miss.
        _record("insufficient_evidence", context=[_span()]),
        # Unanswerable: one correct abstention, one answered (a likely hallucination).
        _record("insufficient_evidence", answerable=False),
        _record(answerable=False, citations=[_span()]),
        # Errors are counted but never scored.
        _record("error"),
    ]

    summary = summarise_answers(records)["all"]

    assert (summary.count, summary.errors, summary.answerable, summary.unanswerable) == (7, 1, 4, 2)
    assert summary.answer_rate == pytest.approx(2 / 4)
    assert summary.correct_abstention == pytest.approx(1 / 2)
    assert (summary.false_abstention_retrieval, summary.false_abstention_generation) == (1, 1)
    assert summary.false_abstention == pytest.approx(2 / 4)
    # Citations of answered answerable questions only: 4 cited, 3 on evidence.
    assert summary.citation_precision == pytest.approx(3 / 4)
    assert summary.evidence_coverage == pytest.approx((1 / 2 + 2 / 2) / 2)
    assert summary.context_hit == pytest.approx(3 / 4)


def test_groups_per_query_type_and_judged_verdicts_are_tallied() -> None:
    correct = {"correctness": Judgment(verdict="correct", reason="")}
    unjudged = {"correctness": Judgment(verdict="unjudged", reason="")}
    records = [
        _record(query_type="paraphrase", judgments=correct),
        _record(query_type="paraphrase", judgments=unjudged),
        _record(query_type="factual"),
    ]

    summaries = summarise_answers(records)

    assert set(summaries) == {"all", "paraphrase", "factual"}
    assert summaries["paraphrase"].judged["correctness"] == {"correct": 1, "unjudged": 1}
    assert summaries["factual"].judged == {}


def test_empty_groups_have_no_rates_rather_than_zero() -> None:
    summary = summarise_answers([_record(answerable=False, outcome="insufficient_evidence")])["all"]

    assert summary.answer_rate is None
    assert summary.citation_precision is None


def test_the_simulated_gate_abstains_below_the_threshold_or_without_a_score() -> None:
    assert is_abstained(_record(top_score=0.5), threshold=1.0)
    assert is_abstained(_record(top_score=None), threshold=1.0)
    assert not is_abstained(_record(top_score=1.0), threshold=1.0)
    assert not is_abstained(_record(top_score=-5.0), threshold=None)


def test_the_sweep_scores_every_observed_threshold() -> None:
    records = [
        _record(answerable=False, top_score=-3.0),
        _record(answerable=False, top_score=2.0),
        _record(top_score=1.0),
        _record(top_score=4.0),
    ]

    sweep = gate_sweep(records)

    assert [point.threshold for point in sweep] == [None, -3.0, 1.0, 2.0, 4.0]
    # At t=1.0 only the -3.0 unanswerable is gated: CA 1/2, FA 0/2.
    assert (sweep[2].correct_abstention, sweep[2].false_abstention) == (0.5, 0.0)
    assert sweep[2].j == pytest.approx(0.5)


def test_the_gate_is_adopted_only_for_a_real_gain_and_ties_take_the_lowest() -> None:
    sweep = [
        GatePoint(None, 0.2, 0.0),
        GatePoint(1.0, 0.3, 0.0),
        GatePoint(2.0, 0.3, 0.0),
    ]

    decision = choose_gate(sweep)

    assert decision.best.threshold == 1.0
    assert decision.gain == pytest.approx(0.1)
    assert decision.adopted
    assert not choose_gate([GatePoint(None, 0.2, 0.0), GatePoint(1.0, 0.25, 0.0)]).adopted
