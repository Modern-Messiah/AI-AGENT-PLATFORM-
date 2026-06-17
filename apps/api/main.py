"""FastAPI entrypoint.

Auth: every endpoint (except /health and /auth/keys) requires
  X-API-Key: <raw key>
Keys are created via POST /auth/keys (protected by X-Admin-Secret header).

Endpoints:
  POST /agent/run                    — single agent run (optional require_approval)
  POST /agent/research               — multi-step research via child workflows
  GET  /workflows/{id}/result        — poll HITL workflow result
  POST /workflows/{id}/approve       — send approve signal (HITL)
  POST /workflows/{id}/reject        — send reject signal (HITL)
  POST /documents                    — upload file, kick off IngestionWorkflow
  POST /documents/bulk               — upload multiple files
  GET  /documents/{id}               — ingestion status
  GET  /documents/{id}/chunks        — indexed chunk previews for one document
  POST /documents/{id}/reindex       — rebuild chunks/embeddings for existing file
  GET  /notebooks                    — list document collections
  POST /notebooks                    — create a document collection
  GET  /notebooks/{id}               — collection detail
  PUT  /notebooks/{id}/documents     — replace collection documents
  POST /notebooks/{id}/documents/upload — upload and attach a file
  POST /notebooks/{id}/insights      — rebuild collection overview
  GET  /analytics/usage              — cost/token aggregate for a tenant
  POST /auth/keys                    — create an API key (admin only)
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from packages.core import settings
from packages.observability import setup_tracing
from packages.rag.embedder import embed_texts
from temporalio.client import Client

from apps.api.routers import (
    agent_router,
    analytics_router,
    auth_router,
    documents_router,
    health_router,
    notebooks_router,
    sessions_router,
    workflows_router,
)
from apps.api.schemas import (
    AddMessageRequest,
    AddUrlDocumentRequest,
    AgentRunApiResponse,
    AgentStreamRequest,
    ChatMessageSchema,
    ChatSessionSchema,
    CreateKeyRequest,
    CreateKeyResponse,
    CreateNotebookRequest,
    CreateSessionRequest,
    DocumentAssetResponse,
    DocumentChunkPreview,
    DocumentResponse,
    NotebookResponse,
    UrlCheckRequest,
    UrlCheckResponse,
    UpdateSessionRequest,
    UpdateNotebookDocumentsRequest,
    WorkflowSignalResponse,
)
from apps.api.serializers import (
    document_response,
    notebook_response,
    serialize_sources,
)
from apps.api.services.notebooks import (
    clean_notebook_title,
    dedupe_uuid_list,
    load_notebook_documents,
    load_notebook_insight_sources,
    load_tenant_documents,
)
from apps.api.services.agent_limits import (
    check_agent_rate_limit,
    enforce_agent_limits,
    validate_agent_query,
)

# Backward-compatible names imported by existing tests and scripts.
_document_response = document_response
_notebook_response = notebook_response
_clean_notebook_title = clean_notebook_title
_dedupe_uuid_list = dedupe_uuid_list
_load_notebook_documents = load_notebook_documents
_load_notebook_insight_sources = load_notebook_insight_sources
_load_tenant_documents = load_tenant_documents
_serialize_sources = serialize_sources
_validate_agent_query = validate_agent_query
_check_agent_rate_limit = check_agent_rate_limit
_enforce_agent_limits = enforce_agent_limits

logging.basicConfig(level=settings.log_level)
log = logging.getLogger(__name__)


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_tracing("aap-api")
    log.info("warming up embedding model...")
    try:
        await embed_texts(["warmup"])
        log.info("embedding model ready")
    except Exception as exc:  # noqa: BLE001
        log.warning("embedding model warmup failed (%s) — will retry on first use", exc)
    app.state.temporal = await Client.connect(
        settings.temporal_address, namespace=settings.temporal_namespace
    )
    yield


app = FastAPI(title="AI Agent Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(agent_router)
app.include_router(analytics_router)
app.include_router(documents_router)
app.include_router(notebooks_router)
app.include_router(sessions_router)
app.include_router(workflows_router)
