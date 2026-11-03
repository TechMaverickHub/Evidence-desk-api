"""The judge: which records get which criteria, verdict parsing, retry, cited-only context."""

import json
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.documents.models import DocumentChunk
from app.evaluation.answer_records import (
    AnswerRecord,
    AnswerRunConfig,
    AnswerRunHeader,
    AnswerRunReport,
    GeneratorSettings,
    Judgment,
    SpanRef,
)
from app.evaluation.dataset import Dataset
from app.evaluation.judge import criteria_for, judge_record, judge_run
from app.evaluation.records import DatasetRef, GitState
from app.generation.llm_client import LLMOutputRejectedError
from app.generation.prompts import load_judge_prompts
from tests.fakes import ScriptedLLMClient

PROMPTS = load_judge_prompts()


def _verdict(verdict: str, reason: str = "ok") -> str:
    return json.dumps({"verdict": verdict, "reason": reason})


def _record(outcome: str = "answered", answerable: bool = True, **fields: object) -> AnswerRecord:
    values: dict[str, object] = {
        "id": "q-0001",
        "query_type": "factual",
        "question": "How many times is it called?",
        "answerable": answerable,
        "evidence_items": 1,
        "outcome": outcome,
        "answer": "Once.",
        "citations": [],
        "context": [],
        "top_score": 1.0,
        "llm_calls": 1,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "latency_ms": {},
    }
    values.update(fields)
    return AnswerRecord.model_validate(values)


def test_only_answers_are_graded_and_correctness_needs_a_reference() -> None:
    assert criteria_for(_record()) == ["correctness", "faithfulness"]
    assert criteria_for(_record(answerable=False)) == ["faithfulness"]
    assert criteria_for(_record("insufficient_evidence")) == []
    assert criteria_for(_record("error")) == []


def test_verdicts_are_parsed_and_long_reasons_cut() -> None:
    llm = ScriptedLLMClient(_verdict("correct", "x" * 500), _verdict("supported"))

    judgments = judge_record(llm, PROMPTS, _record(), "Once per request.", ["called once"])

    assert judgments["correctness"].verdict == "correct"
    assert len(judgments["correctness"].reason) == 200
    assert judgments["faithfulness"].verdict == "supported"
    assert "Once per request." in llm.calls[0][1]["content"]


def test_an_invalid_verdict_is_retried_once_then_left_unjudged() -> None:
    llm = ScriptedLLMClient(
        "not json", _verdict("partial"),  # correctness: second try succeeds
        _verdict("maybe"), LLMOutputRejectedError("400"),  # faithfulness: both invalid
    )  # fmt: skip

    judgments = judge_record(llm, PROMPTS, _record(), "ref", ["text"])

    assert judgments["correctness"].verdict == "partial"
    assert judgments["faithfulness"].verdict == "unjudged"
    assert len(llm.calls) == 4


def test_existing_verdicts_are_not_paid_for_again() -> None:
    done = {"correctness": Judgment(verdict="correct", reason="")}
    llm = ScriptedLLMClient(_verdict("supported"))

    judgments = judge_record(llm, PROMPTS, _record(judgments=done), "ref", ["text"])

    assert set(judgments) == {"faithfulness"}
    assert len(llm.calls) == 1


def test_faithfulness_sees_only_the_cited_passages(
    db_session: Session,
    make_tenant: Callable[..., Tenant],
    load_fixture_corpus: Callable,
    mini_dataset: Dataset,
) -> None:
    tenant = make_tenant()
    load_fixture_corpus(tenant)
    cited, other = db_session.scalars(
        select(DocumentChunk).where(DocumentChunk.tenant_id == tenant.id).limit(2)
    ).all()

    def ref(chunk: DocumentChunk) -> SpanRef:
        return SpanRef(chunk_id=str(chunk.id), slug="s", version="1", char_start=0,
                       char_end=1, matched_items=[])  # fmt: skip

    record = _record(answerable=False, citations=[ref(cited)], context=[ref(cited), ref(other)])
    report = AnswerRunReport(
        header=AnswerRunHeader(
            run_name="r",
            created_at=datetime.now(UTC),
            dataset=DatasetRef(name="mini", sha256="x", split="dev"),
            config=AnswerRunConfig(name="t"),
            generator=GeneratorSettings(
                model="m", context_chunks=5, rerank_depth=20, min_rerank_score=None
            ),  # fmt: skip
            git=GitState(sha="x", dirty=False),
            environment={},
            corpus_documents=2,
        ),
        records=[record],
    )
    llm = ScriptedLLMClient(_verdict("unsupported"))
    saved: list[int] = []

    judge_run(
        db_session, tenant.id, report, {q.id: q for q in mini_dataset.questions},
        llm, PROMPTS, lambda: None, lambda r: saved.append(1),
    )  # fmt: skip

    prompt = llm.calls[0][1]["content"]
    assert cited.text in prompt
    assert other.text not in prompt
    assert report.records[0].judgments["faithfulness"].verdict == "unsupported"
    assert report.header.judge_model == "fake-llm"
    assert saved == [1]
