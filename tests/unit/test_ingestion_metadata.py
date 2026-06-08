from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from temporalio.converter import default

from apps.worker.activities import ingestion
from apps.worker.activities.ingestion import (
    IngestionInput,
    ParsedDoc,
    chunk_and_embed,
    mark_done,
)
from packages.rag.parser import ParsedSegment
from packages.rag.summaries import DocumentInsights


def test_parsed_doc_round_trips_through_temporal_payload_converter() -> None:
    converter = default().payload_converter
    parsed = ParsedDoc(
        segments=[
            ParsedSegment(
                text="Page four evidence.",
                metadata={"page": 4},
            )
        ],
        insights=DocumentInsights(summary="Page four evidence summary."),
    )

    payloads = converter.to_payloads([parsed])
    [decoded] = converter.from_payloads(payloads, type_hints=[ParsedDoc])

    assert decoded.segments[0].text == "Page four evidence."
    assert decoded.segments[0].metadata == {"page": 4}
    assert decoded.insights.summary == "Page four evidence summary."


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
    def __init__(self, results=None) -> None:
        self.results = list(results or [])
        self.statements = []

    async def execute(self, statement) -> None:
        self.statements.append(statement)
        if self.results:
            return self.results.pop(0)
        return None


class _FakeTenantSession:
    def __init__(self, results=None) -> None:
        self.session = _FakeSession(results)

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


async def test_mark_done_invalidates_tenant_semantic_cache(monkeypatch) -> None:
    tenant_session = _FakeTenantSession([None, _ScalarListResult([])])
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


class _ScalarListResult:
    def __init__(self, values) -> None:
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


async def test_mark_done_refreshes_linked_notebook_insights(monkeypatch) -> None:
    document_id = "5ef2d843-ddaf-4ae3-a73d-d25f27fb8621"
    notebook = SimpleNamespace(
        id="notebook-a",
        title="Product research",
        summary="Old stale overview.",
        suggested_questions=["Old question?"],
        key_topics=["Old"],
        insights_updated_at=None,
        updated_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
    )
    documents = [
        SimpleNamespace(
            filename="q1.pdf",
            summary="Revenue grew by 24 percent in Q1. Enterprise demand improved.",
            suggested_questions=["Какие факты есть в q1.pdf?"],
        ),
        SimpleNamespace(
            filename="plan.md",
            summary="Expansion focuses on enterprise customers and onboarding.",
            suggested_questions=["Какие выводы можно сделать из plan.md?"],
        ),
    ]
    tenant_session = _FakeTenantSession(
        [
            None,
            _ScalarListResult([notebook]),
            _ScalarListResult(documents),
        ]
    )

    monkeypatch.setattr(ingestion, "tenant_session", lambda tenant_id: tenant_session)

    async def fake_clear(tenant_id: str) -> None:
        return None

    monkeypatch.setattr(ingestion.semantic_cache, "clear", fake_clear)

    await mark_done(
        IngestionInput(
            document_id=document_id,
            tenant_id="tenant-a",
            object_key="tenant-a/file.pdf",
            filename="file.pdf",
        )
    )

    assert notebook.summary.startswith("q1.pdf: Revenue grew by 24 percent in Q1.")
    assert notebook.suggested_questions == [
        "Что объединяет документы в Product research?",
        "Какие ключевые темы повторяются в Product research?",
        "Какие выводы можно сделать по коллекции Product research?",
    ]
    assert "Revenue" in notebook.key_topics
    assert notebook.insights_updated_at is not None
