"""Evaluation regression gate (task 013): the rule, refusals and CLI exit codes."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.evaluation import cli
from app.evaluation.gate import GateError, evaluate_gate, render_gate
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
from app.evaluation.report import ComparisonError
from app.evaluation.runner import summarise

QUESTIONS = 10
CUTOFFS = [5, 10]


def _record(index: int, ndcg: float) -> QuestionRecord:
    row = QueryScoreRow(precision=0.1, recall=0.5, reciprocal_rank=0.5, ndcg=ndcg, hit=1.0)
    return QuestionRecord(
        id=f"q-{index}",
        query_type="factual" if index % 2 else "paraphrase",
        question=f"question {index}?",
        answerable=True,
        word_overlap=0.4,
        hits=[],
        scores={k: row for k in CUTOFFS},
        latency_ms={"total": 5.0},
    )


def _report(
    first_ndcg: float = 0.5,
    split: str = "dev",
    cutoffs: list[int] = CUTOFFS,
    config_name: str = "prod",
    sha: str = "abc",
) -> RunReport:
    """Ten questions with nDCG 0.5; the first one's nDCG is set, so its change / 10 is the delta."""
    records = [_record(0, first_ndcg), *(_record(i, 0.5) for i in range(1, QUESTIONS))]
    header = RunHeader(
        run_name=f"{config_name}-{split}",
        created_at=datetime(2026, 11, 16, tzinfo=UTC),
        dataset=DatasetRef(name="mini", sha256=sha, split=split),
        config=RunConfig(name=config_name, cutoffs=cutoffs),
        effective=EffectiveSettings(
            chunker="c", embedding_model="m", query_instruction="", min_overlap_fraction=0.5
        ),
        git=GitState(sha="deadbeef", dirty=False),
        environment={"os": "Linux"},
        corpus_documents=2,
    )
    return RunReport(header=header, results=summarise(records, cutoffs))


def _failed_metrics(baseline: RunReport, candidate: RunReport) -> list[str]:
    result = evaluate_gate(baseline, candidate, tolerance=0.02)
    return [f"{check.label}@{check.k}" for check in result.checks if result.failed(check)]


def test_an_identical_run_passes() -> None:
    result = evaluate_gate(_report(), _report())

    assert result.passed
    assert [check.delta for check in result.checks] == [0.0, 0.0, 0.0]


def test_a_drop_beyond_the_tolerance_fails_and_names_the_metric() -> None:
    # One question loses 0.3 nDCG: the mean drops by 0.03.
    assert _failed_metrics(_report(), _report(first_ndcg=0.2)) == ["nDCG@10"]


@pytest.mark.parametrize("first_ndcg", [0.4, 0.3])
def test_a_drop_within_or_at_the_tolerance_passes(first_ndcg: float) -> None:
    # Mean drops of 0.01 and exactly 0.02 (which float arithmetic may overshoot slightly).
    assert _failed_metrics(_report(), _report(first_ndcg=first_ndcg)) == []


def test_an_improvement_passes() -> None:
    assert evaluate_gate(_report(), _report(first_ndcg=1.0)).passed


def test_the_report_shows_every_gated_metric_and_the_verdict() -> None:
    baseline, candidate = _report(), _report(first_ndcg=0.2)
    markdown = render_gate(baseline, candidate, evaluate_gate(baseline, candidate))

    assert markdown.startswith("# Evaluation gate FAILED")
    assert "| nDCG@10 | 0.500 | 0.470 | -0.030 |" in markdown
    assert "| R@10 |" in markdown
    assert "| Hit@5 |" in markdown
    assert "| paraphrase | 5 |" in markdown


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (_report(split="test"), "not on the dev split"),
        (_report(config_name="other"), "different configs"),
        (_report(sha="changed"), "different datasets"),
    ],
)
def test_runs_the_gate_cannot_compare_are_refused(candidate: RunReport, message: str) -> None:
    with pytest.raises((GateError, ComparisonError), match=message):
        evaluate_gate(_report(split=candidate.header.dataset.split), candidate)


def test_a_config_without_the_gated_cutoffs_is_refused() -> None:
    report = _report(cutoffs=[10])

    with pytest.raises(GateError, match=r"no cutoff \[5\]"):
        evaluate_gate(report, report)


def test_a_negative_tolerance_is_refused() -> None:
    with pytest.raises(GateError, match="must not be negative"):
        evaluate_gate(_report(), _report(), tolerance=-0.1)


def _write(path: Path, report: RunReport) -> str:
    path.write_text(report.model_dump_json())
    return str(path)


@pytest.mark.parametrize(
    ("candidate", "exit_code"),
    [(_report(), 0), (_report(first_ndcg=0.2), 1), (_report(config_name="other"), 2)],
)
def test_gate_cli_exit_codes(tmp_path: Path, candidate: RunReport, exit_code: int) -> None:
    baseline = _write(tmp_path / "baseline.json", _report())
    out = tmp_path / "summary" / "gate.md"

    args = ["gate", baseline, _write(tmp_path / "candidate.json", candidate), "--out", str(out)]

    assert cli.main(args) == exit_code
    assert out.exists() == (exit_code != 2)


def test_gate_cli_refuses_an_unreadable_record(tmp_path: Path) -> None:
    baseline = _write(tmp_path / "baseline.json", _report())

    assert cli.main(["gate", baseline, str(tmp_path / "missing.json")]) == 2
