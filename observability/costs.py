"""List prices in USD per million tokens (input, output), used for cost estimates only.

Estimates ignore prompt caching and batch discounts. Update when prices change.
"""

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def estimate_cost(model: str | None, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated USD cost, or None when the model has no known price."""
    if model is None:
        return 0.0 if input_tokens == output_tokens == 0 else None
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        return None
    return round((input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000, 6)
