import math
import uuid
from collections.abc import Callable

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.documents.models import DocumentChunk
from app.evaluation.dataset import BuiltEvidence, BuiltQuestion, BuiltSpan, Dataset
from app.evaluation.records import RunConfig, run_score_kind
from app.evaluation.runner import (
    RunError,
    execute_run,
    percentile,
    run_evaluation,
    score_question,
    search_options,
    summarise,
    verify_corpus,
)
from app.retrieval.repository import SearchHit
from app.retrieval.service import SearchOptions, configured_chunker
from tests.fakes import FakeEmbedder, FakeReranker

MODEL = FakeEmbedder.model_name


def _hit(slug: str, start: int, end: int, score: float = 0.5) -> SearchHit:
    return SearchHit(
        chunk_id=uuid.uuid4(),
        text="",
        char_start=start,
        char_end=end,
        heading_path="",
        document_id=uuid.uuid4(),
        source="s",
        slug=slug,
        version="1",
        title="t",
        score=score,
    )


def _question(evidence: list[tuple[int, int, int]], query_type: str = "factual") -> BuiltQuestion:
    """Evidence as (grade, char_start, char_end) spans in document doc@1."""
    return BuiltQuestion(
        id=f"q-{uuid.uuid4().int % 10_000:04d}",
        split="dev",
        query_type=query_type,
        question="q",
        reference_answer=None,
        answerable=bool(evidence),
        reviewed=True,
        notes=None,
        word_overlap=0.5 if evidence else None,
        evidence=[
            BuiltEvidence(
                grade=grade,
                spans=[BuiltSpan(slug="doc", version="1", char_start=s, char_end=e, quote="x")],
            )
            for grade, s, e in evidence
        ],
    )


# --- Config ------------------------------------------------------------------------------


def test_config_rejects_unknown_keys_and_cutoffs_beyond_depth() -> None:
    with pytest.raises(ValidationError):
        RunConfig.model_validate({"name": "a", "temperature": 0.2})
    with pytest.raises(ValidationError, match="between 1 and depth"):
        RunConfig(name="a", depth=5, cutoffs=[10])
    assert RunConfig(name="a", cutoffs=[10, 5, 5]).cutoffs == [5, 10]


# --- Scoring (hand-computed) --------------------------------------------------------------


def test_score_question_plumbs_matches_into_every_cutoff() -> None:
    question = _question([(3, 0, 100), (1, 200, 300)])
    hits = [_hit("other", 0, 100), _hit("doc", 0, 100), _hit("doc", 200, 300)]

    record = score_question(question, hits, [1, 3], {"total": 1.0})

    assert [hit.matched_items for hit in record.hits] == [[], [0], [1]]
    assert record.scores[1].model_dump() == {
        "precision": 0.0,
        "recall": 0.0,
        "reciprocal_rank": 0.0,
        "ndcg": 0.0,
    }
    at_3 = record.scores[3]
    assert (at_3.precision, at_3.recall, at_3.reciprocal_rank) == pytest.approx((2 / 3, 1, 0.5))
    # DCG: grade 3 at rank 2, grade 1 at rank 3; ideal: grade 3 at rank 1, grade 1 at rank 2.
    dcg = 7 / math.log2(3) + 1 / math.log2(4)
    ideal = 7 / math.log2(2) + 1 / math.log2(3)
    assert at_3.ndcg == pytest.approx(dcg / ideal)


def test_unanswerable_questions_keep_their_hits_but_are_not_scored() -> None:
    record = score_question(_question([], "unanswerable"), [_hit("doc", 0, 10)], [5], {})

    assert record.scores is None
    assert record.hits[0].matched_items == []


def test_summary_counts_only_answerable_questions_per_type() -> None:
    hit = [_hit("doc", 0, 100)]
    records = [
        score_question(_question([(3, 0, 100)], "factual"), hit, [5], {"total": 2.0}),
        score_question(_question([(3, 500, 600)], "paraphrase"), hit, [5], {"total": 4.0}),
        score_question(_question([], "unanswerable"), hit, [5], {"total": 6.0}),
    ]

    results = summarise(records, [5])

    rows = results.metrics[5]
    assert set(rows) == {"all", "factual", "paraphrase"}
    assert rows["all"].count == 2
    assert rows["all"].recall == pytest.approx(0.5)
    assert results.latency_ms["total"].p50 == 4.0
    assert len(results.questions) == 3


def test_percentile_is_nearest_rank() -> None:
    values = list(range(1, 21))

    assert (percentile(values, 0.5), percentile(values, 0.95)) == (10, 19)
    assert percentile([7.0], 0.95) == 7.0


# --- Corpus check ---------------------------------------------------------------------------


def _verify(session: Session, tenant: Tenant, texts: dict, chunker: str | None = None) -> int:
    return verify_corpus(
        session, tenant.id, texts, chunker=chunker or configured_chunker(), embedding_model=MODEL
    )


def test_corpus_check_passes_when_the_tenant_holds_exactly_the_corpus(
    db_session: Session, make_tenant: Callable[..., Tenant], load_fixture_corpus, corpus_texts
) -> None:
    tenant = make_tenant()
    load_fixture_corpus(tenant)

    assert _verify(db_session, tenant, corpus_texts) == 2


def test_corpus_check_names_a_one_byte_change(
    db_session: Session, make_tenant: Callable[..., Tenant], load_fixture_corpus, corpus_texts
) -> None:
    tenant = make_tenant()
    load_fixture_corpus(tenant)
    changed = dict(corpus_texts)
    changed[("incidents/0001", "1")] += " "

    with pytest.raises(RunError, match="incidents/0001@1: stored content differs"):
        _verify(db_session, tenant, changed)


def test_corpus_check_reports_missing_and_extra_documents(
    db_session: Session, make_tenant: Callable[..., Tenant], load_fixture_corpus, corpus_texts
) -> None:
    tenant = make_tenant()
    load_fixture_corpus(tenant)
    texts = {key: value for key, value in corpus_texts.items() if key[0] != "incidents/0001"}
    texts[("fastapi/missing", "1")] = "never ingested"

    with pytest.raises(RunError) as raised:
        _verify(db_session, tenant, texts)

    assert "fastapi/missing@1: not ingested" in str(raised.value)
    assert "incidents/0001@1: in the tenant but not in the corpus manifest" in str(raised.value)


def test_corpus_check_requires_chunks_of_the_configured_chunker(
    db_session: Session, make_tenant: Callable[..., Tenant], load_fixture_corpus, corpus_texts
) -> None:
    tenant = make_tenant()
    load_fixture_corpus(tenant)

    with pytest.raises(RunError, match="no other-chunker chunks"):
        _verify(db_session, tenant, corpus_texts, chunker="other-chunker")


def test_corpus_check_never_sees_another_tenants_documents(
    db_session: Session, make_tenant: Callable[..., Tenant], load_fixture_corpus, corpus_texts
) -> None:
    owner, other = make_tenant(), make_tenant()
    load_fixture_corpus(owner)

    with pytest.raises(RunError, match="fastapi/dependencies@0.115: not ingested"):
        _verify(db_session, other, corpus_texts)


# --- End to end with the database -----------------------------------------------------------


def test_run_scores_answerable_questions_through_the_search_service(
    db_session: Session,
    make_tenant: Callable[..., Tenant],
    load_fixture_corpus,
    mini_dataset: Dataset,
) -> None:
    tenant = make_tenant()
    load_fixture_corpus(tenant)
    first = mini_dataset.questions[0]
    # Pin q-0001's query to the chunk holding its evidence, so rank 1 is known.
    evidence_chunk = db_session.scalars(
        select(DocumentChunk).where(
            DocumentChunk.tenant_id == tenant.id, DocumentChunk.text.contains("Depends(get_db)")
        )
    ).one()
    pinned = FakeEmbedder().embed_documents([evidence_chunk.text])[0]
    embedder = FakeEmbedder(query_vectors={first.question: pinned})

    results = run_evaluation(
        db_session, tenant.id, embedder, mini_dataset.questions, RunConfig(name="t")
    )

    by_id = {record.id: record for record in results.questions}
    assert by_id["q-0001"].hits[0].matched_items == [0]
    assert by_id["q-0001"].scores[5].reciprocal_rank == 1.0
    assert by_id["q-0005"].scores is None
    assert results.metrics[10]["all"].count == 4
    assert set(results.latency_ms) == {"embed_query", "dense", "total"}


def test_run_refuses_an_empty_split(db_session: Session) -> None:
    with pytest.raises(RunError, match="no questions"):
        run_evaluation(db_session, uuid.uuid4(), FakeEmbedder(), [], RunConfig(name="t"))


def test_a_hybrid_config_reaches_the_search_service(
    db_session: Session,
    make_tenant: Callable[..., Tenant],
    load_fixture_corpus,
    mini_dataset: Dataset,
) -> None:
    tenant = make_tenant()
    load_fixture_corpus(tenant)
    config = RunConfig(name="t", retriever="hybrid", fusion_depth=20, rrf_k=10)

    results = run_evaluation(db_session, tenant.id, FakeEmbedder(), mini_dataset.questions, config)

    assert set(results.latency_ms) == {"embed_query", "dense", "keyword", "fuse", "total"}
    assert search_options(config) == SearchOptions(k=10, mode="hybrid", fusion_depth=20, rrf_k=10)


@pytest.mark.parametrize(
    ("config", "kind"),
    [
        (RunConfig(name="a"), "cosine"),
        (RunConfig(name="a", retriever="keyword"), "ts_rank_cd"),
        (RunConfig(name="a", retriever="hybrid"), "rrf"),
        (RunConfig(name="a", retriever="hybrid", rerank=True), "cross_encoder"),
    ],
)
def test_score_kind_names_what_hit_scores_mean(config: RunConfig, kind: str) -> None:
    assert run_score_kind(config) == kind


def test_a_reranking_config_without_a_reranker_fails_clearly(
    db_session: Session,
    make_tenant: Callable[..., Tenant],
    mini_dataset: Dataset,
    corpus_texts: dict,
) -> None:
    config = RunConfig(name="t", rerank=True)

    with pytest.raises(RunError, match="no reranker was provided"):
        execute_run(
            db_session, make_tenant().id, FakeEmbedder(), config, mini_dataset, "dev",
            corpus_texts, "",
        )  # fmt: skip


def test_a_reranked_run_records_its_model_and_rerank_stage(
    db_session: Session,
    make_tenant: Callable[..., Tenant],
    load_fixture_corpus,
    mini_dataset: Dataset,
    corpus_texts: dict,
) -> None:
    tenant = make_tenant()
    load_fixture_corpus(tenant)
    reranker = FakeReranker()
    split = mini_dataset.questions[0].split
    config = RunConfig(name="t", rerank=True, rerank_depth=20)

    report = execute_run(
        db_session, tenant.id, FakeEmbedder(), config, mini_dataset, split, corpus_texts, "",
        reranker,
    )  # fmt: skip

    assert report.header.effective.score_kind == "cross_encoder"
    assert report.header.effective.reranker_model == "fake-reranker"
    assert "rerank" in report.results.latency_ms
    assert reranker.calls
    first_hits = report.results.questions[0].hits
    assert [hit.score for hit in first_hits] == sorted(
        (hit.score for hit in first_hits), reverse=True
    )
