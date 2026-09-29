"""Stage-2 LLM reranker — the precision half of two-stage retrieval.

Stage 1 (hybrid vector+FTS with a wide candidate pool) optimises recall;
this module optimises precision: a weak model reads the user's question
next to each candidate chunk and scores how well the chunk helps answer
THAT question — the cross-encoder view that bi-encoder retrieval cannot
have. Deterministic rerank stays as the ordering fallback, so a verifier
outage degrades to the previous behaviour, never to an error.

Kill-switch: LLM_RERANK_ENABLED=false restores the single-stage pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging

from packages.core import settings
from packages.llm.client import complete_chat_json
from packages.rag.retriever import RetrievedChunk

log = logging.getLogger(__name__)

_EXCERPT_CHARS = 400

_RERANKER_PROMPT = (
    "You are a relevance judge for knowledge-base retrieval. The user "
    "question is given, followed by numbered candidate chunks.\n"
    "Score EACH chunk 0-10 for how well it helps answer the question:\n"
    "10 = directly contains the answer or its key fact; 7-9 = substantially "
    "relevant; 4-6 = same topic but not the asked fact; 1-3 = tangential; "
    "0 = unrelated.\n"
    "Judge only relevance to THIS question — general quality does not "
    'matter. Respond with JSON: {"scores": {"1": 9, "2": 3, ...}} '
    "with a score for every chunk number."
)


async def rerank_chunks_with_llm(
    query: str, chunks: list[RetrievedChunk]
) -> list[RetrievedChunk] | None:
    """Reorder chunks by LLM-judged relevance; None = use the fallback order."""
    if not settings.llm_rerank_enabled or len(chunks) < 2:
        return None

    candidates = chunks[: settings.llm_rerank_max_chunks]
    numbered = "\n\n".join(
        f"[{i}] {chunk.content[:_EXCERPT_CHARS]}" for i, chunk in enumerate(candidates, 1)
    )
    messages = [
        {"role": "system", "content": _RERANKER_PROMPT},
        {"role": "user", "content": f"Question:\n{query}\n\nCandidate chunks:\n{numbered}"},
    ]
    try:
        raw = await asyncio.wait_for(
            complete_chat_json(settings.weak_model, messages, max_tokens=800),
            timeout=settings.llm_rerank_timeout_seconds,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        scores = {str(k): float(v) for k, v in dict(parsed.get("scores", {})).items()}
    except Exception as exc:
        log.warning("llm rerank fell back to deterministic order: %s", exc)
        return None

    def _score(index: int) -> float:
        return scores.get(str(index), -1.0)

    order = sorted(
        range(len(candidates)),
        key=lambda i: (_score(i + 1), candidates[i].score, -i),
        reverse=True,
    )
    reranked = [candidates[i] for i in order]
    tail = chunks[settings.llm_rerank_max_chunks :]
    judged = sum(1 for i in range(len(candidates)) if _score(i + 1) >= 0)
    log.info(
        "llm rerank | chunks=%d judged=%d top=%.0f",
        len(candidates),
        judged,
        _score(order[0] + 1) if order else -1,
    )
    return reranked + tail
