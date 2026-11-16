"""Evaluation regression gate (task 013): did a change make the adopted config worse on dev?

The gate compares a fresh run with a committed baseline run of the same config. It fails when
a headline metric drops by more than a fixed tolerance. The paired bootstrap interval is
reported but does not decide: the gate asks "did we break it?", and on ~70 questions the
interval is too wide to catch real drops.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.evaluation.records import QuestionRecord, RunReport
from app.evaluation.report import TIE_TOLERANCE, paired_bootstrap_ci, paired_questions, row_order

# Absorbs float noise between platforms (Windows baseline, Linux CI) while staying well below
# the smallest change adopted so far (+0.057 hit@5 in task 010).
DEFAULT_TOLERANCE = 0.02
# (label, field on MetricRow and QueryScoreRow, cutoff)
GATED_METRICS = (("nDCG", "ndcg", 10), ("R", "recall", 10), ("Hit", "hit", 5))


class GateError(Exception):
    """Two runs the gate refuses to compare."""


@dataclass(frozen=True)
class MetricCheck:
    label: str
    field: str
    k: int
    baseline: float
    candidate: float
    ci: tuple[float, float]

    @property
    def delta(self) -> float:
        return self.candidate - self.baseline


@dataclass(frozen=True)
class GateResult:
    tolerance: float
    checks: list[MetricCheck]

    def failed(self, check: MetricCheck) -> bool:
        # TIE_TOLERANCE keeps a drop of exactly the tolerance from failing on float error.
        return check.delta < -self.tolerance - TIE_TOLERANCE

    @property
    def passed(self) -> bool:
        return not any(self.failed(check) for check in self.checks)


def evaluate_gate(
    baseline: RunReport, candidate: RunReport, tolerance: float = DEFAULT_TOLERANCE
) -> GateResult:
    if tolerance < 0:
        raise GateError("The tolerance must not be negative")
    _check_comparable(baseline, candidate)
    pairs = [
        (b, c)
        for b, c in paired_questions(baseline, candidate)
        if b.scores is not None and c.scores is not None
    ]
    checks = [_check(baseline, candidate, pairs, *metric) for metric in GATED_METRICS]
    return GateResult(tolerance=tolerance, checks=checks)


def _check_comparable(baseline: RunReport, candidate: RunReport) -> None:
    for report in (baseline, candidate):
        if report.header.dataset.split != "dev":
            # Test is for deliberate final comparisons; gating on it would make it a tuning set.
            raise GateError(f"Run {report.header.run_name} is not on the dev split")
    if baseline.header.config != candidate.header.config:
        raise GateError("Runs used different configs; the gate compares one config over time")
    missing = {k for _, _, k in GATED_METRICS} - set(baseline.header.config.cutoffs)
    if missing:
        raise GateError(f"The config has no cutoff {sorted(missing)} for the gated metrics")


def _check(
    baseline: RunReport,
    candidate: RunReport,
    pairs: Sequence[tuple[QuestionRecord, QuestionRecord]],
    label: str,
    field: str,
    k: int,
) -> MetricCheck:
    base_value = getattr(baseline.results.metrics[k]["all"], field)
    candidate_value = getattr(candidate.results.metrics[k]["all"], field)
    if base_value is None or candidate_value is None:
        raise GateError(f"A run has no {label}@{k} (recorded from task 010 onwards)")
    deltas = [getattr(c.scores[k], field) - getattr(b.scores[k], field) for b, c in pairs]
    return MetricCheck(label, field, k, base_value, candidate_value, paired_bootstrap_ci(deltas))


def render_gate(baseline: RunReport, candidate: RunReport, result: GateResult) -> str:
    verdict = "PASSED" if result.passed else "FAILED"
    dataset = baseline.header.dataset
    lines = [
        f"# Evaluation gate {verdict}: `{candidate.header.run_name}`",
        "",
        f"Config `{baseline.header.config.name}` on {dataset.name} `{dataset.split}` "
        f"(sha256 `{dataset.sha256[:12]}`). Fails when a metric drops by more than "
        f"{result.tolerance}.",
        "",
        _provenance("Baseline", baseline),
        _provenance("Candidate", candidate),
        "",
        "| metric | baseline | candidate | delta | 95 % CI (paired) | result |",
        "|---|---|---|---|---|---|",
    ]
    for check in result.checks:
        low, high = check.ci
        status = "**fail**" if result.failed(check) else "pass"
        lines.append(
            f"| {check.label}@{check.k} | {check.baseline:.3f} | {check.candidate:.3f} "
            f"| {check.delta:+.3f} | [{low:+.3f}, {high:+.3f}] | {status} |"
        )
    lines += ["", *_query_type_section(baseline, candidate, result.checks)]
    return "\n".join(lines)


def _provenance(label: str, report: RunReport) -> str:
    header = report.header
    return f"- {label}: git `{header.git.sha[:12]}`, {header.environment.get('os', 'unknown OS')}"


def _query_type_section(
    baseline: RunReport, candidate: RunReport, checks: Sequence[MetricCheck]
) -> list[str]:
    columns = " | ".join(f"{check.label}@{check.k}" for check in checks)
    lines = [
        "## Deltas by query_type (informational: groups are too small to gate on)",
        "",
        f"| query_type | n | {columns} |",
        "|---|---|" + "---|" * len(checks),
    ]
    rows = baseline.results.metrics[checks[0].k]
    for name in row_order(rows):
        cells = " | ".join(_type_delta(baseline, candidate, name, check) for check in checks)
        lines.append(f"| {name} | {rows[name].count} | {cells} |")
    return [*lines, ""]


def _type_delta(baseline: RunReport, candidate: RunReport, name: str, check: MetricCheck) -> str:
    base_row = baseline.results.metrics[check.k].get(name)
    candidate_row = candidate.results.metrics[check.k].get(name)
    if base_row is None or candidate_row is None:
        return "–"
    delta = getattr(candidate_row, check.field) - getattr(base_row, check.field)
    return f"{delta:+.3f}"
