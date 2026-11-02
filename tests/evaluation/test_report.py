from datetime import UTC, datetime

import pytest

from app.evaluation.records import (
    DatasetRef,
    EffectiveSettings,
    GitState,
    QueryScoreRow,
    QuestionRecord,
    RunConfig,
    RunHeader,
    RunReport,
)
from app.evaluation.report import (
    ComparisonError,
    paired_bootstrap_ci,
    render_comparison,
    render_run,
    win_tie_loss,
)
from app.evaluation.runner import summarise


def _record(question_id: str, query_type: str, recall: float, ndcg: float) -> QuestionRecord:
    row = QueryScoreRow(precision=recall / 10, recall=recall, reciprocal_rank=ndcg, ndcg=ndcg)
    return QuestionRecord(
        id=question_id,
        query_type=query_type,
        question=f"question {question_id}?",
        answerable=True,
        word_overlap=0.4,
        hits=[],
        scores={10: row},
        latency_ms={"total": 5.0},
    )


def _report(
    records: list[QuestionRecord], split: str = "dev", name: str = "base", sha: str = "abc"
) -> RunReport:
    header = RunHeader(
        run_name=f"{name}-{split}",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
        dataset=DatasetRef(name="mini", sha256=sha, split=split),
        config=RunConfig(name=name, cutoffs=[10]),
        effective=EffectiveSettings(
            chunker="c", embedding_model="m", query_instruction="", min_overlap_fraction=0.5
        ),
        git=GitState(sha="deadbeef", dirty=False),
        environment={"python": "3.12"},
        corpus_documents=2,
    )
    return RunReport(header=header, results=summarise(records, [10]))


def test_bootstrap_interval_is_exact_for_constant_deltas_and_reproducible() -> None:
    assert paired_bootstrap_ci([0.0] * 20) == (0.0, 0.0)
    assert paired_bootstrap_ci([0.25] * 5) == pytest.approx((0.25, 0.25))
    mixed = [0.5, -0.1, 0.0, 0.3, 0.2, -0.4, 0.1]
    low, high = paired_bootstrap_ci(mixed)
    assert low < sum(mixed) / len(mixed) < high
    assert paired_bootstrap_ci(mixed) == (low, high)


def test_win_tie_loss_treats_float_noise_as_a_tie() -> None:
    assert win_tie_loss([0.5, 0.0, -0.2, 1e-12]) == (1, 2, 1)


def test_dev_report_states_provenance_counts_and_misses() -> None:
    report = _report([_record("q-0001", "factual", 1.0, 1.0), _record("q-0002", "factual", 0, 0)])

    markdown = render_run(report)

    assert "sha256 `abc`" in markdown
    assert "`deadbeef`" in markdown
    assert "| **all** | 2 |" in markdown
    assert "## Misses: nothing relevant in the top 10 (1)" in markdown
    assert "question q-0002?" in markdown


def test_test_report_is_labelled_and_lists_no_misses() -> None:
    report = _report([_record("q-0001", "factual", 0, 0)], split="test")

    markdown = render_run(report)

    assert "Test split" in markdown
    assert "Misses" not in markdown


def test_comparison_counts_per_question_wins_and_losses() -> None:
    base = _report([_record("q-1", "factual", 0, 0.2), _record("q-2", "factual", 1, 0.9)])
    candidate = _report(
        [_record("q-1", "factual", 1, 0.8), _record("q-2", "factual", 1, 0.9)], name="cand"
    )

    markdown = render_comparison(base, candidate)

    assert "| nDCG@10 | +0.300 |" in markdown
    assert "| 1 / 1 / 0 |" in markdown
    assert "0.500 → 1.000 (+0.500)" in markdown


def test_runs_on_different_datasets_are_not_compared() -> None:
    base = _report([_record("q-1", "factual", 0, 0)])
    other = _report([_record("q-1", "factual", 0, 0)], sha="different")

    with pytest.raises(ComparisonError, match="different datasets"):
        render_comparison(base, other)
