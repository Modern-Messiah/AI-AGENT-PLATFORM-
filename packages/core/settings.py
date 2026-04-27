from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    bifrost_base_url: str = "http://localhost:8088/openai/v1"
    bifrost_api_key: str = "not-used"
    default_model: str = "openai/gpt-4o-mini"

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


@lru_cache
def _get_settings() -> Settings:
    return Settings()


settings = _get_settings()
