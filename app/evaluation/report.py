"""Render run records as Markdown, and compare two runs on the same dataset split.

Everything here reads `RunReport` (the JSON record), so a report can never state a number
the record doesn't hold.
"""

import random
from collections.abc import Sequence
from statistics import fmean

from app.evaluation.records import MetricRow, QuestionRecord, RunReport

BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 0
# Smaller per-query differences count as ties (float noise, not a real change).
TIE_TOLERANCE = 1e-9
# How many top hits a miss listing shows.
MISS_HITS_SHOWN = 3

_BANDS = ("low", "high")
_METRICS = (("P", "precision"), ("R", "recall"), ("MRR", "mrr"), ("nDCG", "ndcg"))


class ComparisonError(Exception):
    """Two runs that cannot be compared question by question."""


# --- Single run -------------------------------------------------------------------------


def render_run(report: RunReport) -> str:
    lines = _run_header(report)
    for k, rows in report.results.metrics.items():
        lines += [f"## Retrieval metrics @{k}", "", *_metric_table(rows, k, _row_order(rows)), ""]
    lines += _overlap_section(report)
    lines += _latency_section(report)
    lines += _unanswerable_section(report.results.questions)
    if report.header.dataset.split == "dev":
        lines += _misses_section(report)
    return "\n".join(lines)


def _run_header(report: RunReport) -> list[str]:
    header = report.header
    dataset = header.dataset
    effective = header.effective
    dirty = {True: " (uncommitted changes)", False: "", None: " (git unavailable)"}
    lines = [
        f"# Run `{header.run_name}`",
        "",
        f"- **Dataset:** {dataset.name}, split `{dataset.split}`, sha256 `{dataset.sha256}`",
        f"- **Config:** `{header.config.model_dump_json()}`",
        f"- **Chunker:** `{effective.chunker}`",
        f"- **Embedding model:** `{effective.embedding_model}`",
        f"- **Query instruction:** `{effective.query_instruction!r}`",
        f"- **Span match:** overlap ≥ {effective.min_overlap_fraction} × the shorter range",
        f"- **Corpus:** {header.corpus_documents} documents verified against `corpus/`",
        f"- **Git:** `{header.git.sha}`{dirty[header.git.dirty]}",
        f"- **Environment:** {', '.join(f'{k} {v}' for k, v in header.environment.items())}",
        f"- **Created:** {header.created_at.isoformat(timespec='seconds')}",
        "",
    ]
    if dataset.split == "test":
        lines += ["> Test split: a final comparison run. Do not tune on these numbers.", ""]
    return lines


def _row_order(rows: dict[str, MetricRow]) -> list[str]:
    """The overall row first, then query types alphabetically."""
    return ["all", *sorted(name for name in rows if name != "all")]


def _metric_table(rows: dict[str, MetricRow], k: int, names: Sequence[str]) -> list[str]:
    columns = " | ".join(f"{label}@{k}" for label, _ in _METRICS)
    lines = [f"| query_type | n | {columns} |", "|---|---|" + "---|" * len(_METRICS)]
    for name in names:
        row = rows[name]
        values = " | ".join(f"{getattr(row, field):.3f}" for _, field in _METRICS)
        label = f"**{name}**" if name == "all" else name
        lines.append(f"| {label} | {row.count} | {values} |")
    return lines


def _overlap_section(report: RunReport) -> list[str]:
    bands = report.results.overlap_bands
    if bands is None:
        return []
    return [
        f"## By word overlap @{bands.cutoff}",
        "",
        f"Questions below vs at-or-above the median overlap ({bands.threshold:.2f}) between "
        "the question's words and its evidence text.",
        "",
        *_metric_table(bands.groups, bands.cutoff, [n for n in _BANDS if n in bands.groups]),
        "",
    ]


def _latency_section(report: RunReport) -> list[str]:
    lines = [
        f"## Latency (search service, ms, {len(report.results.questions)} queries)",
        "",
        "| stage | p50 | p95 |",
        "|---|---|---|",
    ]
    for stage, values in report.results.latency_ms.items():
        lines.append(f"| {stage} | {values.p50:.1f} | {values.p95:.1f} |")
    return [*lines, ""]


def _unanswerable_section(questions: Sequence[QuestionRecord]) -> list[str]:
    unanswerable = [_top_score(q) for q in questions if not q.answerable]
    answerable = [_top_score(q) for q in questions if q.answerable]
    if not unanswerable or not answerable:
        return []
    return [
        "## Top-1 similarity (input for abstention, task 009)",
        "",
        "| questions | n | mean | min | max |",
        "|---|---|---|---|---|",
        _score_row("answerable", answerable),
        _score_row("unanswerable", unanswerable),
        "",
    ]


def _top_score(question: QuestionRecord) -> float:
    return question.hits[0].score if question.hits else 0.0


def _score_row(label: str, scores: Sequence[float]) -> str:
    values = f"{fmean(scores):.3f} | {min(scores):.3f} | {max(scores):.3f}"
    return f"| {label} | {len(scores)} | {values} |"


def _misses_section(report: RunReport) -> list[str]:
    """Questions with no evidence in the top k. Dev only: a test failure list invites tuning."""
    k = max(report.results.metrics)
    misses = [
        q for q in report.results.questions if q.scores is not None and q.scores[k].recall == 0
    ]
    lines = [f"## Misses: nothing relevant in the top {k} ({len(misses)})", ""]
    if not misses:
        return [*lines, "None.", ""]
    lines += ["| id | query_type | question | top hits |", "|---|---|---|---|"]
    for question in misses:
        top = ", ".join(f"`{h.slug}@{h.version}`" for h in question.hits[:MISS_HITS_SHOWN])
        lines.append(f"| {question.id} | {question.query_type} | {question.question} | {top} |")
    return [*lines, ""]


# --- Comparison -------------------------------------------------------------------------


def paired_bootstrap_ci(
    deltas: Sequence[float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Percentile bootstrap interval for the mean of per-question differences.

    Resampling questions (not runs) keeps each question's pair together, so the interval
    reflects how consistently one configuration beats the other on the same questions.
    """
    generator = random.Random(seed)
    means = sorted(fmean(generator.choices(deltas, k=len(deltas))) for _ in range(resamples))
    tail = (1 - confidence) / 2
    return means[int(tail * resamples)], means[int((1 - tail) * resamples) - 1]


def win_tie_loss(deltas: Sequence[float]) -> tuple[int, int, int]:
    wins = sum(1 for delta in deltas if delta > TIE_TOLERANCE)
    losses = sum(1 for delta in deltas if delta < -TIE_TOLERANCE)
    return wins, len(deltas) - wins - losses, losses


def render_comparison(base: RunReport, candidate: RunReport) -> str:
    pairs = _paired_questions(base, candidate)
    lines = [
        f"# `{candidate.header.run_name}` vs `{base.header.run_name}`",
        "",
        f"Dataset {base.header.dataset.name}, split `{base.header.dataset.split}`, "
        f"sha256 `{base.header.dataset.sha256}`. Deltas are candidate minus base.",
        "",
    ]
    for k in base.results.metrics:
        lines += [f"## Deltas @{k}", "", *_delta_table(base, candidate, k), ""]
    lines += _paired_section(pairs, base, candidate)
    return "\n".join(lines)


def _paired_questions(
    base: RunReport, candidate: RunReport
) -> list[tuple[QuestionRecord, QuestionRecord]]:
    if base.header.dataset != candidate.header.dataset:
        raise ComparisonError("Runs used different datasets or splits")
    if base.header.config.cutoffs != candidate.header.config.cutoffs:
        raise ComparisonError("Runs used different metric cutoffs")
    candidate_by_id = {question.id: question for question in candidate.results.questions}
    if candidate_by_id.keys() != {question.id for question in base.results.questions}:
        raise ComparisonError("Runs scored different questions")
    return [(question, candidate_by_id[question.id]) for question in base.results.questions]


def _delta_table(base: RunReport, candidate: RunReport, k: int) -> list[str]:
    base_rows, candidate_rows = base.results.metrics[k], candidate.results.metrics[k]
    columns = " | ".join(f"{label}@{k}" for label, _ in _METRICS)
    lines = [f"| query_type | n | {columns} |", "|---|---|" + "---|" * len(_METRICS)]
    for name in _row_order(base_rows):
        cells = " | ".join(
            _delta_cell(getattr(base_rows[name], field), getattr(candidate_rows[name], field))
            for _, field in _METRICS
        )
        label = f"**{name}**" if name == "all" else name
        lines.append(f"| {label} | {base_rows[name].count} | {cells} |")
    return lines


def _delta_cell(base_value: float, candidate_value: float) -> str:
    return f"{base_value:.3f} → {candidate_value:.3f} ({candidate_value - base_value:+.3f})"


def _paired_section(
    pairs: Sequence[tuple[QuestionRecord, QuestionRecord]], base: RunReport, candidate: RunReport
) -> list[str]:
    scored = [(b, c) for b, c in pairs if b.scores is not None and c.scores is not None]
    cutoffs = list(base.results.metrics)
    primary = [("R", "recall", cutoffs[0]), ("MRR", "reciprocal_rank", cutoffs[-1])]
    primary.append(("nDCG", "ndcg", cutoffs[-1]))
    lines = [
        f"## Per-question differences ({len(scored)} answerable questions)",
        "",
        f"95 % paired bootstrap interval of the mean delta ({BOOTSTRAP_RESAMPLES} resamples, "
        f"seed {BOOTSTRAP_SEED}). An interval that contains 0 is not a demonstrated difference.",
        "",
        "| metric | mean delta | 95 % CI | wins / ties / losses |",
        "|---|---|---|---|",
    ]
    for label, field, k in primary:
        deltas = [getattr(c.scores[k], field) - getattr(b.scores[k], field) for b, c in scored]
        low, high = paired_bootstrap_ci(deltas)
        wins, ties, losses = win_tie_loss(deltas)
        lines.append(
            f"| {label}@{k} | {fmean(deltas):+.3f} | [{low:+.3f}, {high:+.3f}] "
            f"| {wins} / {ties} / {losses} |"
        )
    lines += ["", f"Candidate: `{candidate.header.config.model_dump_json()}`", ""]
    return lines
