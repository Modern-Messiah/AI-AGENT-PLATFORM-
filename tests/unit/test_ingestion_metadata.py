from __future__ import annotations

from apps.worker.activities import ingestion
from apps.worker.activities.ingestion import (
    IngestionInput,
    ParsedDoc,
    chunk_and_embed,
    mark_done,
)
from packages.rag.parser import ParsedSegment
from packages.rag.summaries import DocumentInsights


async def test_chunk_and_embed_preserves_segment_metadata(monkeypatch) -> None:
    async def fake_embed_texts(contents: list[str]) -> list[list[float]]:
        return [[float(index)] for index, _ in enumerate(contents)]

    monkeypatch.setattr(ingestion, "embed_texts", fake_embed_texts)
    parsed = ParsedDoc(
        segments=[
            ParsedSegment(
                text=("Page four evidence. " * 180).strip(),
                metadata={"page": 4},
            )
        ],
        insights=DocumentInsights(
            summary="Page four evidence summary.",
            suggested_questions=["Что есть на странице 4?"],
        ),
    )

    batch = await chunk_and_embed(parsed)

    assert len(batch.contents) > 1
    assert len(batch.contents) == len(batch.embeddings) == len(batch.metadata)
    assert all(metadata == {"page": 4} for metadata in batch.metadata)
    assert batch.summary == "Page four evidence summary."
    assert batch.suggested_questions == ["Что есть на странице 4?"]


class _FakeSession:
    async def execute(self, statement) -> None:
        self.statement = statement


class _FakeTenantSession:
    def __init__(self) -> None:
        self.session = _FakeSession()

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


async def test_mark_done_invalidates_tenant_semantic_cache(monkeypatch) -> None:
    tenant_session = _FakeTenantSession()
    cleared: list[str] = []

    monkeypatch.setattr(ingestion, "tenant_session", lambda tenant_id: tenant_session)

    async def fake_clear(tenant_id: str) -> None:
        cleared.append(tenant_id)

    monkeypatch.setattr(ingestion.semantic_cache, "clear", fake_clear)

    await mark_done(
        IngestionInput(
            document_id="5ef2d843-ddaf-4ae3-a73d-d25f27fb8621",
            tenant_id="tenant-a",
            object_key="tenant-a/file.pdf",
            filename="file.pdf",
        )
    )

    assert cleared == ["tenant-a"]
