"""The API's LLM client and prompts, each built once per process."""

from functools import lru_cache

from app.core.config import get_settings
from app.generation.llm_client import GroqClient, LLMClient
from app.generation.prompts import AnswerPrompts, load_prompts


@lru_cache
def get_llm_client() -> LLMClient | None:
    """None when no API key is configured: /v1/answers then returns 503, nothing else breaks.
    Tests override this with a scripted fake, so they never reach the network."""
    return build_llm_client(get_settings().llm_model)


def build_llm_client(model: str) -> LLMClient | None:
    """A Groq client for `model` (the generator, or the judge in evaluation runs)."""
    settings = get_settings()
    if settings.groq_api_key is None:
        return None
    return GroqClient(
        api_key=settings.groq_api_key.get_secret_value(),
        model=model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        max_completion_tokens=settings.llm_max_completion_tokens,
    )


def get_prompts() -> AnswerPrompts:
    return load_prompts()
