"""GroqClient error translation and reply mapping, with the SDK call replaced (no network)."""

from types import SimpleNamespace

import groq
import httpx
import pytest

from app.core.errors import LLMUnavailableError
from app.generation.llm_client import GroqClient, LLMOutputRejectedError

REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _status_error(cls: type[groq.APIStatusError], status: int) -> groq.APIStatusError:
    return cls("error", response=httpx.Response(status, request=REQUEST), body=None)


def _client(create: object) -> GroqClient:
    client = GroqClient(
        api_key="test-key-not-real",
        model="openai/gpt-oss-20b",
        timeout_seconds=1,
        max_retries=0,
        max_completion_tokens=64,
    )
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    return client


def _raising(error: Exception) -> object:
    def create(**_kwargs: object) -> None:
        raise error

    return create


@pytest.mark.parametrize(
    "error",
    [
        groq.APITimeoutError(request=REQUEST),
        groq.APIConnectionError(request=REQUEST),
        _status_error(groq.RateLimitError, 429),
        _status_error(groq.InternalServerError, 500),
        _status_error(groq.AuthenticationError, 401),
    ],
)
def test_provider_failures_become_llm_unavailable(error: Exception) -> None:
    with pytest.raises(LLMUnavailableError):
        _client(_raising(error)).complete_json([], {}, "s")


def test_a_rejected_generation_is_an_output_problem_not_an_outage() -> None:
    error = _status_error(groq.BadRequestError, 400)

    with pytest.raises(LLMOutputRejectedError):
        _client(_raising(error)).complete_json([], {}, "s")


def test_the_reply_and_usage_are_mapped_and_the_schema_is_strict() -> None:
    sent: dict = {}

    def create(**kwargs: object) -> SimpleNamespace:
        sent.update(kwargs)
        return SimpleNamespace(
            model="openai/gpt-oss-20b",
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"a": 1}'))],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30),
        )

    reply = _client(create).complete_json(
        [{"role": "user", "content": "q"}], {"type": "object"}, "s"
    )

    assert (reply.content, reply.prompt_tokens, reply.completion_tokens) == ('{"a": 1}', 120, 30)
    assert sent["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "s", "strict": True, "schema": {"type": "object"}},
    }
    assert sent["temperature"] == 0
