"""Estimated LLM cost from configured per-model prices (task 012).

No prices ship with the code: providers change them, and the free tier costs nothing. An
unpriced model's cost is None rather than a guess.
"""

from collections.abc import Sequence

from app.core.config import get_settings

TOKENS_PER_PRICE_UNIT = 1_000_000


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """USD for one call at the configured price of `model`; None when it has no price."""
    prices = get_settings().llm_prices.get(model)
    return None if prices is None else cost_at(prices, prompt_tokens, completion_tokens)


def cost_at(prices: Sequence[float], prompt_tokens: int, completion_tokens: int) -> float:
    """tokens / 1M x [input, output] USD per million. Reports use the prices recorded with
    a run, not today's settings, so an old report's cost never changes."""
    input_price, output_price = prices
    return (prompt_tokens * input_price + completion_tokens * output_price) / TOKENS_PER_PRICE_UNIT


def add_costs(total: float | None, cost: float | None) -> float | None:
    """A total stays known only while every part is known."""
    return None if total is None or cost is None else total + cost
