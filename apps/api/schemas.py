from __future__ import annotations

import uuid
from datetime import datetime

from packages.rag import CitationSource
from packages.storage import DocumentAssetStatus, DocumentStatus
from pydantic import BaseModel, EmailStr, Field, model_validator


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
    def validate_single_scope(self) -> CreateSessionRequest:
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


class DocumentReindexResponse(BaseModel):
    document: DocumentResponse
    changed: bool = True
    workflow_started: bool = True


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
    image_count: int = 0
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
    user_id: uuid.UUID | None = None


class CreateKeyResponse(BaseModel):
    id: str
    tenant_id: str
    name: str | None
    raw_key: str  # shown once - store it now


class CreateUserRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    role: str = Field(default="member", pattern="^(member|admin)$")


class UserInfo(BaseModel):
    id: str
    tenant_id: str
    name: str
    role: str
    created_at: datetime


class ApiKeyInfo(BaseModel):
    """Admin-facing key view: no hashes, no raw keys."""

    id: str
    tenant_id: str
    name: str | None = None
    user_id: str | None = None
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None


class AgentStreamRequest(BaseModel):
    user_query: str
    model: str | None = None
    session_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    notebook_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_single_scope(self) -> AgentStreamRequest:
        if self.document_id is not None and self.notebook_id is not None:
            raise ValueError("document_id and notebook_id cannot be used together")
        return self


# ── Admin panel ──────────────────────────────────────────────────────────────


class AdminDocumentCounts(BaseModel):
    total: int
    done: int
    processing: int
    failed: int
    pending: int


class AdminQueryCounts(BaseModel):
    total: int
    today: int
    errors: int


class AdminDailyQueries(BaseModel):
    day: str
    count: int
    errors: int


class AdminOverviewResponse(BaseModel):
    tenants: int
    users: int
    active_api_keys: int
    documents: AdminDocumentCounts
    chunks: int
    notebooks: int
    chat_sessions: int
    chat_messages: int
    queries: AdminQueryCounts
    daily_queries: list[AdminDailyQueries]


class AdminTenantSummary(BaseModel):
    tenant_id: str
    users: int
    documents: int
    chunks: int
    sessions: int
    queries_7d: int
    last_query_at: datetime | None = None


class AdminUserInfo(BaseModel):
    id: str
    tenant_id: str
    name: str
    email: str | None = None
    has_password: bool = False
    role: str
    created_at: datetime
    keys: int
    active_keys: int
    queries_total: int
    queries_7d: int
    last_query_at: datetime | None = None


class CreateAdminUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    name: str = Field(default="", max_length=256)
    role: str = Field(default="member", pattern="^(member|admin)$")


class AdminKeyInfo(BaseModel):
    """Key with its request activity — the admin access-control view."""

    id: str
    tenant_id: str
    name: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None
    queries_total: int
    queries_7d: int
    last_query_at: datetime | None = None


class AdminPromptListItem(BaseModel):
    id: str
    tenant_id: str
    user_id: str | None = None
    user_name: str | None = None
    api_key_id: str | None = None
    api_key_name: str | None = None
    mode: str
    model: str
    session_id: str | None = None
    workflow_id: str | None = None
    scope_type: str | None = None
    scope_ref: str | None = None
    query: str
    answer_preview: str
    status: str
    error: str | None = None
    latency_ms: int
    cached: bool
    confidence: float | None = None
    sources_count: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None = None
    created_at: datetime


class AdminPromptDetail(AdminPromptListItem):
    answer: str
    retrieval_query: str | None = None


class AdminPromptListResponse(BaseModel):
    items: list[AdminPromptListItem]
    total: int
    limit: int
    offset: int


class AdminDocumentListItem(BaseModel):
    id: str
    tenant_id: str
    filename: str
    source_type: str
    status: str
    processing_stage: str
    error: str | None = None
    size_bytes: int
    total_pages: int
    processed_pages: int
    created_at: datetime
    updated_at: datetime


class AdminDocumentListResponse(BaseModel):
    items: list[AdminDocumentListItem]
    total: int
    limit: int
    offset: int


class AdminUsageTotals(BaseModel):
    cost_usd: float
    total_tokens: int
    calls: int
    avg_latency_ms: int


class AdminUsageByTenant(BaseModel):
    tenant_id: str
    cost_usd: float
    total_tokens: int
    calls: int


class AdminUsageByModel(BaseModel):
    model: str
    provider: str
    cost_usd: float
    total_tokens: int
    calls: int
    avg_latency_ms: int


class AdminUsageDaily(BaseModel):
    day: str
    cost_usd: float
    total_tokens: int
    calls: int


class AdminUsageResponse(BaseModel):
    days: int
    totals: AdminUsageTotals
    by_tenant: list[AdminUsageByTenant]
    by_model: list[AdminUsageByModel]
    daily: list[AdminUsageDaily]


class AdminHealthResponse(BaseModel):
    status: str
    checks: dict[str, str]


class GoogleLoginUrlResponse(BaseModel):
    url: str


class SessionInfo(BaseModel):
    tenant_id: str
    user_id: str | None = None
    user_name: str | None = None
    email: str | None = None
    role: str | None = None
    is_admin: bool = False


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    name: str = Field(default="", max_length=256)


class EmailLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class EmailLoginResponse(BaseModel):
    token: str
    tenant_id: str
    user_id: str
    user_name: str | None = None
    email: str
    role: str
    is_admin: bool


class PasswordChangeRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)


class LlmKeyInfo(BaseModel):
    """Admin view of a provider key — the value itself never leaves the DB."""

    id: str
    provider: str
    name: str
    key_preview: str
    is_active: bool
    requests_count: int
    last_used_at: datetime | None = None
    created_at: datetime


class CreateLlmKeyRequest(BaseModel):
    provider: str = Field(pattern="^(moonshot|deepseek)$")
    name: str = Field(min_length=1, max_length=256)
    key: str = Field(min_length=8, max_length=512)


class AdminPasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)


class AdminUserUsage(BaseModel):
    """One user's share of the LLM spend (admin analytics)."""

    user_id: str | None = None
    user_name: str | None = None
    email: str | None = None
    cost_usd: float
    total_tokens: int
    calls: int
    avg_latency_ms: int
