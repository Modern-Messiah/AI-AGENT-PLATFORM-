"""Query expansion: paraphrases and cross-lingual variants for weak retrievals.

When the primary retrieval comes back weak (below the trigger score), the
weak model generates search variants: synonym paraphrases in the query's
language plus — for mixed-language corpora — one translation into the
other corpus language. Retrieval runs per variant and the results are
RRF-merged. Best-effort by design: any failure returns just the original
query, and the whole path is disabled for single-document scopes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy import select

from packages.core import settings
from packages.llm import complete_chat_json
from packages.rag.lang import detect_language
from packages.rag.retriever import (
    RetrievedChunk,
    merge_variant_results,
    rerank_chunks,
    retrieve_chunks,
)
from packages.storage import Chunk
from packages.storage.db import tenant_session

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You generate search query variants for a knowledge base. Given a "
    "question, produce up to two paraphrases that replace words with common "
    "synonyms and spell out abbreviations, keeping the question's language. "
    "When a target_language is provided, you MUST also set the translation "
    "field to ONE faithful translation of the question into that language "
    "(null otherwise). Never answer the question. Respond with JSON: "
    '{"variants": ["...", "..."], "translation": "..." | null}'
)


def _target_language(query: str, corpus_langs: Sequence[str | None]) -> str | None:
    query_lang = detect_language(query)
    if query_lang is None:
        return None
    for lang in corpus_langs:
        if lang and lang != query_lang:
            return lang
    return None


async def expand_query(
    query: str,
    *,
    corpus_langs: Sequence[str | None] = (),
    complete_json: Callable[..., Awaitable[str]] | None = None,
) -> list[str]:
    """Return search variants, always starting with the original query."""
    if not settings.query_expansion_enabled:
        return [query]
    target = _target_language(query, corpus_langs)
    try:
        raw = await asyncio.wait_for(
            (complete_json or complete_chat_json)(
                settings.weak_model,
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "question": query,
                                "target_language": target,
                                "max_variants": 3,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                max_tokens=300,
            ),
            timeout=settings.query_expansion_timeout_seconds,
        )
        parsed = json.loads(raw)
        variants = [
            variant.strip()
            for variant in parsed.get("variants", [])
            if isinstance(variant, str) and variant.strip()
        ]
        if target:
            translation = parsed.get("translation")
            if isinstance(translation, str) and translation.strip():
                variants.append(translation.strip())
    except Exception as exc:
        log.warning("LLM feature degraded: query expansion fell back to the original query | error=%s", type(exc).__name__)
        return [query]

    # cap the paraphrases, then keep the translation even when the cap
    # is tight — cross-lingual coverage outranks a third synonym
    paraphrases = variants[:-1] if target else variants
    translation = variants[-1] if target else None
    # reserve a slot for the translation only when one is expected
    paraphrase_cap = (
        settings.query_expansion_variants - 2 if target else settings.query_expansion_variants - 1
    )
    seen = {query.casefold()}
    unique = [query]
    for variant in paraphrases[:paraphrase_cap]:
        folded = variant.casefold()
        if folded not in seen:
            seen.add(folded)
            unique.append(variant)
    if translation and translation.casefold() not in seen:
        unique.append(translation)
    return unique


async def retrieve_chunks_with_expansion(
    query: str,
    tenant_id: str,
    *,
    k: int | None = None,
    max_distance: float | None = None,
    document_id: str | None = None,
    document_ids: Sequence[str] | None = None,
    corpus_langs: Sequence[str | None] = (),
) -> list[RetrievedChunk]:
    """retrieve_chunks, escalating to variant search when results look weak.

    Single-document scopes skip the escalation: the user explicitly chose
    the document and the distance cutoff is already disabled there.
    """
    primary = await retrieve_chunks(
        query,
        tenant_id,
        k=k,
        max_distance=max_distance,
        document_id=document_id,
        document_ids=document_ids,
    )
    if document_id is not None or not settings.query_expansion_enabled:
        return primary
    if primary and max(chunk.score for chunk in primary) >= settings.query_expansion_trigger_score:
        return primary

    if not corpus_langs:
        async with tenant_session(tenant_id) as db:
            corpus_langs = [
                row
                for row in (
                    await db.execute(
                        select(Chunk.chunk_metadata["lang"].astext).where(
                            Chunk.tenant_id == tenant_id
                        )
                    )
                ).scalars()
                if row
            ]
    variants = await expand_query(query, corpus_langs=corpus_langs)
    if len(variants) == 1:
        return primary

    variant_results: list[list[RetrievedChunk]] = [primary]
    for variant in variants[1:]:
        result = await retrieve_chunks(
            variant,
            tenant_id,
            k=k,
            max_distance=max_distance,
            document_id=document_id,
            document_ids=document_ids,
        )
        if result:
            variant_results.append(result)

    merged = merge_variant_results(variant_results, limit=2 * (k or settings.retrieval_top_k))
    return rerank_chunks(query, merged)
