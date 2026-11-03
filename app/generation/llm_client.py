"""The LLM gateway: one structured-output call, with provider errors translated at the edge.

Nothing outside this module imports `groq`, so services never see SDK exceptions.
"""

import logging
import time
from dataclasses import dataclass
from typing import Protocol

import groq

from app.core.errors import LLMUnavailableError

logger = logging.getLogger(__name__)

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
    ) -> None:
        # The SDK retries timeouts, 429 and 5xx with backoff, up to max_retries.
        self._client = groq.Groq(api_key=api_key, timeout=timeout_seconds, max_retries=max_retries)
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
            # Timeouts, connection failures, 401/403, 429 and 5xx: nothing the caller can fix.
            logger.warning("llm unavailable", extra={"fields": {"error": type(exc).__name__}})
            raise LLMUnavailableError() from exc
        usage = response.usage
        return LLMReply(
            content=response.choices[0].message.content or "",
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
