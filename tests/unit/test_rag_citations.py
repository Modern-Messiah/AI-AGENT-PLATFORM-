from __future__ import annotations

import asyncio

import fitz
from packages.rag.chunker import chunk_segments
from packages.rag.citations import (
    build_citations,
    build_grounded_messages,
    select_diverse_chunks,
)
from packages.rag.parser import ParsedSegment, parse_to_segments
from packages.rag.retriever import RetrievedChunk


def _chunk(
    chunk_id: str,
    document_id: str,
    filename: str,
    score: float,
    *,
    chunk_idx: int = 0,
    page: int | None = None,
) -> RetrievedChunk:
    metadata = {"filename": filename}
    if page is not None:
        metadata["page"] = page
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        filename=filename,
        content=f"Evidence from {filename}, chunk {chunk_idx}.",
        score=score,
        metadata=metadata,
        chunk_idx=chunk_idx,
    )


def test_pdf_parser_preserves_one_based_page_numbers_and_skips_empty_pages() -> None:
    document = fitz.open()
    page_one = document.new_page()
    page_one.insert_text((72, 72), "First page evidence")
    document.new_page()
    page_three = document.new_page()
    page_three.insert_text((72, 72), "Third page evidence")
    data = document.tobytes()
    document.close()

    segments = asyncio.run(parse_to_segments(data, "evidence.pdf"))

    assert [segment.text for segment in segments] == [
        "First page evidence",
        "Third page evidence",
    ]
    assert [segment.metadata for segment in segments] == [{"page": 1}, {"page": 3}]


def test_chunk_segments_preserves_source_metadata() -> None:
    segments = [
        ParsedSegment(
            text=("Page seven sentence. " * 180).strip(),
            metadata={"page": 7},
        )
    ]

    chunks = chunk_segments(segments)

    assert len(chunks) > 1
    assert all(chunk.metadata == {"page": 7} for chunk in chunks)
    assert all(chunk.content for chunk in chunks)


def test_select_diverse_chunks_uses_multiple_documents_and_deduplicates() -> None:
    candidates = [
        _chunk("a1", "doc-a", "a.pdf", 0.95, chunk_idx=1),
        _chunk("a2", "doc-a", "a.pdf", 0.94, chunk_idx=2),
        _chunk("a3", "doc-a", "a.pdf", 0.93, chunk_idx=3),
        _chunk("b1", "doc-b", "b.pdf", 0.92, chunk_idx=1),
        _chunk("b1", "doc-b", "b.pdf", 0.91, chunk_idx=1),
        _chunk("c1", "doc-c", "c.pdf", 0.90, chunk_idx=1),
    ]

    selected = select_diverse_chunks(candidates, limit=4, per_document=2)

    assert [chunk.chunk_id for chunk in selected] == ["a1", "a2", "b1", "c1"]
    assert {chunk.document_id for chunk in selected} == {"doc-a", "doc-b", "doc-c"}


def test_build_citations_retains_exact_chunk_location_and_excerpt() -> None:
    chunks = [
        _chunk(
            "chunk-8",
            "document-2",
            "contract.pdf",
            0.84,
            chunk_idx=14,
            page=8,
        )
    ]

    citations = build_citations(chunks)

    assert [citation.model_dump() for citation in citations] == [
        {
            "id": 1,
            "document_id": "document-2",
            "chunk_id": "chunk-8",
            "filename": "contract.pdf",
            "page": 8,
            "chunk_index": 14,
            "excerpt": "Evidence from contract.pdf, chunk 14.",
            "score": 0.84,
        }
    ]


def test_grounded_prompt_numbers_sources_and_requires_inline_markers() -> None:
    citations = build_citations(
        [
            _chunk(
                "chunk-8",
                "document-2",
                "contract.pdf",
                0.84,
                chunk_idx=14,
                page=8,
            )
        ]
    )

    messages = build_grounded_messages(
        "When can the contract be terminated?",
        citations,
        max_context_chars=8_000,
    )

    assert "append its citation marker like [1]" in messages[0]["content"]
    assert "[1] contract.pdf (page 8, score=0.840)" in messages[1]["content"]
    assert "Evidence from contract.pdf, chunk 14." in messages[1]["content"]
