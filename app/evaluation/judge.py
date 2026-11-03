"""LLM-judged answer quality: correctness against the reference, faithfulness to citations.

Verdicts are strict-schema JSON from a separate judge model, retried once if invalid and
otherwise recorded as "unjudged", never guessed. They sit next to the deterministic
metrics and are never used to tune anything.
"""

import json
import uuid
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.evaluation import repository
from app.evaluation.answer_records import AnswerRecord, AnswerRunReport, Criterion, Judgment
from app.evaluation.dataset import BuiltQuestion
from app.generation.llm_client import LLMClient, LLMOutputRejectedError, Messages
from app.generation.prompts import JudgePrompts
from app.generation.schemas import strict_json_schema

MAX_REASON_CHARS = 200
UNJUDGED = "unjudged"


class CorrectnessVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["correct", "partial", "incorrect"]
    reason: str


class FaithfulnessVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["supported", "partially_supported", "unsupported"]
    reason: str


_VERDICT_MODELS: dict[Criterion, type[BaseModel]] = {
    "correctness": CorrectnessVerdict,
    "faithfulness": FaithfulnessVerdict,
}


def criteria_for(record: AnswerRecord) -> list[Criterion]:
    """Only answered questions are graded. Correctness needs a reference answer, so it
    applies to answerable questions; faithfulness applies to every answer, including
    answers to unanswerable questions (where it catches hallucination)."""
    if record.outcome != "answered":
        return []
    return ["correctness", "faithfulness"] if record.answerable else ["faithfulness"]


def judge_record(
    llm: LLMClient,
    prompts: JudgePrompts,
    record: AnswerRecord,
    reference: str | None,
    cited_texts: list[str],
) -> dict[Criterion, Judgment]:
    """Verdicts for the criteria this record still lacks."""
    judgments: dict[Criterion, Judgment] = {}
    for criterion in criteria_for(record):
        if criterion in record.judgments:
            continue
        user = _user_message(prompts, criterion, record, reference, cited_texts)
        messages = [
            {"role": "system", "content": prompts.judge_system},
            {"role": "user", "content": user},
        ]
        judgments[criterion] = _verdict(llm, messages, _VERDICT_MODELS[criterion])
    return judgments


def judge_run(
    session: Session,
    tenant_id: uuid.UUID,
    report: AnswerRunReport,
    questions: dict[str, BuiltQuestion],
    llm: LLMClient,
    prompts: JudgePrompts,
    pace: Callable[[], None],
    save: Callable[[AnswerRunReport], None],
) -> AnswerRunReport:
    """Judge every record still missing a verdict; saves after each, so it can resume.
    A provider outage (LLMUnavailableError) stops the run; rerunning continues from there."""
    report.header.judge_model = llm.model_name
    for record in report.records:
        if all(criterion in record.judgments for criterion in criteria_for(record)):
            continue
        texts = _cited_texts(session, tenant_id, record)
        pace()
        record.judgments |= judge_record(
            llm, prompts, record, questions[record.id].reference_answer, texts
        )
        save(report)
    return report


def _user_message(
    prompts: JudgePrompts,
    criterion: Criterion,
    record: AnswerRecord,
    reference: str | None,
    cited_texts: list[str],
) -> str:
    if criterion == "correctness":
        return prompts.correctness_message(record.question, reference or "", record.answer)
    # Faithfulness sees only the passages the answer cited, never the rest of the context.
    passages = "\n\n".join(f"[{n}] {text}" for n, text in enumerate(cited_texts, start=1))
    return prompts.faithfulness_message(record.answer, passages)


def _verdict(llm: LLMClient, messages: Messages, model: type[BaseModel]) -> Judgment:
    for _attempt in range(2):
        try:
            reply = llm.complete_json(
                messages, strict_json_schema(model), f"judge_{model.__name__}"
            )
            parsed = model.model_validate(json.loads(reply.content))
        except (LLMOutputRejectedError, json.JSONDecodeError, ValidationError):
            continue
        return Judgment(verdict=parsed.verdict, reason=parsed.reason[:MAX_REASON_CHARS])
    return Judgment(verdict=UNJUDGED, reason="the judge's reply was invalid twice")


def _cited_texts(session: Session, tenant_id: uuid.UUID, record: AnswerRecord) -> list[str]:
    chunk_ids = [uuid.UUID(citation.chunk_id) for citation in record.citations]
    chunks = repository.chunks_by_id(session, tenant_id, chunk_ids)
    return [chunks[chunk_id].text for chunk_id in chunk_ids if chunk_id in chunks]
