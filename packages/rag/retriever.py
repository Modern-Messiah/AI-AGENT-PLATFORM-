"""Hybrid retrieval: pgvector neighbours fused with PostgreSQL full-text matches."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select

from packages.core import settings
from packages.rag.embedder import embed_queries
from packages.storage import Chunk, Document
from packages.storage.db import tenant_session


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    filename: str
    content: str
    score: float
    metadata: dict[str, object]
    chunk_idx: int = 0


_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = {
    "and",
    "for",
    "from",
    "how",
    "the",
    "what",
    "when",
    "where",
    "with",
    "для",
    "как",
    "какие",
    "какой",
    "что",
    "это",
}
_DOCUMENT_METADATA_TERMS = {
    "author",
    "автор",
    "date",
    "дата",
    "version",
    "верси",
}
_TITLE_PAGE_QUERY_TERMS = {
    "cover",
    "document",
    "page",
    "title",
    "документ",
    "лист",
    "страниц",
    "титульн",
}
_RUSSIAN_SUFFIXES = (
    "иями",
    "ями",
    "ами",
    "ого",
    "ему",
    "ому",
    "ыми",
    "ими",
    "ий",
    "ый",
    "ая",
    "яя",
    "ое",
    "ее",
    "ие",
    "ые",
    "ов",
    "ев",
    "ам",
    "ям",
    "ах",
    "ях",
    "ом",
    "ем",
    "ой",
    "ей",
    "у",
    "ю",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "о",
)


def _normalize_term(term: str) -> str:
    normalized = term.casefold().replace("ё", "е")
    if normalized.isdigit() or len(normalized) <= 4:
        return normalized
    for suffix in _RUSSIAN_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 4:
            return normalized[: -len(suffix)]
    return normalized


def _lexical_terms(text: str) -> list[str]:
    return [
        normalized
        for raw in _WORD_RE.findall(text)
        if (normalized := _normalize_term(raw)) not in _STOP_WORDS
        and (len(normalized) >= 3 or normalized.isdigit())
    ]


def _lexical_relevance(query: str, content: str) -> float:
    query_terms = _lexical_terms(query)
    if not query_terms:
        return 0.0
    content_terms = _lexical_terms(content)
    if not content_terms:
        return 0.0

    query_set = set(query_terms)
    content_set = set(content_terms)
    term_coverage = len(query_set & content_set) / len(query_set)

    query_pairs = set(zip(query_terms, query_terms[1:], strict=False))
    content_pairs = set(zip(content_terms, content_terms[1:], strict=False))
    pair_coverage = len(query_pairs & content_pairs) / len(query_pairs) if query_pairs else 0.0
    return min(1.0, term_coverage * 0.8 + pair_coverage * 0.2)


def _title_page_metadata_relevance(query: str, chunk: RetrievedChunk) -> float:
    page = chunk.metadata.get("page")
    if page != 1 and chunk.chunk_idx != 0:
        return 0.0

    query_terms = set(_lexical_terms(query))
    metadata_hits = len(query_terms & _DOCUMENT_METADATA_TERMS)
    title_hits = len(query_terms & _TITLE_PAGE_QUERY_TERMS)
    if metadata_hits >= 2 and title_hits:
        return 0.45
    if metadata_hits >= 2:
        return 0.30
    if metadata_hits and title_hits:
        return 0.25
    return 0.0


def rerank_chunks(query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Blend semantic distance with deterministic Unicode lexical relevance."""
    return sorted(
        chunks,
        key=lambda chunk: (
            chunk.score
            + 0.35 * _lexical_relevance(query, chunk.content)
            + _title_page_metadata_relevance(query, chunk),
            chunk.score,
            -chunk.chunk_idx,
        ),
        reverse=True,
    )


def filter_unsupported_query_chunks(
    query: str,
    chunks: list[RetrievedChunk],
    *,
    min_semantic_score_without_lexical_support: float = 0.55,
) -> list[RetrievedChunk]:
    """Drop unscoped nearest-neighbour noise for clearly unsupported queries.

    Vector search always has a nearest chunk, even for questions outside the
    corpus. If none of the retrieved chunks share meaningful lexical evidence
    with the query and the semantic scores are weak, treat the result as no
    knowledge instead of handing random context to the agent.
    """
    if not chunks:
        return []
    if any(_lexical_relevance(query, chunk.content) > 0 for chunk in chunks):
        return chunks
    if max(chunk.score for chunk in chunks) >= min_semantic_score_without_lexical_support:
        return chunks
    return []


def candidate_limit_for_scope(
    *,
    default_limit: int,
    scoped_limit: int,
    document_id: str | uuid.UUID | None,
    document_ids: Sequence[str | uuid.UUID] | None,
) -> int:
    if document_id is not None or document_ids:
        return max(default_limit, scoped_limit)
    return default_limit


def effective_max_distance_for_scope(
    *,
    configured_max_distance: float,
    document_id: str | uuid.UUID | None,
    document_ids: Sequence[str | uuid.UUID] | None,
) -> float:
    if document_id is not None:
        return 0
    if document_ids is not None and len(document_ids) == 1:
        return 0
    return configured_max_distance


def rrf_merge(
    *ranked_lists: Sequence[str],
    k: int = 60,
    limit: int | None = None,
) -> list[str]:
    """Reciprocal-rank fusion of any number of ranked id lists.

    Lists are ordered best-first. An id found by only one list still gets
    its single-list contribution, which is exactly how exact-term matches
    the vector search missed become reachable again.
    """
    scores: dict[str, float] = {}
    for ids in ranked_lists:
        for rank, chunk_id in enumerate(ids):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    ordered = sorted(scores, key=lambda cid: (-scores[cid], cid))
    return ordered[:limit] if limit is not None else ordered


def _fts_terms(query: str) -> list[str]:
    """Sanitized query terms for OR-mode to_tsquery (word characters only)."""
    return _lexical_terms(query)[:8]


def _fts_queries(query: str) -> tuple[ColumnElement[bool], ColumnElement[bool]] | None:
    """OR-mode tsqueries over both configs.

    websearch_to_tsquery ANDs every word — a query like "which model is
    used by default" matched nothing unless the chunk contained ALL terms.
    OR-mode lets partial lexical evidence enter the pool; ts_rank_cd then
    ranks full matches above single-word noise. Terms come from
    _lexical_terms (\\w+ only), so the to_tsquery string needs no escaping.
    """
    terms = _fts_terms(query)
    if not terms:
        return None
    joined = " | ".join(terms)
    return (
        func.to_tsquery("simple", joined),
        func.to_tsquery("russian", joined),
    )


def merge_variant_results(
    variant_results: Sequence[list[RetrievedChunk]],
    *,
    limit: int,
) -> list[RetrievedChunk]:
    """RRF-merge per-variant ranked results, deduped by chunk id.

    A chunk appearing in several variants keeps its best (max) score —
    consensus across paraphrases is the signal, not one lucky embedding.
    """
    merged_ids = rrf_merge(
        *[[chunk.chunk_id for chunk in results] for results in variant_results],
        limit=limit,
    )
    by_id: dict[str, RetrievedChunk] = {}
    for results in variant_results:
        for chunk in results:
            existing = by_id.get(chunk.chunk_id)
            if existing is None or chunk.score > existing.score:
                by_id[chunk.chunk_id] = chunk
    return [by_id[chunk_id] for chunk_id in merged_ids if chunk_id in by_id]


async def retrieve_chunks(
    query: str,
    tenant_id: str,
    k: int | None = None,
    max_distance: float | None = None,
    document_id: str | uuid.UUID | None = None,
    document_ids: Sequence[str | uuid.UUID] | None = None,
) -> list[RetrievedChunk]:
    k = candidate_limit_for_scope(
        default_limit=k or settings.retrieval_top_k,
        scoped_limit=settings.scoped_rag_candidate_k,
        document_id=document_id,
        document_ids=document_ids,
    )
    max_distance = settings.retrieval_max_distance if max_distance is None else max_distance
    max_distance = effective_max_distance_for_scope(
        configured_max_distance=max_distance,
        document_id=document_id,
        document_ids=document_ids,
    )
    [query_vec] = await embed_queries([query])
    document_uuids = [uuid.UUID(str(doc_id)) for doc_id in (document_ids or [])]
    if document_id is not None:
        document_uuids = [uuid.UUID(str(document_id))]

    async with tenant_session(tenant_id) as session:
        # cosine_distance: 0 = identical, 2 = opposite. Score = 1 - distance.
        distance = Chunk.embedding.cosine_distance(query_vec)
        stmt = (
            select(Chunk, Document.filename, distance.label("distance"))
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.tenant_id == tenant_id)
            .order_by(distance)
            .limit(k)
        )
        if document_uuids:
            stmt = stmt.where(Chunk.document_id.in_(document_uuids))
        if max_distance > 0:
            stmt = stmt.where(distance <= max_distance)
        rows = (await session.execute(stmt)).all()

        # Full-text leg of the hybrid search: exact tokens and Russian
        # morphology that cosine neighbours may rank below the cutoff.
        fts_rows: Sequence[Any] = []
        queries = _fts_queries(query) if settings.hybrid_search_enabled else None
        if queries is not None:
            tsq_simple, tsq_russian = queries
            rank = (
                func.ts_rank_cd(Chunk.tsv, tsq_simple) + func.ts_rank_cd(Chunk.tsv, tsq_russian)
            ).label("rank")
            fts_stmt = (
                select(Chunk, Document.filename, distance.label("distance"), rank)
                .join(Document, Chunk.document_id == Document.id)
                .where(
                    Chunk.tenant_id == tenant_id,
                    or_(Chunk.tsv.op("@@")(tsq_simple), Chunk.tsv.op("@@")(tsq_russian)),
                )
                .order_by(rank.desc())
                .limit(k)
            )
            if document_uuids:
                fts_stmt = fts_stmt.where(Chunk.document_id.in_(document_uuids))
            fts_rows = (await session.execute(fts_stmt)).all()

    by_id: dict[str, tuple[Chunk, str, float]] = {}
    for chunk, filename, dist in rows:
        by_id[str(chunk.id)] = (chunk, filename, float(dist))
    for fts_row in fts_rows:
        chunk, filename, dist = fts_row[0], fts_row[1], fts_row[2]
        by_id.setdefault(str(chunk.id), (chunk, filename, float(dist)))

    merged_ids = rrf_merge(
        [str(chunk.id) for chunk, _, _ in rows],
        [str(fts_row[0].id) for fts_row in fts_rows],
        k=settings.hybrid_rrf_k,
        limit=2 * k,
    )

    chunks = [
        RetrievedChunk(
            chunk_id=chunk_id,
            document_id=str(by_id[chunk_id][0].document_id),
            filename=by_id[chunk_id][1],
            content=by_id[chunk_id][0].content,
            score=1.0 - by_id[chunk_id][2],
            metadata=by_id[chunk_id][0].chunk_metadata,
            chunk_idx=by_id[chunk_id][0].chunk_idx,
        )
        for chunk_id in merged_ids
    ]
    ranked = rerank_chunks(query, chunks)
    if document_uuids:
        return ranked
    return filter_unsupported_query_chunks(query, ranked)
