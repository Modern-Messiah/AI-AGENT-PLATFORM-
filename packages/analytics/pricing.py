"""Cost per 1 000 000 tokens by model, in USD.

Prices are approximate and should be verified against provider billing pages.
Models are matched by the short name after the provider prefix
(e.g. "moonshot/kimi-k2.6" → "kimi-k2.6").

Sources (checked 2026-06-08):
  Moonshot: https://platform.moonshot.ai/docs/pricing
  DeepSeek:  https://api-docs.deepseek.com/quick_start/pricing
"""

from __future__ import annotations

# {model_short_name: {input_usd_per_1m, output_usd_per_1m}}
_PRICING: dict[str, dict[str, float]] = {
    # ── Moonshot / Kimi ──────────────────────────────────────────────────────
    "kimi-k2.6":             {"input": 0.60, "output": 2.50},
    "kimi-k2.5":             {"input": 0.60, "output": 2.50},
    "kimi-k2-turbo-preview": {"input": 0.60, "output": 2.50},
    "kimi-k2-0711-preview":  {"input": 0.60, "output": 2.50},

    # ── DeepSeek ─────────────────────────────────────────────────────────────
    # Current official V4-Pro rates: cache-miss input $0.435 / output $0.87.
    "deepseek-v4-pro":       {"input": 0.435, "output": 0.87},
    "deepseek-v4-flash":     {"input": 0.14,  "output": 0.28},
    "deepseek-chat":         {"input": 0.14,  "output": 0.28},  # aliases to v4-flash
    "deepseek-reasoner":     {"input": 0.55,  "output": 2.19},  # deepseek-r1
}
_DEFAULT = {"input": 0.50, "output": 1.50}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated cost in USD for the given token counts."""
    prices = _PRICING.get(model.split("/")[-1], _DEFAULT)
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
