"""Markdown for answer runs, and the judge spot-check sheet. Rendered from the JSON record."""

import random
from collections.abc import Sequence

from app.evaluation.answer_metrics import (
    AnswerSummary,
    GatePoint,
    choose_gate,
    gate_sweep,
    has_context_hit,
    is_abstained,
    summarise_answers,
)
from app.evaluation.answer_records import AnswerRecord, AnswerRunReport
from app.evaluation.dataset import BuiltQuestion
from app.evaluation.runner import percentile

SPOT_CHECK_SIZE = 20
SPOT_CHECK_SEED = "evidencedesk-judge-check"
_VERDICTS = {
    "correctness": ("correct", "partial", "incorrect", "unjudged"),
    "faithfulness": ("supported", "partially_supported", "unsupported", "unjudged"),
}


def render_answer_run(report: AnswerRunReport, gate: float | None = None) -> str:
    """`gate`: a threshold chosen elsewhere (dev), reported with and without it (test)."""
    summaries = summarise_answers(report.records)
    lines = _header(report)
    lines += ["## Outcomes", "", *_outcome_table(summaries), ""]
    lines += ["## Citations and context", "", *_citation_table(summaries), ""]
    lines += _judged_section(report, summaries)
    lines += _cost_section(report.records)
    lines += _gate_section(report.records, gate)
    if report.header.dataset.split == "dev":
        lines += _failure_lists(report.records)
    return "\n".join(lines)


def _header(report: AnswerRunReport) -> list[str]:
    header = report.header
    generator = header.generator
    agreement = header.judge_agreement
    lines = [
        f"# Answer run `{header.run_name}`",
        "",
        f"- **Dataset:** {header.dataset.name}, split `{header.dataset.split}`, "
        f"sha256 `{header.dataset.sha256}`",
        f"- **Config:** `{header.config.model_dump_json()}`",
        f"- **Generator:** `{generator.model}`, {generator.context_chunks} context chunks, "
        f"rerank depth {generator.rerank_depth}, chunker `{generator.chunker or 'unrecorded'}`, "
        f"gate during run: {generator.min_rerank_score}",
        f"- **Judge:** `{header.judge_model or 'not judged'}`"
        + (f", human agreement {agreement.agreed}/{agreement.checked}" if agreement else ""),
        f"- **Corpus:** {header.corpus_documents} documents verified",
        f"- **Git:** `{header.git.sha}`" + (" (uncommitted changes)" if header.git.dirty else ""),
        f"- **Environment:** {', '.join(f'{k} {v}' for k, v in header.environment.items())}",
        f"- **Created:** {header.created_at.isoformat(timespec='seconds')}",
        "",
    ]
    if header.dataset.split == "test":
        lines += ["> Test split: a final comparison run. Do not tune on these numbers.", ""]
    return lines


def _order(summaries: dict[str, AnswerSummary]) -> list[str]:
    return ["all", *sorted(name for name in summaries if name != "all")]


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.0%}"


def _outcome_table(summaries: dict[str, AnswerSummary]) -> list[str]:
    lines = [
        "| query_type | n | answered (answerable) | correct abstention (unanswerable) "
        "| false abstention: retrieval / generation | errors |",
        "|---|---|---|---|---|---|",
    ]
    for name in _order(summaries):
        s = summaries[name]
        lines.append(
            f"| {name} | {s.count} | {s.answered_answerable}/{s.answerable} {_pct(s.answer_rate)} "
            f"| {s.abstained_unanswerable}/{s.unanswerable} {_pct(s.correct_abstention)} "
            f"| {s.false_abstention_retrieval} / {s.false_abstention_generation} | {s.errors} |"
        )
    return lines


def _citation_table(summaries: dict[str, AnswerSummary]) -> list[str]:
    lines = [
        "Answerable questions that were answered. Precision: cited chunks overlapping labelled "
        "evidence. Coverage: evidence items cited. Context hit: evidence in the 5 context chunks "
        "(all answerable questions).",
        "",
        "| query_type | citations | citation precision | evidence coverage | context hit |",
        "|---|---|---|---|---|",
    ]
    for name in _order(summaries):
        s = summaries[name]
        lines.append(
            f"| {name} | {s.citations} | {_pct(s.citation_precision)} "
            f"| {_pct(s.evidence_coverage)} | {_pct(s.context_hit)} |"
        )
    return lines


def _judged_section(report: AnswerRunReport, summaries: dict[str, AnswerSummary]) -> list[str]:
    if not report.header.judge_model:
        return []
    agreement = report.header.judge_agreement
    checked = f"{agreement.agreed}/{agreement.checked}" if agreement else "not yet checked"
    lines = [
        f"## LLM-judged (judge `{report.header.judge_model}`; human agreement {checked})",
        "",
        "Correctness: answered answerable questions vs the reference answer. Faithfulness: "
        "every answer vs the passages it cited.",
        "",
    ]
    for criterion, verdicts in _VERDICTS.items():
        lines += [
            f"| {criterion} | " + " | ".join(verdicts) + " |",
            "|---" * (len(verdicts) + 1) + "|",
        ]
        for name in _order(summaries):
            counts = summaries[name].judged.get(criterion, {})
            lines.append(
                f"| {name} | " + " | ".join(str(counts.get(v, 0)) for v in verdicts) + " |"
            )
        lines.append("")
    return lines


def _cost_section(records: Sequence[AnswerRecord]) -> list[str]:
    totals = [r.latency_ms["total"] for r in records if "total" in r.latency_ms]
    llm = [r.latency_ms["llm"] for r in records if r.llm_calls]
    lines = [
        "## Cost and latency",
        "",
        f"- LLM calls: {sum(r.llm_calls for r in records)} for {len(records)} questions",
        f"- Tokens: {sum(r.prompt_tokens for r in records)} prompt, "
        f"{sum(r.completion_tokens for r in records)} completion",
    ]
    if totals:
        lines.append(f"- Total latency {_p50_p95(totals)}")
    if llm:
        lines.append(f"- LLM latency {_p50_p95(llm)}")
    return [*lines, ""]


def _gate_section(records: Sequence[AnswerRecord], gate: float | None) -> list[str]:
    if gate is not None:
        return _gate_comparison(records, gate)
    decision = choose_gate(gate_sweep(records))
    best = decision.best
    return [
        "## Abstention gate (sweep; rule fixed in task 009b)",
        "",
        "Abstain if the model abstains or the top cross-encoder score is below t. "
        "J = correct abstention (unanswerable) − false abstention (answerable). "
        "Adopt only if J improves by ≥ 0.10.",
        "",
        f"- No gate: {_gate_point(decision.baseline)}",
        f"- Best t = {best.threshold}: {_gate_point(best)}",
        f"- Gain {decision.gain:+.2f} → **{'adopt' if decision.adopted else 'do not adopt'}**",
        "",
    ]


def _gate_point(point: GatePoint) -> str:
    return (
        f"J {point.j:+.2f} (correct {point.correct_abstention:.0%}, "
        f"false {point.false_abstention:.0%})"
    )


def _p50_p95(values: Sequence[float]) -> str:
    return f"p50 {percentile(values, 0.5):.0f} ms, p95 {percentile(values, 0.95):.0f} ms"


def _gate_comparison(records: Sequence[AnswerRecord], gate: float) -> list[str]:
    lines = [
        f"## With and without the dev-chosen gate (t = {gate})",
        "",
        "| | answered (answerable) | correct abstention | false abstention |",
        "|---|---|---|---|",
    ]
    for label, threshold in (("no gate", None), (f"gate t = {gate}", gate)):
        s = summarise_answers(records, threshold)["all"]
        lines.append(
            f"| {label} | {_pct(s.answer_rate)} | {_pct(s.correct_abstention)} "
            f"| {_pct(s.false_abstention)} |"
        )
    return [*lines, ""]


def _failure_lists(records: Sequence[AnswerRecord]) -> list[str]:
    """Dev only: listing test failures would invite tuning to test."""
    answered_unanswerable = [r for r in records if not r.answerable and r.outcome == "answered"]
    generation = [r for r in records if r.answerable and is_abstained(r) and has_context_hit(r)]
    lines = ["## Answered although unanswerable (hallucination candidates)", ""]
    lines += [f"- {r.id}: {r.question}" for r in answered_unanswerable] or ["None."]
    lines += ["", "## Abstained although the evidence was in the context", ""]
    lines += [f"- {r.id} ({r.query_type}): {r.question}" for r in generation] or ["None."]
    return [*lines, ""]


# --- Judge spot-check -----------------------------------------------------------------------


def render_spot_check(report: AnswerRunReport, questions: dict[str, BuiltQuestion]) -> str:
    """A fixed random sample of judged answers for a human to agree or disagree with."""
    judged = [
        r for r in report.records if any(j.verdict != "unjudged" for j in r.judgments.values())
    ]
    sample = random.Random(SPOT_CHECK_SEED).sample(judged, min(SPOT_CHECK_SIZE, len(judged)))
    lines = [
        f"# Judge spot-check: {report.header.run_name} ({len(sample)} answers)",
        "",
        "For each id, reply with the criteria you disagree with (or 'all agree').",
        "",
    ]
    for record in sorted(sample, key=lambda r: r.id):
        reference = questions[record.id].reference_answer or "— (unanswerable)"
        lines += [
            f"## {record.id} · {record.query_type}",
            "",
            f"**Q:** {record.question}",
            "",
            f"**Reference:** {reference}",
            "",
            f"**Answer:** {record.answer}",
            "",
            "**Cited:** " + ", ".join(f"`{c.slug}@{c.version}`" for c in record.citations),
            "",
        ]
        lines += [
            f"- **{criterion}: {j.verdict}** — {j.reason}"
            for criterion, j in record.judgments.items()
        ]
        lines += ["", "---", ""]
    return "\n".join(lines)
