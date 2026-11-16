"""The LLM gateway: one structured-output call, with provider errors translated at the edge.

Nothing outside this module imports `groq`, so services never see SDK exceptions. Failures
are classified (task 011): transient (retry later), daily quota (retry after a long wait),
or configuration (an operator must act); see `_classify`.
"""

import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Protocol

import groq
import httpx

from app.core.errors import LLMNotConfiguredError, LLMQuotaExceededError, LLMUnavailableError

logger = logging.getLogger(__name__)

# The SDK itself waits out a retry-after only up to 60 s; anything longer is not a blip.
SHORT_RETRY_AFTER_SECONDS = 60
# Groq names daily limits like "tokens per day (TPD)" (seen in task 009b).
_DAILY_LIMIT = re.compile(r"per day|\b(TPD|RPD)\b", re.IGNORECASE)
# Rejected key, no access to the model, unknown model: retrying cannot help.
_CONFIGURATION_STATUSES = {401, 403, 404}

Messages = list[dict[str, str]]


@dataclass(frozen=True)
class LLMReply:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float


class LLMOutputRejectedError(Exception):
    """The provider refused the generated output (e.g. a schema failure reported as 400)."""


class LLMClient(Protocol):
    model_name: str

    def complete_json(self, messages: Messages, schema: dict, schema_name: str) -> LLMReply: ...


class GroqClient:
    """Groq chat completions with a strict JSON schema (constrained decoding)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        max_completion_tokens: int,
        http_client: httpx.Client | None = None,
    ) -> None:
        # The SDK retries timeouts, 408/409/429 and 5xx with backoff, up to max_retries.
        # `http_client` lets tests drive the real SDK over a mock transport.
        self._client = groq.Groq(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
            http_client=http_client,
        )
        self._max_completion_tokens = max_completion_tokens
        self.model_name = model

    def complete_json(self, messages: Messages, schema: dict, schema_name: str) -> LLMReply:
        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                },
                max_completion_tokens=self._max_completion_tokens,
                # Repeatable answers for the same context matter more than variety here.
                temperature=0,
            )
        except groq.BadRequestError as exc:
            raise LLMOutputRejectedError(
                f"provider rejected the request: {exc.status_code}"
            ) from exc
        except (groq.APIConnectionError, groq.APIStatusError) as exc:
            error = _classify(exc)
            # The error kind and status only: never the key or the provider's message text.
            fields = {"error": type(exc).__name__, "kind": error.error_code}
            logger.warning("llm unavailable", extra={"fields": fields})
            raise error from exc
        usage = response.usage
        return LLMReply(
            content=response.choices[0].message.content or "",
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )


def _classify(exc: groq.APIConnectionError | groq.APIStatusError) -> LLMUnavailableError:
    """Map a provider failure (after the SDK's own retries) to what the caller should do."""
    if not isinstance(exc, groq.APIStatusError):
        return LLMUnavailableError()  # timeout or connection failure
    if exc.status_code in _CONFIGURATION_STATUSES:
        return LLMNotConfiguredError()
    retry_after = _retry_after_seconds(exc.response.headers)
    if exc.status_code != 429:
        return LLMUnavailableError(retry_after_seconds=retry_after)
    if (retry_after or 0) > SHORT_RETRY_AFTER_SECONDS or _DAILY_LIMIT.search(str(exc.message)):
        return LLMQuotaExceededError(retry_after_seconds=retry_after)
    return LLMUnavailableError(retry_after_seconds=retry_after)


def _retry_after_seconds(headers: httpx.Headers) -> int | None:
    """Whole seconds from a numeric Retry-After header; dates and junk are ignored."""
    try:
        return math.ceil(float(headers.get("retry-after", "")))
    except ValueError:
        return None
