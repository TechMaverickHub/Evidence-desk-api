"""Answer runs: records, resume after interruption, refusal to mix runs, pacing."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.core.errors import (
    LLMNotConfiguredError,
    LLMQuotaExceededError,
    LLMUnavailableError,
)
from app.evaluation.answer_records import AnswerRunConfig
from app.evaluation.answer_runner import AnswerDeps, Pacer, run_answers
from app.evaluation.dataset import Dataset
from app.evaluation.runner import RunError
from app.generation.prompts import load_prompts
from tests.fakes import FakeEmbedder, FakeReranker, ScriptedLLMClient

CONFIG = AnswerRunConfig(name="t")
KEY = {"config": CONFIG.model_dump(), "dataset": "sha", "split": "all"}
ANSWER = json.dumps({"status": "answered", "answer": "Yes.", "citations": [1]})


def _no_pace() -> None:
    pass


def _deps(llm: ScriptedLLMClient) -> AnswerDeps:
    return AnswerDeps(FakeEmbedder(), lambda: FakeReranker(), llm, load_prompts())


@pytest.fixture
def tenant(make_tenant: Callable[..., Tenant], load_fixture_corpus: Callable) -> Tenant:
    tenant = make_tenant()
    load_fixture_corpus(tenant)
    return tenant


def test_every_question_is_recorded_with_its_evidence_matches(
    db_session: Session, tenant: Tenant, mini_dataset: Dataset, tmp_path: Path
) -> None:
    questions = mini_dataset.questions
    llm = ScriptedLLMClient(*[ANSWER] * len(questions))

    records = run_answers(
        db_session,
        tenant.id,
        questions,
        CONFIG,
        _deps(llm),
        tmp_path / "p.jsonl",
        KEY,
        lambda: None,
    )

    assert [record.id for record in records] == [question.id for question in questions]
    assert all(record.outcome == "answered" for record in records)
    assert len(records[0].context) >= 1
    assert records[0].evidence_items == 1
    unanswerable = next(record for record in records if not record.answerable)
    # Answering an unanswerable question is recorded as is; metrics flag it later.
    assert unanswerable.citations[0].matched_items == []
    assert records[0].top_score is not None


def test_a_rerun_only_pays_for_unfinished_or_failed_questions(
    db_session: Session, tenant: Tenant, mini_dataset: Dataset, tmp_path: Path
) -> None:
    questions = mini_dataset.questions
    partial = tmp_path / "p.jsonl"
    first = ScriptedLLMClient(ANSWER, ANSWER, LLMUnavailableError(), ANSWER, ANSWER)

    records = run_answers(
        db_session, tenant.id, questions, CONFIG, _deps(first), partial, KEY, lambda: None
    )

    assert [record.outcome for record in records].count("error") == 1
    assert records[2].error_code == "LLM_UNAVAILABLE"
    second = ScriptedLLMClient(ANSWER)
    rerun = run_answers(
        db_session, tenant.id, questions, CONFIG, _deps(second), partial, KEY, lambda: None
    )
    assert len(second.calls) == 1
    assert all(record.outcome == "answered" for record in rerun)


def test_a_partial_file_from_another_run_is_refused(
    db_session: Session, tenant: Tenant, mini_dataset: Dataset, tmp_path: Path
) -> None:
    partial = tmp_path / "p.jsonl"
    partial.write_text(json.dumps({"run_key": {**KEY, "split": "dev"}}) + "\n", encoding="utf-8")

    with pytest.raises(RunError, match="different run"):
        run_answers(
            db_session, tenant.id, mini_dataset.questions, CONFIG,
            _deps(ScriptedLLMClient()), partial, KEY, lambda: None,
        )  # fmt: skip


def test_the_pacer_keeps_the_minimum_interval() -> None:
    now = [100.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    pace = Pacer(2.0, clock=lambda: now[0], sleep=sleep)
    pace()
    now[0] += 0.5
    pace()
    now[0] += 5.0
    pace()

    assert slept == [1.5]


def test_a_daily_quota_stops_the_run_and_keeps_the_answers(
    db_session: Session, tenant: Tenant, mini_dataset: Dataset, tmp_path: Path
) -> None:
    questions = mini_dataset.questions
    partial = tmp_path / "p.jsonl"
    llm = ScriptedLLMClient(ANSWER, ANSWER, LLMQuotaExceededError(retry_after_seconds=191))

    with pytest.raises(RunError) as raised:
        run_answers(db_session, tenant.id, questions, CONFIG, _deps(llm), partial, KEY, _no_pace)

    message = str(raised.value)
    assert "LLM_QUOTA_EXCEEDED" in message
    assert f"2/{len(questions)} done" in message
    assert "rerun the same command after about 4 min" in message
    resumed = ScriptedLLMClient(*[ANSWER] * (len(questions) - 2))
    run_answers(db_session, tenant.id, questions, CONFIG, _deps(resumed), partial, KEY, _no_pace)
    assert len(resumed.calls) == len(questions) - 2


def test_a_configuration_error_stops_the_run_with_an_operator_hint(
    db_session: Session, tenant: Tenant, mini_dataset: Dataset, tmp_path: Path
) -> None:
    llm = ScriptedLLMClient(LLMNotConfiguredError())

    with pytest.raises(RunError, match="fix the LLM configuration, then rerun"):
        run_answers(
            db_session, tenant.id, mini_dataset.questions, CONFIG, _deps(llm),
            tmp_path / "p.jsonl", KEY, lambda: None,
        )  # fmt: skip
