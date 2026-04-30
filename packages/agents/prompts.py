"""Fetch system prompts from Langfuse with a hardcoded fallback.

Langfuse stores prompts under a name + label (e.g. "research-agent" / "production").
The SDK caches responses internally so each call does not hit the network.
If Langfuse is unreachable or the prompt doesn't exist yet, the fallback is used.
"""

from __future__ import annotations

import logging
from functools import lru_cache

log = logging.getLogger(__name__)

FALLBACK_SYSTEM_PROMPT = """\
You are a helpful research assistant grounded in the user's knowledge base.

Available tools:
- retrieve      : search the vector knowledge base for relevant chunks
- sql_query     : run a SELECT against the documents/chunks tables
- http_fetch    : fetch content from an external URL
- code_exec     : run a Python snippet for computation or data transformation

When answering:
1. Call retrieve first for knowledge-base questions.
2. Use sql_query to look up document metadata or counts.
3. Use http_fetch only when you need fresh external content.
4. Use code_exec for calculations or non-trivial data wrangling.

Always set confidence in [0,1]. In sources, list ONLY the filename of each
document whose content you directly cited or paraphrased in your answer.
If a retrieved chunk was not helpful, do not include its filename. Never invent filenames.
"""


@lru_cache(maxsize=1)
def _langfuse():  # type: ignore[return]
    from langfuse import Langfuse

    from packages.core import settings

    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )


def get_system_prompt(
    name: str = "research-agent",
    label: str = "production",
) -> str:
    """Return the compiled prompt from Langfuse, or the fallback if unavailable."""
    from packages.core import settings

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return FALLBACK_SYSTEM_PROMPT

    try:
        prompt = _langfuse().get_prompt(name, label=label, fallback=FALLBACK_SYSTEM_PROMPT)
        return prompt.compile()
    except Exception as exc:  # noqa: BLE001
        log.warning("Langfuse prompt fetch failed (%s) — using fallback", exc)
        return FALLBACK_SYSTEM_PROMPT
