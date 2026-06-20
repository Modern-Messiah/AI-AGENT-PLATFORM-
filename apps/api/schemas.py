from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, model_validator

from packages.rag import CitationSource
from packages.storage import DocumentAssetStatus, DocumentStatus


class ChatMessageSchema(BaseModel):
    id: str
    role: str
    content: str
    sources: list[str | CitationSource] = []
    cached: bool = False
    created_at: str


class ChatSessionSchema(BaseModel):
    id: str
    title: str
    model: str | None
    scope_type: str | None = None
    document_id: str | None = None
    notebook_id: str | None = None
    created_at: str
    updated_at: str
    message_count: int = 0


class CreateSessionRequest(BaseModel):
    title: str = "New Chat"
    model: str | None = None
    document_id: uuid.UUID | None = None
    notebook_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_single_scope(self) -> "CreateSessionRequest":
        if self.document_id is not None and self.notebook_id is not None:
            raise ValueError("document_id and notebook_id cannot be used together")
        return self


class UpdateSessionRequest(BaseModel):
    title: str | None = None
    model: str | None = None


class AddMessageRequest(BaseModel):
    role: str
    content: str
    sources: list[str | CitationSource] = []
    cached: bool = False


class DocumentResponse(BaseModel):
    id: str
    tenant_id: str
    filename: str
    status: DocumentStatus
    size_bytes: int = 0
    source_type: str = "file"
    source_url: str | None = None
    source_title: str | None = None
    source_checked_at: str | None = None
    summary: str | None = None
    suggested_questions: list[str] = Field(default_factory=list)
    processing_stage: str = "queued"
    processed_pages: int = 0
    total_pages: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: str | None = None


class UrlCheckRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)


class AddUrlDocumentRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)


class UrlCheckResponse(BaseModel):
    ok: bool
    url: str
    final_url: str | None = None
    content_type: str | None = None
    title: str | None = None
    size_bytes: int = 0
    source_type: str = "url"
    file_count: int = 0
    preview_files: list[str] = Field(default_factory=list)
    reason: str | None = None


class DocumentAssetResponse(BaseModel):
    id: str
    document_id: str
    page_number: int | None = None
    asset_kind: str
    ocr_text: str = ""
    ocr_confidence: float | None = None
    vision_description: str = ""
    width: int = 0
    height: int = 0
    status: DocumentAssetStatus
    error: str | None = None
    preview_available: bool = False


class DocumentChunkPreview(BaseModel):
    chunk_id: str
    chunk_index: int
    page: int | None = None
    excerpt: str


class CreateNotebookRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    document_ids: list[uuid.UUID] = Field(default_factory=list)


class UpdateNotebookDocumentsRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(default_factory=list)


class NotebookResponse(BaseModel):
    id: str
    tenant_id: str
    title: str
    description: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    document_count: int = 0
    documents: list[DocumentResponse] = Field(default_factory=list)
    summary: str | None = None
    suggested_questions: list[str] = Field(default_factory=list)
    key_topics: list[str] = Field(default_factory=list)
    insights_updated_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AgentRunApiResponse(BaseModel):
    answer: str = ""
    confidence: float = 0.0
    sources: list[CitationSource] = []
    cached: bool = False
    workflow_id: str | None = None
    pending_approval: bool = False


class WorkflowSignalResponse(BaseModel):
    workflow_id: str
    action: str


class CreateKeyRequest(BaseModel):
    tenant_id: str
    name: str | None = None


class CreateKeyResponse(BaseModel):
    id: str
    tenant_id: str
    name: str | None
    raw_key: str  # shown once - store it now


class AgentStreamRequest(BaseModel):
    user_query: str
    model: str | None = None
    document_id: uuid.UUID | None = None
    notebook_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_single_scope(self) -> "AgentStreamRequest":
        if self.document_id is not None and self.notebook_id is not None:
            raise ValueError("document_id and notebook_id cannot be used together")
        return self
