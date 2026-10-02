from __future__ import annotations

import uuid

from fastapi import HTTPException
from packages.auth import Actor
from packages.rag import NotebookInsightSource
from packages.storage import Chunk, Document, Notebook, NotebookDocument
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.access import accessible_condition, scope_condition


def dedupe_uuid_list(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    deduped: list[uuid.UUID] = []
    for item in ids:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def clean_notebook_title(title: str) -> str:
    cleaned = title.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="title must not be empty")
    return cleaned


async def load_tenant_documents(
    db: AsyncSession,
    tenant_id: str,
    document_ids: list[uuid.UUID],
    actor: Actor | None = None,
) -> list[Document]:
    """Fetch documents by id, restricted to what the actor may attach."""
    if not document_ids:
        return []
    stmt = select(Document).where(Document.id.in_(document_ids), Document.tenant_id == tenant_id)
    if actor is not None and (condition := accessible_condition(Document, actor)) is not None:
        stmt = stmt.where(condition)
    rows = (await db.execute(stmt.order_by(Document.created_at.desc()))).scalars().all()
    if len(rows) != len(document_ids):
        raise HTTPException(status_code=404, detail="one or more documents not found")
    by_id = {doc.id: doc for doc in rows}
    return [by_id[doc_id] for doc_id in document_ids]


async def load_notebook_documents(
    db: AsyncSession,
    tenant_id: str,
    notebook_id: uuid.UUID,
    actor: Actor | None = None,
) -> list[Document]:
    """Documents linked to a notebook, filtered to the actor's knowledge base."""
    stmt = (
        select(Document)
        .join(NotebookDocument, NotebookDocument.document_id == Document.id)
        .where(
            NotebookDocument.notebook_id == notebook_id,
            NotebookDocument.tenant_id == tenant_id,
            Document.tenant_id == tenant_id,
        )
    )
    if actor is not None and (condition := accessible_condition(Document, actor)) is not None:
        stmt = stmt.where(condition)
    return list(
        (await db.execute(stmt.order_by(NotebookDocument.created_at, Document.created_at.desc())))
        .scalars()
        .all()
    )


async def load_notebooks_with_documents(
    db: AsyncSession,
    *,
    tenant_id: str,
    limit: int,
    offset: int,
    actor: Actor | None = None,
    scope: str = "all",
) -> list[tuple[Notebook, list[Document]]]:
    stmt = select(Notebook).where(Notebook.tenant_id == tenant_id)
    if actor is not None and (condition := scope_condition(Notebook, actor, scope)) is not None:
        stmt = stmt.where(condition)
    notebooks = (
        (await db.execute(stmt.order_by(Notebook.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    if not notebooks:
        return []

    notebook_ids = [notebook.id for notebook in notebooks]
    documents_by_notebook: dict[uuid.UUID, list[Document]] = {
        notebook_id: [] for notebook_id in notebook_ids
    }
    doc_stmt = (
        select(NotebookDocument.notebook_id, Document)
        .select_from(NotebookDocument)
        .join(Document, NotebookDocument.document_id == Document.id)
        .where(
            NotebookDocument.notebook_id.in_(notebook_ids),
            NotebookDocument.tenant_id == tenant_id,
            Document.tenant_id == tenant_id,
        )
    )
    if actor is not None and (doc_condition := accessible_condition(Document, actor)) is not None:
        doc_stmt = doc_stmt.where(doc_condition)
    rows = (
        await db.execute(
            doc_stmt.order_by(
                NotebookDocument.notebook_id,
                NotebookDocument.created_at,
                Document.created_at.desc(),
            )
        )
    ).all()
    for notebook_id, document in rows:
        documents_by_notebook.setdefault(notebook_id, []).append(document)

    return [(notebook, documents_by_notebook.get(notebook.id, [])) for notebook in notebooks]


async def load_notebook_insight_sources(
    db: AsyncSession,
    *,
    tenant_id: str,
    documents: list[Document],
) -> list[NotebookInsightSource]:
    if not documents:
        return []

    document_ids = [doc.id for doc in documents]
    chunks = (
        (
            await db.execute(
                select(Chunk)
                .where(
                    Chunk.document_id.in_(document_ids),
                    Chunk.tenant_id == tenant_id,
                )
                .order_by(Chunk.document_id, Chunk.chunk_idx)
            )
        )
        .scalars()
        .all()
    )
    chunks_by_document: dict[uuid.UUID, list[str]] = {
        document_id: [] for document_id in document_ids
    }
    for chunk in chunks:
        chunks_by_document.setdefault(chunk.document_id, []).append(chunk.content)

    return [
        NotebookInsightSource(
            filename=doc.filename,
            summary=doc.summary or "",
            suggested_questions=doc.suggested_questions or [],
            chunks=chunks_by_document.get(doc.id, []),
        )
        for doc in documents
    ]
