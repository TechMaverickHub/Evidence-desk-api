"""Failure scenarios 1-5 (task 011): the real Groq SDK over a mock transport, no network.

These pin how many requests each failure costs and how it is classified, so an SDK upgrade
that changes retry behaviour fails here first.
"""

import json
from collections.abc import Callable

import httpx
import pytest

from app.core.errors import LLMNotConfiguredError, LLMQuotaExceededError, LLMUnavailableError
from app.generation.llm_client import GroqClient

TPD_MESSAGE = (
    "Rate limit reached for model `openai/gpt-oss-20b` in organization `org_x` service tier "
    "`on_demand` on tokens per day (TPD): Limit 200000, Used 198858, Requested 1586."
)
COMPLETION = {
    "id": "c",
    "object": "chat.completion",
    "created": 0,
    "model": "openai/gpt-oss-20b",
    "choices": [{"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": "{\"ok\": true}"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
}  # fmt: skip


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    # The SDK sleeps between retries; the count matters here, not the wall time.
    monkeypatch.setattr("groq._base_client.time.sleep", lambda _seconds: None)


def _error(status: int, message: str = "error", **headers: str) -> httpx.Response:
    body = {"error": {"message": message, "type": "error"}}
    return httpx.Response(status, json=body, headers=headers)


def _client(responses: list[Callable[[], httpx.Response]], requests: list) -> GroqClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses[min(len(requests), len(responses)) - 1]()

    return GroqClient(
        api_key="test-key-not-real",
        model="openai/gpt-oss-20b",
        timeout_seconds=1,
        max_retries=2,
        max_completion_tokens=64,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _call(client: GroqClient) -> object:
    return client.complete_json([{"role": "user", "content": "q"}], {"type": "object"}, "s")


def test_1_a_timeout_is_retried_then_reported_unavailable() -> None:
    requests: list = []

    def timeout() -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=requests[-1])

    with pytest.raises(LLMUnavailableError) as raised:
        _call(_client([timeout], requests))

    assert type(raised.value) is LLMUnavailableError
    assert len(requests) == 3  # 1 + max_retries


def test_2_a_short_rate_limit_is_retried_and_then_succeeds() -> None:
    requests: list = []
    responses = [lambda: _error(429, "slow down", **{"retry-after": "1"}),
                 lambda: httpx.Response(200, json=COMPLETION)]  # fmt: skip

    reply = _call(_client(responses, requests))

    assert json.loads(reply.content) == {"ok": True}
    assert len(requests) == 2


def test_3_persistent_server_errors_end_unavailable_with_the_retry_hint() -> None:
    requests: list = []

    with pytest.raises(LLMUnavailableError) as raised:
        _call(_client([lambda: _error(503, **{"retry-after": "5"})], requests))

    assert type(raised.value) is LLMUnavailableError
    assert raised.value.retry_after_seconds == 5
    assert raised.value.headers == {"Retry-After": "5"}
    assert len(requests) == 3


@pytest.mark.parametrize(
    "headers", [{"retry-after": "191"}, {}], ids=["long-retry-after", "message-only"]
)
def test_4_a_daily_quota_is_its_own_error(headers: dict[str, str]) -> None:
    requests: list = []

    with pytest.raises(LLMQuotaExceededError) as raised:
        _call(_client([lambda: _error(429, TPD_MESSAGE, **headers)], requests))

    assert raised.value.error_code == "LLM_QUOTA_EXCEEDED"
    assert raised.value.retry_after_seconds == (191 if headers else None)


@pytest.mark.parametrize("status", [401, 403, 404])
def test_5_configuration_failures_are_not_retried(status: int) -> None:
    requests: list = []

    with pytest.raises(LLMNotConfiguredError):
        _call(_client([lambda: _error(status)], requests))

    assert len(requests) == 1


def test_a_short_429_without_daily_wording_stays_transient() -> None:
    requests: list = []

    with pytest.raises(LLMUnavailableError) as raised:
        _call(
            _client([lambda: _error(429, "requests per minute", **{"retry-after": "2"})], requests)
        )

    assert type(raised.value) is LLMUnavailableError
    assert raised.value.retry_after_seconds == 2
