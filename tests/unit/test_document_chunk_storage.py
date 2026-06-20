from __future__ import annotations

from apps.worker.activities import document_chunks
from apps.worker.activities.ingestion_types import ChunkBatch, IngestionInput


class _ChunkStorageSession:
    def __init__(self) -> None:
        self.statements = []
        self.rows = []

    async def execute(self, statement):
        self.statements.append(statement)

    def add_all(self, rows) -> None:
        self.rows = list(rows)


class _ChunkStorageTenantSession:
    def __init__(self, session: _ChunkStorageSession) -> None:
        self.session = session

    async def __aenter__(self) -> _ChunkStorageSession:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


async def test_store_chunk_batch_deletes_existing_chunks_before_insert(monkeypatch) -> None:
    session = _ChunkStorageSession()
    input = IngestionInput(
        document_id="5ef2d843-ddaf-4ae3-a73d-d25f27fb8621",
        tenant_id="tenant-a",
        object_key="tenant-a/source.txt",
        filename="GitHub_acme_docs.txt",
    )
    batch = ChunkBatch(
        contents=["fresh chunk one", "fresh chunk two"],
        embeddings=[[0.1, 0.2], [0.3, 0.4]],
        metadata=[{"source_url": "https://example.com/one.png"}, {"page": 2}],
        summary="Fresh summary",
        suggested_questions=["Fresh question?"],
        warnings=["1 URL image processed, 1 skipped"],
    )

    monkeypatch.setattr(
        document_chunks,
        "tenant_session",
        lambda _tenant_id: _ChunkStorageTenantSession(session),
    )

    written = await document_chunks.store_chunk_batch(input, batch)

    assert written == 2
    assert len(session.statements) == 2
    assert "DELETE FROM chunks" in str(session.statements[0])
    assert "UPDATE documents" in str(session.statements[1])
    assert "warnings" in str(session.statements[1])
    assert [row.chunk_idx for row in session.rows] == [0, 1]
    assert [row.content for row in session.rows] == ["fresh chunk one", "fresh chunk two"]
    assert session.rows[0].chunk_metadata == {
        "filename": "GitHub_acme_docs.txt",
        "source_url": "https://example.com/one.png",
    }
    assert session.rows[1].chunk_metadata == {
        "filename": "GitHub_acme_docs.txt",
        "page": 2,
    }
