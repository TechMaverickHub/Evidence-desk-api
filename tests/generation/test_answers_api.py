"""POST /v1/answers with a scripted LLM: trust rules, retries, abstention, isolation, logging."""

import json
import logging
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.models import Tenant, User
from app.core.errors import LLMUnavailableError
from app.generation.deps import get_llm_client
from app.generation.llm_client import LLMOutputRejectedError
from tests.conftest import auth_headers
from tests.fakes import ScriptedLLMClient
from tests.retrieval.test_keyword_search import _add_chunk

ANSWERS = "/v1/answers"
QUESTION = "What is the default max_age of CORSMiddleware?"
SECRET_TEXT = "max_age defaults to 600 seconds for preflight caching"


def _reply(status: str = "answered", answer: str = "600 seconds.", citations: tuple = (1,)) -> str:
    return json.dumps({"status": status, "answer": answer, "citations": list(citations)})


@pytest.fixture
def tenant_with_chunks(db_session: Session, make_tenant: Callable[..., Tenant]) -> Tenant:
    tenant = make_tenant()
    for text in (SECRET_TEXT, "GZipMiddleware minimum_size is 500 bytes", "TrustedHost 400"):
        _add_chunk(db_session, tenant, text)
    return tenant


@pytest.fixture
def ask(
    app: FastAPI,
    client: TestClient,
    tenant_with_chunks: Tenant,
    make_user: Callable[..., User],
) -> Callable[..., tuple[int, dict, ScriptedLLMClient]]:
    headers = auth_headers(make_user(tenant=tenant_with_chunks))

    def _ask(*replies: str | Exception, question: str = QUESTION) -> tuple:
        llm = ScriptedLLMClient(*replies)
        app.dependency_overrides[get_llm_client] = lambda: llm
        response = client.post(ANSWERS, json={"question": question}, headers=headers)
        return response.status_code, response.json(), llm

    return _ask


def test_a_cited_answer_is_returned_with_its_passage(ask: Callable) -> None:
    status, body, llm = ask(_reply(citations=(1, 1)))

    assert status == 200
    assert body["status"] == "answered"
    assert body["answer"] == "600 seconds."
    assert len(body["citations"]) == 1
    cited = body["citations"][0]
    assert cited["chunk_id"] == body["retrieval"]["context_chunk_ids"][0]
    assert body["usage"]["llm_calls"] == 1
    assert body["retrieval"] == {**body["retrieval"], "mode": "dense", "rerank": True}
    assert set(body["latency_ms"]) == {"retrieval", "llm", "total"}
    (messages,) = llm.calls
    assert messages[0]["role"] == "system"
    assert '<passage id="1"' in messages[1]["content"]


def test_a_citation_outside_the_passages_gets_one_retry(ask: Callable) -> None:
    status, body, llm = ask(_reply(citations=(9,)), _reply(citations=(2,)))

    assert status == 200
    assert body["status"] == "answered"
    assert body["usage"]["llm_calls"] == 2
    assert "not given: [9]" in llm.calls[1][-1]["content"]


def test_an_unsupported_answer_twice_becomes_insufficient_evidence(ask: Callable) -> None:
    status, body, _ = ask(_reply(citations=(9,)), _reply(citations=()))

    assert status == 200
    assert body["status"] == "insufficient_evidence"
    assert (body["answer"], body["citations"]) == ("", [])


def test_malformed_output_twice_is_a_502(ask: Callable) -> None:
    status, body, _ = ask("not json", '{"status": "answered"}')

    assert status == 502
    assert body["error_code"] == "LLM_INVALID_OUTPUT"


def test_a_provider_rejection_then_a_valid_reply_succeeds(ask: Callable) -> None:
    status, body, _ = ask(LLMOutputRejectedError("400"), _reply())

    assert status == 200
    assert body["usage"]["llm_calls"] == 2


def test_the_model_may_refuse(ask: Callable) -> None:
    status, body, _ = ask(_reply("insufficient_evidence", "", ()))

    assert status == 200
    assert body["status"] == "insufficient_evidence"
    assert body["usage"]["llm_calls"] == 1


def test_provider_outage_is_a_503(ask: Callable) -> None:
    status, body, _ = ask(LLMUnavailableError())

    assert status == 503
    assert body["error_code"] == "LLM_UNAVAILABLE"


def test_nothing_retrieved_means_no_llm_call(
    app: FastAPI, client: TestClient, make_user: Callable[..., User]
) -> None:
    llm = ScriptedLLMClient()
    app.dependency_overrides[get_llm_client] = lambda: llm
    # A fresh tenant has no chunks at all.
    response = client.post(ANSWERS, json={"question": QUESTION}, headers=auth_headers(make_user()))

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert llm.calls == []


def test_without_an_llm_configured_answers_are_503_and_search_still_works(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    # The conftest default: get_llm_client returns None, as with no GROQ_API_KEY.
    headers = auth_headers(make_user())

    answer = client.post(ANSWERS, json={"question": QUESTION}, headers=headers)
    search = client.post("/v1/search", json={"query": QUESTION}, headers=headers)

    assert answer.status_code == 503
    assert "not configured" in answer.json()["message"]
    assert search.status_code == 200


def test_another_tenants_chunks_never_reach_the_prompt(
    app: FastAPI,
    client: TestClient,
    tenant_with_chunks: Tenant,
    make_user: Callable[..., User],
    db_session: Session,
    make_tenant: Callable[..., Tenant],
) -> None:
    other = make_tenant()
    _add_chunk(db_session, other, "OTHER TENANT max_age is 86400")
    llm = ScriptedLLMClient(_reply())
    app.dependency_overrides[get_llm_client] = lambda: llm

    client.post(
        ANSWERS,
        json={"question": "max_age"},
        headers=auth_headers(make_user(tenant=tenant_with_chunks)),
    )

    prompt = llm.calls[0][1]["content"]
    assert "OTHER TENANT" not in prompt
    assert SECRET_TEXT in prompt


def test_llm_logs_carry_metadata_but_no_question_or_passage_text(
    ask: Callable, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        ask(_reply(citations=(7,)), _reply())

    calls = [record for record in caplog.records if record.getMessage() == "llm call"]
    assert [record.fields["outcome"] for record in calls] == ["unsupported", "answered"]
    assert {"model", "attempt", "prompt_tokens", "latency_ms"} <= set(calls[0].fields)
    logged = " ".join(str(record.__dict__) for record in caplog.records)
    assert QUESTION not in logged
    assert SECRET_TEXT not in logged


@pytest.mark.parametrize(
    "body",
    [{"question": "  "}, {"question": "q", "tenant_id": "x"}, {"question": "q", "k": 3}],
)
def test_invalid_requests_are_rejected(
    client: TestClient, make_user: Callable[..., User], body: dict
) -> None:
    response = client.post(ANSWERS, json=body, headers=auth_headers(make_user()))

    assert response.status_code == 422


def test_answers_require_authentication(client: TestClient) -> None:
    assert client.post(ANSWERS, json={"question": QUESTION}).status_code == 401
