"""Approximate prices used to estimate cost per document.

USD per million tokens as (input, output), from the Anthropic API pricing table in the Claude API
reference (cached 2026-06-24). Output tokens include thinking tokens.
"""

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        return None
    return round((input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000, 6)
