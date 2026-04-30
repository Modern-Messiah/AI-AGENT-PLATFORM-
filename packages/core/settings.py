import json
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    moonshot_api_key: str = ""
    deepseek_api_key: str = ""
    # strong = сложные шаги агента; weak = дешёвые вспомогательные.
    strong_model: str = "moonshot/kimi-k2.6"
    weak_model: str = "deepseek/deepseek-v4-flash"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "agent-tasks"

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/app"
    )
    redis_url: str = "redis://localhost:6379/0"
    clickhouse_url: str = "http://default:clickhouse@localhost:8123/analytics"

    minio_endpoint: str = "localhost:9002"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "app-files"

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    chunk_size: int = 2000
    chunk_overlap: int = 200
    retrieval_top_k: int = 5

    # Log a WARNING when a single LLM call costs more than this amount.
    budget_alert_usd_per_call: float = 0.10

    # Protect POST /auth/keys — change before deploying.
    admin_secret: str = "change-me-before-deploy"

    # Opt-in: run arbitrary Python in a subprocess (disabled by default — see code_exec.py).
    enable_code_exec: bool = False

    # Explicit domain allowlist for http_fetch tool.
    # Accepts JSON array  (HTTP_FETCH_ALLOWED_DOMAINS='["docs.python.org"]')
    # or comma-separated  (HTTP_FETCH_ALLOWED_DOMAINS=docs.python.org,api.github.com).
    # When non-empty ONLY these domains are reachable — fully prevents SSRF including DNS rebinding.
    # When empty the tool falls back to an IP-based blocklist (still vulnerable to DNS rebinding).
    http_fetch_allowed_domains: list[str] = []

    @field_validator("http_fetch_allowed_domains", mode="before")
    @classmethod
    def _parse_domains(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("["):
                return json.loads(v)
            return [d.strip() for d in v.split(",") if d.strip()]
        return v

    # Maximum file size accepted by POST /documents and /documents/bulk (bytes).
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MB per file

    # Maximum total body across ALL files in a single POST /documents/bulk request.
    # Prevents memory exhaustion from 20 × 50 MB = 1 GB bulk uploads.
    max_bulk_total_bytes: int = 200 * 1024 * 1024  # 200 MB


@lru_cache
def _get_settings() -> Settings:
    return Settings()


settings = _get_settings()
