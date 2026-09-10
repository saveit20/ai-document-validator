"""Approximate prices used to estimate cost per document.

USD per million tokens as (input, output), from the Anthropic API pricing table in the Claude API
reference (cached 2026-06-24). Output tokens include thinking tokens. Prompt-cache reads cost 0.1x
the input price and 5-minute cache writes 1.25x; `input_tokens` excludes both.
"""

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}

CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        return None
    input_price, output_price = prices
    cost = (
        input_tokens * input_price
        + cache_read_tokens * input_price * CACHE_READ_MULTIPLIER
        + cache_write_tokens * input_price * CACHE_WRITE_MULTIPLIER
        + output_tokens * output_price
    )
    return round(cost / 1_000_000, 6)
