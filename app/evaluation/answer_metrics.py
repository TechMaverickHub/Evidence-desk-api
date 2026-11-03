"""Deterministic answer metrics and the abstention-gate sweep, computed from answer records.

Pure functions of `AnswerRecord`s: no model, no database. LLM-judged verdicts are only
counted here, never turned into the deterministic numbers.
"""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.evaluation.answer_records import AnswerRecord

# Adopt a gate only if it improves J by at least this much (task 009b, fixed in advance):
# with 10 unanswerable dev questions, one extra correct abstention is 0.10.
MIN_GATE_GAIN = 0.10


@dataclass(frozen=True)
class AnswerSummary:
    count: int
    errors: int
    answerable: int
    unanswerable: int
    answered_answerable: int
    abstained_unanswerable: int
    # Answerable but abstained, by cause: evidence never reached the context, or it did.
    false_abstention_retrieval: int
    false_abstention_generation: int
    citations: int
    citations_on_evidence: int
    context_hits: int
    coverage_sum: float
    judged: dict[str, Counter] = field(default_factory=dict)

    @property
    def answer_rate(self) -> float | None:
        return _rate(self.answered_answerable, self.answerable)

    @property
    def correct_abstention(self) -> float | None:
        return _rate(self.abstained_unanswerable, self.unanswerable)

    @property
    def false_abstention(self) -> float | None:
        abstained = self.false_abstention_retrieval + self.false_abstention_generation
        return _rate(abstained, self.answerable)

    @property
    def citation_precision(self) -> float | None:
        return _rate(self.citations_on_evidence, self.citations)

    @property
    def evidence_coverage(self) -> float | None:
        """Mean share of a question's evidence items its citations cover (answered only)."""
        return _rate(self.coverage_sum, self.answered_answerable)

    @property
    def context_hit(self) -> float | None:
        return _rate(self.context_hits, self.answerable)


def is_abstained(record: AnswerRecord, threshold: float | None = None) -> bool:
    """The model abstained, or (simulated) the gate would have: top score below threshold."""
    if record.outcome == "insufficient_evidence":
        return True
    if threshold is None:
        return False
    return record.top_score is None or record.top_score < threshold


def has_context_hit(record: AnswerRecord) -> bool:
    return any(chunk.matched_items for chunk in record.context)


def summarise_answers(
    records: Sequence[AnswerRecord], threshold: float | None = None
) -> dict[str, AnswerSummary]:
    """Key "all" plus one key per query type. Errors are counted, not scored."""
    groups: dict[str, list[AnswerRecord]] = defaultdict(list)
    for record in records:
        groups["all"].append(record)
        groups[record.query_type].append(record)
    return {name: _summarise(group, threshold) for name, group in groups.items()}


def _summarise(records: Sequence[AnswerRecord], threshold: float | None) -> AnswerSummary:
    scored = [record for record in records if record.outcome != "error"]
    answerable = [record for record in scored if record.answerable]
    unanswerable = [record for record in scored if not record.answerable]
    answered = [record for record in answerable if not is_abstained(record, threshold)]
    false_abstentions = [record for record in answerable if is_abstained(record, threshold)]
    cited = [chunk for record in answered for chunk in record.citations]
    judged: dict[str, Counter] = defaultdict(Counter)
    for record in scored:
        for criterion, judgment in record.judgments.items():
            judged[criterion][judgment.verdict] += 1
    return AnswerSummary(
        count=len(records),
        errors=len(records) - len(scored),
        answerable=len(answerable),
        unanswerable=len(unanswerable),
        answered_answerable=len(answered),
        abstained_unanswerable=sum(is_abstained(record, threshold) for record in unanswerable),
        false_abstention_retrieval=sum(not has_context_hit(r) for r in false_abstentions),
        false_abstention_generation=sum(has_context_hit(r) for r in false_abstentions),
        citations=len(cited),
        citations_on_evidence=sum(bool(chunk.matched_items) for chunk in cited),
        context_hits=sum(has_context_hit(record) for record in answerable),
        coverage_sum=sum(_coverage(record) for record in answered),
        judged=dict(judged),
    )


def _coverage(record: AnswerRecord) -> float:
    covered = {item for chunk in record.citations for item in chunk.matched_items}
    return len(covered) / record.evidence_items


def _rate(numerator: float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


# --- Abstention gate -----------------------------------------------------------------------


@dataclass(frozen=True)
class GatePoint:
    threshold: float | None
    correct_abstention: float
    false_abstention: float

    @property
    def j(self) -> float:
        """Youden's J for abstaining: correct abstentions minus false abstentions."""
        return self.correct_abstention - self.false_abstention


@dataclass(frozen=True)
class GateDecision:
    baseline: GatePoint
    best: GatePoint
    adopted: bool

    @property
    def gain(self) -> float:
        return self.best.j - self.baseline.j


def gate_sweep(records: Sequence[AnswerRecord]) -> list[GatePoint]:
    """No gate, then every observed top score as a candidate threshold (ascending).

    The gate acts before the LLM, so recorded runs can be swept without new calls.
    """
    scored = [record for record in records if record.outcome != "error"]
    candidates = sorted({r.top_score for r in scored if r.top_score is not None})
    return [_gate_point(scored, threshold) for threshold in [None, *candidates]]


def choose_gate(sweep: Sequence[GatePoint], min_gain: float = MIN_GATE_GAIN) -> GateDecision:
    """Best J; ties go to the lowest threshold (fewest questions gated). Adopt only on a
    real gain, so noise from a handful of questions doesn't change behaviour."""
    baseline = sweep[0]
    best = baseline
    for point in sweep[1:]:
        if point.j > best.j:
            best = point
    # The tolerance keeps a gain of exactly one question (e.g. 0.3 - 0.2) from failing on
    # float rounding.
    return GateDecision(baseline, best, adopted=best.j - baseline.j >= min_gain - 1e-9)


def _gate_point(records: Sequence[AnswerRecord], threshold: float | None) -> GatePoint:
    answerable = [record for record in records if record.answerable]
    unanswerable = [record for record in records if not record.answerable]
    return GatePoint(
        threshold=threshold,
        correct_abstention=_abstention_rate(unanswerable, threshold),
        false_abstention=_abstention_rate(answerable, threshold),
    )


def _abstention_rate(records: Sequence[AnswerRecord], threshold: float | None) -> float:
    abstained = sum(is_abstained(record, threshold) for record in records)
    return _rate(abstained, len(records)) or 0.0
