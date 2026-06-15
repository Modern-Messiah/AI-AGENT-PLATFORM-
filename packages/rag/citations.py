"""Citation contracts and deterministic multi-document source selection."""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from packages.rag.retriever import RetrievedChunk


class CitationSource(BaseModel):
    id: int = Field(ge=1)
    document_id: str
    chunk_id: str
    filename: str
    page: int | None = Field(default=None, ge=1)
    asset_id: str | None = None
    asset_kind: str | None = None
    preview_available: bool = False
    chunk_index: int = Field(ge=0)
    excerpt: str
    score: float


def select_diverse_chunks(
    chunks: list[RetrievedChunk],
    *,
    limit: int,
    per_document: int,
) -> list[RetrievedChunk]:
    if limit <= 0 or per_document <= 0:
        return []

    selected: list[RetrievedChunk] = []
    seen_chunk_ids: set[str] = set()
    document_counts: defaultdict[str, int] = defaultdict(int)

    for chunk in chunks:
        if chunk.chunk_id in seen_chunk_ids:
            continue
        if document_counts[chunk.document_id] >= per_document:
            continue

        selected.append(chunk)
        seen_chunk_ids.add(chunk.chunk_id)
        document_counts[chunk.document_id] += 1
        if len(selected) >= limit:
            break

    return selected


def build_citations(chunks: list[RetrievedChunk]) -> list[CitationSource]:
    citations: list[CitationSource] = []
    for citation_id, chunk in enumerate(chunks, start=1):
        raw_page = chunk.metadata.get("page")
        page = raw_page if isinstance(raw_page, int) and raw_page > 0 else None
        raw_asset_id = chunk.metadata.get("asset_id")
        asset_id = raw_asset_id if isinstance(raw_asset_id, str) and raw_asset_id else None
        raw_asset_kind = chunk.metadata.get("asset_kind")
        asset_kind = (
            raw_asset_kind
            if isinstance(raw_asset_kind, str) and raw_asset_kind
            else None
        )
        citations.append(
            CitationSource(
                id=citation_id,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                filename=chunk.filename,
                page=page,
                asset_id=asset_id,
                asset_kind=asset_kind,
                preview_available=bool(
                    asset_id and chunk.metadata.get("preview_available") is True
                ),
                chunk_index=chunk.chunk_idx,
                excerpt=chunk.content.strip(),
                score=chunk.score,
            )
        )
    return citations


def build_grounded_messages(
    query: str,
    citations: list[CitationSource],
    *,
    max_context_chars: int,
) -> list[dict[str, str]]:
    separator = "\n\n---\n\n"
    headers: list[str] = []
    for citation in citations:
        location = (
            f"page {citation.page}"
            if citation.page is not None
            else f"chunk {citation.chunk_index}"
        )
        headers.append(
            f"[{citation.id}] {citation.filename} "
            f"({location}, score={citation.score:.3f})\n"
        )

    fixed_chars = sum(map(len, headers)) + max(0, len(headers) - 1) * len(separator)
    available_content = max(0, max_context_chars - fixed_chars)
    per_citation = available_content // len(citations) if citations else 0

    context_parts: list[str] = []
    for citation, header in zip(citations, headers, strict=True):
        content = citation.excerpt
        if len(content) > per_citation:
            content = content[:per_citation].rsplit(" ", 1)[0].strip()
            if not content and per_citation:
                content = citation.excerpt[:per_citation]
        context_parts.append(f"{header}{content}")

    context = separator.join(context_parts)
    return [
        {
            "role": "system",
            "content": (
                "You are a concise research assistant. Answer only from the provided "
                "knowledge-base context. For every factual claim, append its citation "
                "marker like [1] immediately after the supported sentence. You may cite "
                "multiple sources. If the context is insufficient, say so directly. "
                "Never invent facts, citation numbers, or filenames."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question:\n{query}\n\n"
                f"Numbered knowledge-base context:\n{context}\n\n"
                "Answer in the user's language. Keep it clear and practical."
            ),
        },
    ]
