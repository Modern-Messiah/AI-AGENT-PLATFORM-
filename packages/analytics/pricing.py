"""Cost per 1 000 000 tokens by model, in USD.

Prices are approximate and should be verified against provider billing pages.
Models are matched by the short name after the provider prefix
(e.g. "moonshot/kimi-k2-turbo-preview" → "kimi-k2-turbo-preview").
"""

from __future__ import annotations

# {model_short_name: {input_usd_per_1m, output_usd_per_1m}}
_PRICING: dict[str, dict[str, float]] = {
    "kimi-k2-turbo-preview": {"input": 0.60, "output": 2.50},
    "kimi-k2-0711-preview":  {"input": 0.60, "output": 2.50},
    "deepseek-chat":         {"input": 0.27, "output": 1.10},
    "deepseek-reasoner":     {"input": 0.55, "output": 2.19},
}
_DEFAULT = {"input": 0.50, "output": 1.50}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated cost in USD for the given token counts."""
    prices = _PRICING.get(model.split("/")[-1], _DEFAULT)
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
