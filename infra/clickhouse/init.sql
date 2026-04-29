-- Analytics DB for app usage events.
-- Langfuse uses its own DB and migrates schema on boot.

CREATE DATABASE IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.llm_usage_events (
    event_time      DateTime64(3) DEFAULT now64(3),
    tenant_id       String,
    workflow_id     String,
    run_id          String,
    model           LowCardinality(String),
    provider        LowCardinality(String),
    prompt_tokens   UInt32,
    completion_tokens UInt32,
    total_tokens    UInt32,
    cost_usd        Float64,
    latency_ms      UInt32,
    status          LowCardinality(String),
    error           String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (tenant_id, event_time)
TTL toDateTime(event_time) + INTERVAL 90 DAY;
