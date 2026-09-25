"""Rewrite follow-up questions into standalone queries using chat history.

The streaming chat used to be stateless: a bare follow-up ("tell me more
about the second one") embedded into a vector with no context and retrieved
garbage. With a session
id the router loads recent turns, and this service asks the weak model to
resolve pronouns/ellipsis into a self-contained question used for retrieval
and the semantic cache. Best-effort by design: any failure falls back to the
raw question.
"""

from __future__ import annotations

import json
import logging

from packages.core import settings
from packages.llm import complete_chat_json

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You rewrite a follow-up question into a standalone question using the "
    'chat history. Resolve pronouns and omissions ("it", "this", "the '
    "second document\") into explicit references. Keep the user's language "
    "and intent; do not answer the question. If it is already standalone, "
    "return it unchanged. Respond with JSON: "
    '{"standalone_query": "..."}'
)
_MAX_HISTORY_MESSAGES = 10
_MAX_MESSAGE_CHARS = 400
_MAX_STANDALONE_CHARS = 2000


def render_history(history: list[tuple[str, str]]) -> str:
    """Compact oldest-first rendering of (role, content) turns."""
    lines = []
    for role, content in history[-_MAX_HISTORY_MESSAGES:]:
        content = " ".join(content.split())[:_MAX_MESSAGE_CHARS]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def condense_query(history: list[tuple[str, str]], query: str) -> str:
    """Return a standalone version of `query`, or `query` itself on any failure."""
    if not history or not settings.query_condensation_enabled:
        return query
    try:
        raw = await complete_chat_json(
            settings.weak_model,
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Chat history:\n{render_history(history)}\n\nFollow-up question: {query}"
                    ),
                },
            ],
            max_tokens=300,
        )
        standalone = str(json.loads(raw).get("standalone_query", "")).strip()
        if not standalone:
            return query
        log.info("query condensed | original=%r standalone=%r", query[:80], standalone[:80])
        return standalone[:_MAX_STANDALONE_CHARS]
    except Exception as exc:  # condensation must never break the chat
        log.warning(
            "LLM feature degraded: query condensation fell back to the raw query | error=%s",
            type(exc).__name__,
        )
        return query
