"""Evaluation runs over the API: roles, tenant isolation, input checks, and the worker job."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import Role, Tenant, User
from app.core.config import get_settings
from app.evaluation import repository
from app.evaluation.dataset import Dataset, build_dataset, write_dataset
from app.evaluation.models import EvaluationResult, EvaluationRun
from app.evaluation.records import RunConfig
from app.evaluation.runner import execute_run
from app.evaluation.service import store_report, stored_run_report
from app.ingestion.chunking import TokenWindowChunker
from app.jobs import repository as jobs_repository
from app.jobs.models import JobKind
from app.worker import build_handlers, process_next_job
from tests.conftest import auth_headers
from tests.evaluation.conftest import MANIFEST, MINI
from tests.fakes import FakeEmbedder, FakeReranker, WhitespaceTokenizer

RUNS = "/v1/evaluations/runs"


@pytest.fixture
def datasets_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mini_dataset: Dataset
) -> Iterator[Path]:
    """Point the API at a directory holding `mini.jsonl` and at the fixture corpus."""
    write_dataset(mini_dataset, tmp_path / "mini.jsonl")
    monkeypatch.setenv("EVAL_DATASETS_DIR", str(tmp_path))
    monkeypatch.setenv("EVAL_CORPUS_MANIFEST", str(MANIFEST))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _body(split: str = "dev", **overrides: object) -> dict[str, object]:
    return {"dataset": "mini", "split": split, "config": {"name": "fixture"}, **overrides}


def _drain_queue(session: Session) -> None:
    settings = get_settings()
    chunker = TokenWindowChunker(
        WhitespaceTokenizer(), settings.chunk_max_tokens, settings.chunk_overlap_tokens
    )
    handlers = build_handlers(chunker, FakeEmbedder())
    while process_next_job(session, handlers):
        pass


def _split_with_questions(dataset: Dataset) -> str:
    return dataset.questions[0].split


# --- Roles and input checks ---------------------------------------------------------------


@pytest.mark.usefixtures("datasets_dir")
@pytest.mark.parametrize("role", [Role.VIEWER, Role.EDITOR])
def test_only_admins_start_runs(
    client: TestClient, make_user: Callable[..., User], role: Role
) -> None:
    response = client.post(RUNS, json=_body(), headers=auth_headers(make_user(role)))

    assert response.status_code == 403


@pytest.mark.usefixtures("datasets_dir")
@pytest.mark.parametrize(
    ("dataset", "message"),
    [("../mini", "String should match pattern"), ("a/b", "String should match pattern"),
     ("missing", "unknown dataset")],
)  # fmt: skip
def test_dataset_must_be_a_known_name(
    client: TestClient, make_user: Callable[..., User], dataset: str, message: str
) -> None:
    response = client.post(
        RUNS, json=_body(dataset=dataset), headers=auth_headers(make_user(Role.ADMIN))
    )

    assert response.status_code == 422
    assert message in response.json()["field_errors"]["dataset"][0]


@pytest.mark.usefixtures("datasets_dir")
def test_test_split_requires_allow_test(client: TestClient, make_user: Callable[..., User]) -> None:
    response = client.post(RUNS, json=_body("test"), headers=auth_headers(make_user(Role.ADMIN)))

    assert response.status_code == 422
    assert "allow_test" in response.json()["field_errors"]


@pytest.mark.usefixtures("datasets_dir")
def test_body_cannot_choose_the_tenant(client: TestClient, make_user: Callable[..., User]) -> None:
    body = _body(tenant_id="00000000-0000-0000-0000-000000000000")

    response = client.post(RUNS, json=body, headers=auth_headers(make_user(Role.ADMIN)))

    assert response.status_code == 422


# --- Tenant isolation ----------------------------------------------------------------------


@pytest.mark.usefixtures("datasets_dir")
def test_runs_are_invisible_to_other_tenants(
    client: TestClient,
    make_user: Callable[..., User],
    make_tenant: Callable[..., Tenant],
    mini_dataset: Dataset,
) -> None:
    owner = make_user(Role.ADMIN)
    split = _split_with_questions(mini_dataset)
    body = _body(split, allow_test=True)
    run_id = client.post(RUNS, json=body, headers=auth_headers(owner)).json()["run_id"]
    outsider = make_user(Role.VIEWER, tenant=make_tenant())

    assert client.get(f"{RUNS}/{run_id}", headers=auth_headers(outsider)).status_code == 404
    assert client.get(RUNS, headers=auth_headers(outsider)).json()["total"] == 0
    listed = client.get(RUNS, headers=auth_headers(owner)).json()
    assert [item["id"] for item in listed["items"]] == [run_id]
    assert listed["items"][0]["status"] == "queued"
    assert listed["items"][0]["overall"] is None


# --- The worker job ------------------------------------------------------------------------


@pytest.mark.usefixtures("datasets_dir")
def test_a_queued_run_is_executed_and_stored(
    client: TestClient,
    db_session: Session,
    make_user: Callable[..., User],
    load_fixture_corpus: Callable[[Tenant], None],
    mini_dataset: Dataset,
) -> None:
    admin = make_user(Role.ADMIN)
    load_fixture_corpus(db_session.get(Tenant, admin.tenant_id))
    split = _split_with_questions(mini_dataset)
    headers = auth_headers(admin)
    run_id = client.post(RUNS, json=_body(split, allow_test=True), headers=headers).json()["run_id"]

    _drain_queue(db_session)

    detail = client.get(f"{RUNS}/{run_id}", headers=headers).json()
    assert detail["run"]["status"] == "succeeded"
    assert detail["dataset"]["sha256"] == mini_dataset.sha256
    assert detail["corpus_documents"] == 2
    assert detail["results"] is None
    assert set(detail["summary"]["metrics"]) == {"5", "10"}
    with_results = client.get(f"{RUNS}/{run_id}?include=results", headers=headers).json()
    expected = sum(1 for question in mini_dataset.questions if question.split == split)
    assert len(with_results["results"]) == expected
    listed = client.get(RUNS, headers=headers).json()["items"][0]
    assert listed["overall"] == detail["summary"]["metrics"]["10"]["all"]


@pytest.mark.usefixtures("datasets_dir")
def test_a_failed_run_keeps_the_error_and_stores_nothing(
    client: TestClient, db_session: Session, make_user: Callable[..., User], mini_dataset: Dataset
) -> None:
    # No corpus loaded in this tenant: the corpus check must fail the job.
    admin = make_user(Role.ADMIN)
    headers = auth_headers(admin)
    body = _body(_split_with_questions(mini_dataset), allow_test=True)
    run_id = client.post(RUNS, json=body, headers=headers).json()["run_id"]

    _drain_queue(db_session)

    detail = client.get(f"{RUNS}/{run_id}", headers=headers).json()
    assert detail["run"]["status"] == "failed"
    assert "not ingested" in detail["run"]["error"]
    assert detail["summary"] is None
    assert db_session.scalar(select(func.count(EvaluationResult.id))) == 0


def test_a_dataset_changed_after_queueing_fails_the_run(
    client: TestClient,
    db_session: Session,
    make_user: Callable[..., User],
    load_fixture_corpus: Callable[[Tenant], None],
    datasets_dir: Path,
    mini_dataset: Dataset,
) -> None:
    admin = make_user(Role.ADMIN)
    load_fixture_corpus(db_session.get(Tenant, admin.tenant_id))
    headers = auth_headers(admin)
    body = _body(_split_with_questions(mini_dataset), allow_test=True)
    run_id = client.post(RUNS, json=body, headers=headers).json()["run_id"]
    # Same name, different split seed: a different file under the same dataset name.
    write_dataset(build_dataset(MINI, MANIFEST, "mini", "other-seed"), datasets_dir / "mini.jsonl")

    _drain_queue(db_session)

    detail = client.get(f"{RUNS}/{run_id}", headers=headers).json()
    assert detail["run"]["status"] == "failed"
    assert "changed after the run was queued" in detail["run"]["error"]


# --- Storage round trip ----------------------------------------------------------------------


def test_a_stored_run_converts_back_to_the_same_record(
    db_session: Session,
    make_user: Callable[..., User],
    load_fixture_corpus: Callable[[Tenant], None],
    mini_dataset: Dataset,
    corpus_texts: dict[tuple[str, str], str],
) -> None:
    admin = make_user(Role.ADMIN)
    load_fixture_corpus(db_session.get(Tenant, admin.tenant_id))
    split = _split_with_questions(mini_dataset)
    report = execute_run(
        db_session,
        admin.tenant_id,
        FakeEmbedder(),
        RunConfig(name="fixture"),
        mini_dataset,
        split,
        corpus_texts,
        "",
    )
    job = jobs_repository.add_job(db_session, admin.tenant_id, JobKind.EVALUATE, {})
    run = repository.add_run(
        db_session,
        EvaluationRun(
            tenant_id=admin.tenant_id,
            created_by=admin.id,
            job_id=job.id,
            dataset_name="mini",
            dataset_sha256=mini_dataset.sha256,
            split=split,
            config=RunConfig(name="fixture").model_dump(mode="json"),
        ),
    )

    store_report(db_session, run, report)
    db_session.flush()
    db_session.expire_all()

    stored = db_session.get(EvaluationRun, run.id)
    rebuilt = stored_run_report(
        stored, repository.list_results(db_session, admin.tenant_id, run.id)
    )
    assert rebuilt == report


@pytest.mark.usefixtures("datasets_dir")
def test_the_worker_loads_the_reranker_only_for_reranking_runs(
    client: TestClient,
    db_session: Session,
    make_user: Callable[..., User],
    load_fixture_corpus: Callable[[Tenant], None],
    mini_dataset: Dataset,
) -> None:
    admin = make_user(Role.ADMIN)
    load_fixture_corpus(db_session.get(Tenant, admin.tenant_id))
    headers = auth_headers(admin)
    split = _split_with_questions(mini_dataset)
    plain = _body(split, allow_test=True)
    reranked = _body(split, allow_test=True, config={"name": "rr", "rerank": True})
    plain_id = client.post(RUNS, json=plain, headers=headers).json()["run_id"]
    reranked_id = client.post(RUNS, json=reranked, headers=headers).json()["run_id"]
    loads: list[str] = []

    def load_reranker() -> FakeReranker:
        loads.append("loaded")
        return FakeReranker()

    settings = get_settings()
    chunker = TokenWindowChunker(
        WhitespaceTokenizer(), settings.chunk_max_tokens, settings.chunk_overlap_tokens
    )
    handlers = build_handlers(chunker, FakeEmbedder(), load_reranker=load_reranker)
    while process_next_job(db_session, handlers):
        pass

    assert loads == ["loaded"]
    plain_run = client.get(f"{RUNS}/{plain_id}", headers=headers).json()
    reranked_run = client.get(f"{RUNS}/{reranked_id}", headers=headers).json()
    assert plain_run["effective"]["score_kind"] == "cosine"
    assert reranked_run["effective"]["score_kind"] == "cross_encoder"
    assert "rerank" in reranked_run["summary"]["latency_ms"]
