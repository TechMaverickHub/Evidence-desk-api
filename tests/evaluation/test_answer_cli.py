"""answer-run / answer-judge / answer-report end to end, with fakes instead of Groq."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.evaluation import answer_cli, cli
from app.evaluation.answer_records import AnswerRunReport
from app.evaluation.answer_runner import AnswerDeps
from app.evaluation.dataset import Dataset, write_dataset
from app.generation.prompts import load_prompts
from tests.evaluation.conftest import MANIFEST
from tests.fakes import FakeEmbedder, FakeReranker, ScriptedLLMClient

ANSWER = json.dumps({"status": "answered", "answer": "Yes.", "citations": [1]})


def _verdict(verdict: str) -> str:
    return json.dumps({"verdict": verdict, "reason": "r"})


@pytest.fixture
def setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    make_tenant: Callable[..., Tenant],
    load_fixture_corpus: Callable[[Tenant], None],
    mini_dataset: Dataset,
) -> dict:
    tenant = make_tenant("answers-fixture")
    load_fixture_corpus(tenant)
    monkeypatch.setattr(answer_cli, "get_sessionmaker", lambda: lambda: db_session)
    dataset = tmp_path / "mini.jsonl"
    write_dataset(mini_dataset, dataset)
    config = tmp_path / "answers.yaml"
    config.write_text("name: fx\n", encoding="utf-8")
    split = mini_dataset.questions[0].split
    count = sum(1 for q in mini_dataset.questions if q.split == split)
    llm = ScriptedLLMClient(*[ANSWER] * count)
    deps = AnswerDeps(FakeEmbedder(), lambda: FakeReranker(), llm, load_prompts())
    monkeypatch.setattr(answer_cli, "build_answer_deps", lambda: deps)
    return {"tenant": tenant.name, "dataset": str(dataset), "config": str(config),
            "out": tmp_path / "reports", "split": split, "count": count}  # fmt: skip


def _run_args(setup: dict, split: str) -> list[str]:
    return [
        "answer-run", "--config", setup["config"], "--dataset", setup["dataset"],
        "--split", split, "--tenant", setup["tenant"], "--manifest", str(MANIFEST),
        "--out-dir", str(setup["out"]), "--pace", "0",
    ]  # fmt: skip


def test_answer_run_on_test_needs_allow_test(setup: dict) -> None:
    assert cli.main(_run_args(setup, "test")) == 2
    assert not setup["out"].exists()


def test_run_judge_and_report_end_to_end(setup: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    split = setup["split"]
    allow = ["--allow-test"] if split == "test" else []
    assert cli.main([*_run_args(setup, split), *allow]) == 0

    record_path = setup["out"] / f"answers-fx-{split}.json"
    report = AnswerRunReport.model_validate_json(record_path.read_bytes())
    assert len(report.records) == setup["count"]
    assert not (setup["out"] / f"answers-fx-{split}.partial.jsonl").exists()
    assert "## Outcomes" in record_path.with_suffix(".md").read_text(encoding="utf-8")

    judge = ScriptedLLMClient(*[_verdict("correct"), _verdict("supported")] * setup["count"])
    monkeypatch.setattr(answer_cli, "build_llm", lambda model: judge)
    args = ["answer-judge", str(record_path), "--dataset", setup["dataset"],
            "--tenant", setup["tenant"], "--pace", "0"]  # fmt: skip
    assert cli.main(args) == 0
    judged = AnswerRunReport.model_validate_json(record_path.read_bytes())
    assert judged.header.judge_model == "fake-llm"
    assert any(record.judgments for record in judged.records)

    sheet = setup["out"] / "sheet.md"
    args = ["answer-report", str(record_path), "--dataset", setup["dataset"],
            "--sheet", str(sheet), "--agreement", "3/4", "--gate", "0.5"]  # fmt: skip
    assert cli.main(args) == 0
    markdown = record_path.with_suffix(".md").read_text(encoding="utf-8")
    assert "human agreement 3/4" in markdown
    assert "With and without the dev-chosen gate (t = 0.5)" in markdown
    assert "Judge spot-check" in sheet.read_text(encoding="utf-8")


def test_a_bad_agreement_value_fails_cleanly(setup: dict, capsys: pytest.CaptureFixture) -> None:
    split = setup["split"]
    allow = ["--allow-test"] if split == "test" else []
    cli.main([*_run_args(setup, split), *allow])
    record = str(setup["out"] / f"answers-fx-{split}.json")

    assert cli.main(["answer-report", record, "--agreement", "21/20"]) == 1
    assert "--agreement" in capsys.readouterr().err
