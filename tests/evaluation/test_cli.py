from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.evaluation import cli
from app.evaluation.dataset import Dataset, write_dataset
from app.evaluation.records import RunReport
from tests.fakes import FakeEmbedder, FakeReranker

FIXTURES = Path(__file__).parents[1] / "fixtures"
MANIFEST = FIXTURES / "corpus" / "manifest.yaml"
MINI = FIXTURES / "datasets" / "mini.yaml"


def test_build_then_stats(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "mini-v1.jsonl"
    build_args = ["build-dataset", "--source", str(MINI), "--manifest", str(MANIFEST)]

    assert cli.main([*build_args, "--out", str(out), "--seed", "s"]) == 0
    built_report = capsys.readouterr().out
    assert cli.main(["stats", "--dataset", str(out)]) == 0
    stats_report = capsys.readouterr().out

    assert built_report == stats_report
    assert "mini-v1: 5 questions" in stats_report
    assert "unanswerable" in stats_report
    assert "span chars: n=6" in stats_report


def test_build_problems_exit_non_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "bad.yaml"
    source.write_text("questions: []\n", encoding="utf-8")

    exit_code = cli.main(
        ["build-dataset", "--source", str(source), "--manifest", str(MANIFEST), "--out", "x.jsonl"]
    )

    assert exit_code == 1
    assert "Invalid source" in capsys.readouterr().err
    assert not Path("x.jsonl").exists()


def test_review_sheet_shows_unreviewed_questions_with_exact_evidence(tmp_path: Path) -> None:
    draft = yaml.safe_load(MINI.read_text(encoding="utf-8"))
    draft["questions"][1]["reviewed"] = False  # q-0002 becomes a draft
    source = tmp_path / "draft.yaml"
    source.write_text(yaml.safe_dump(draft), encoding="utf-8")
    out = tmp_path / "sheet.md"

    exit_code = cli.main(
        ["review-sheet", "--source", str(source), "--manifest", str(MANIFEST), "--out", str(out)]
    )

    sheet = out.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "## q-0002 · exact_identifier" in sheet
    assert "## q-0001" not in sheet  # reviewed questions are left out by default
    assert "> use_cache=False" in sheet  # the exact labelled text, quote_only span
    assert "`fastapi/dependencies@0.115`" in sheet


# --- run / compare ---------------------------------------------------------------------------


@pytest.fixture
def run_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    make_tenant: Callable[..., Tenant],
    load_fixture_corpus: Callable[[Tenant], None],
    mini_dataset: Dataset,
) -> dict[str, str]:
    """A tenant with the fixture corpus, a built dataset and a config, wired into the CLI."""
    tenant = make_tenant("eval-fixture")
    load_fixture_corpus(tenant)
    # Run inside this test's rolled-back session, with the fake embedder instead of torch.
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: lambda: db_session)
    monkeypatch.setattr(cli, "build_query_embedder", lambda instruction: FakeEmbedder())
    dataset_path = tmp_path / "mini.jsonl"
    write_dataset(mini_dataset, dataset_path)
    config_path = tmp_path / "fixture.yaml"
    config_path.write_text("name: fixture\ncutoffs: [5, 10]\n", encoding="utf-8")
    return {
        "dataset": str(dataset_path),
        "config": str(config_path),
        "tenant": tenant.name,
        "out": str(tmp_path / "reports"),
        "sha256": mini_dataset.sha256,
    }


def _run_args(setup: dict[str, str], split: str) -> list[str]:
    return [
        "run",
        "--config", setup["config"],
        "--dataset", setup["dataset"],
        "--split", split,
        "--tenant", setup["tenant"],
        "--manifest", str(MANIFEST),
        "--out-dir", setup["out"],
    ]  # fmt: skip


def test_test_split_needs_allow_test_and_writes_nothing(
    run_setup: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(_run_args(run_setup, "test")) == 2
    assert "--allow-test" in capsys.readouterr().err
    assert not Path(run_setup["out"]).exists()


def test_run_writes_a_record_and_a_report_from_it(run_setup: dict[str, str]) -> None:
    assert cli.main([*_run_args(run_setup, "test"), "--allow-test"]) == 0

    record_path = Path(run_setup["out"]) / "fixture-test.json"
    report = RunReport.model_validate_json(record_path.read_bytes())
    assert report.header.dataset.sha256 == run_setup["sha256"]
    assert report.header.corpus_documents == 2
    assert report.header.effective.embedding_model == FakeEmbedder.model_name
    assert b"\r\n" not in record_path.read_bytes()
    markdown = record_path.with_suffix(".md").read_text(encoding="utf-8")
    assert run_setup["sha256"] in markdown


def test_compare_of_a_run_with_itself_shows_no_difference(run_setup: dict[str, str]) -> None:
    assert cli.main([*_run_args(run_setup, "test"), "--allow-test"]) == 0
    record = str(Path(run_setup["out"]) / "fixture-test.json")

    assert cli.main(["compare", record, record, "--out-dir", run_setup["out"]]) == 0

    comparison = Path(run_setup["out"]) / "compare-fixture-test-vs-fixture-test.md"
    text = comparison.read_text(encoding="utf-8")
    assert "[+0.000, +0.000]" in text
    assert "| 0 /" in text


def test_run_against_an_unknown_tenant_fails_cleanly(
    run_setup: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    args = _run_args({**run_setup, "tenant": "no-such-tenant"}, "test")

    assert cli.main([*args, "--allow-test"]) == 1
    assert "Unknown tenant" in capsys.readouterr().err


def test_a_reranking_config_builds_the_reranker(
    run_setup: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "build_reranker", lambda: FakeReranker())
    config = tmp_path / "rerank.yaml"
    config.write_text("name: rr\nrerank: true\nrerank_depth: 5\n", encoding="utf-8")
    args = _run_args({**run_setup, "config": str(config)}, "test")

    assert cli.main([*args, "--allow-test"]) == 0

    record = RunReport.model_validate_json((Path(run_setup["out"]) / "rr-test.json").read_bytes())
    assert record.header.effective.reranker_model == "fake-reranker"
    assert record.header.config.rerank_depth == 5
