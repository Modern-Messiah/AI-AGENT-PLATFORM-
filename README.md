# AI Agent Platform

Платформа для построения durable AI-агентов на стеке PydanticAI + Temporal с LLM-gateway, observability, RAG и аналитикой. Стек приближен к Replit Agent.

## Стек

| Слой | Технология | Назначение |
|---|---|---|
| Agent framework | **PydanticAI** | Типизированные агенты, structured output, tool calling |
| Orchestration | **Temporal** | Durable workflows, retries, signals, human-in-the-loop |
| LLM gateway | **Bifrost** (Maxim AI) | Routing, fallback, rate-limit, semantic cache |
| Observability | **Langfuse** | Traces, prompt management, evals, cost tracking |
| Vector store | **pgvector** (или ParadeDB / VectorChord / Qdrant) | RAG, semantic search |
| OLAP / analytics | **ClickHouse** | Usage events, cost-per-tenant, метрики |
| Cache / queues | **Redis** | Sessions, idempotency keys, semantic cache |
| Object storage | **MinIO** | Файлы юзера, артефакты пайплайнов |
| API | **FastAPI** | HTTP / WS endpoints |

## Архитектура

```
   Client ──HTTP/WS──▶ FastAPI ──start workflow──▶ Temporal server
                                                         │
                                                         ▼ activities
                                                   Worker (python)
                                                   ┌────────────┐
                                                   │ PydanticAI │──┐
                                                   └────────────┘  │
                                                                   ▼
                                  Langfuse ◀──traces── Bifrost gateway
                                                              │
                                                              ▼
                                                   Moonshot Kimi / OpenAI

   Storage:
   ├─ Postgres + pgvector  (RAG, app state, Langfuse metadata)
   ├─ Redis                (cache / sessions / idempotency)
   ├─ ClickHouse           (analytics events, Langfuse traces store)
   └─ MinIO                (files / артефакты)
```

**Ключевое правило**: PydanticAI вызывается **внутри Temporal activity**, не в workflow. Workflow детерминистичен, LLM-вызовы — нет. История агента и scratchpad хранятся в workflow-state и передаются в activity параметром на каждом шаге.

## Компоненты

### PydanticAI
Агентный фреймворк с типизированным выходом через Pydantic. Объявляешь `result_type`, тулзы, системный промпт — он валидирует ответ модели и ретраит при невалидном JSON.

Альтернативы: LangGraph (мощнее, графы), Instructor (только structured output), AI SDK (TS).

### Temporal
Durable execution. Workflow продолжается после рестарта воркера, ретраи декларативны, event history даёт time-travel debugging.

Для агентов критично:
- Long-running tools (часы на approval)
- Идемпотентность шагов
- Signals для отмены / human-input
- Child workflows для долгих под-задач

### Bifrost
LLM gateway, OpenAI-compatible endpoint. На Go, быстрее LiteLLM. Делает routing, fallback, rate-limit, semantic cache, ротацию ключей.

LiteLLM зрелее по списку провайдеров — если используешь Bedrock или нишевые модели, проверь сначала их.

### Langfuse
Observability + prompt management + evals. Self-host: web + worker + postgres + clickhouse + redis. Видишь весь trace агента, версионируешь промпты с лейблами `production`/`staging`.

### Vector store
- **pgvector** — <10M векторов, простота
- **VectorChord** — drop-in замена pgvector, ×5-10 быстрее
- **ParadeDB** — Postgres + BM25 + pgvector, true hybrid search
- **Qdrant** — отдельный сервис, лучшие payload-фильтры, multi-tenancy через namespace
- **LanceDB** — embedded, для версионируемых датасетов

Рекомендация на старт: **pgvector** для скорости разработки, миграция на ParadeDB / Qdrant когда упрёшься в hybrid search или объём.

## Структура проекта

```
ai-agent-platform/
├── README.md
├── docker-compose.yml          # postgres, temporal, redis, clickhouse, minio, langfuse, bifrost
├── Makefile                    # up/down/logs/seed/migrate/test
├── .env.example
├── pyproject.toml
├── apps/
│   ├── api/                    # FastAPI: HTTP/WS endpoints, аутентификация
│   │   ├── main.py
│   │   ├── routes/
│   │   └── middleware/
│   └── worker/                 # Temporal worker
│       ├── main.py
│       ├── workflows/          # детерминистичная оркестрация
│       │   ├── agent_run.py
│       │   └── ingestion.py
│       └── activities/         # PydanticAI, RAG, tools
│           ├── agent_step.py
│           ├── retrieval.py
│           └── tools/
├── packages/
│   ├── agents/                 # PydanticAI агенты (общие для api и worker)
│   │   ├── base.py
│   │   ├── prompts.py          # лоадер промптов из Langfuse
│   │   └── schemas.py          # Pydantic модели для result_type
│   ├── rag/                    # ingestion, chunking, retrieval, reranking
│   │   ├── ingest.py
│   │   ├── chunkers.py
│   │   ├── embedders.py
│   │   └── retrievers.py
│   ├── llm/                    # Bifrost клиент-обёртка, model registry
│   │   ├── client.py
│   │   └── models.py
│   ├── observability/          # Langfuse setup, decorators
│   │   └── tracing.py
│   ├── storage/                # postgres, minio, redis, clickhouse клиенты
│   │   ├── postgres.py
│   │   ├── minio.py
│   │   ├── redis.py
│   │   └── clickhouse.py
│   └── core/                   # settings, logging, errors, multi-tenancy
│       ├── settings.py
│       └── tenant.py
├── migrations/                 # alembic для postgres
├── infra/
│   ├── bifrost/
│   │   └── config.json
│   ├── temporal/
│   └── clickhouse/
│       └── init.sql
├── evals/                      # golden sets, scorers, CI eval-runner
│   ├── datasets/
│   └── runners/
├── scripts/                    # одноразовые: seed, ingest, миграции данных
└── tests/
    ├── unit/
    ├── integration/            # с docker-compose поднятой инфрой
    └── workflows/              # Temporal workflow tests с time-skipping
```

## Подводные камни

1. **Workflow determinism** — никаких `time.time()`, `uuid.uuid4()`, `random` в теле workflow. Только `workflow.now()`, `workflow.uuid4()`. Иначе replay сломается.

2. **Idempotency activity** — LLM-ответы не идемпотентны. Сохраняй результат по `(workflow_id, attempt_id)`, при retry читай из кеша.

3. **Контекст-окно** — длинная история = $$$ + деградация качества. Сжатие через summarization-шаг + sliding window.

4. **Streaming + Temporal** — activity результат возвращает только при завершении. Streaming клиенту — мимо Temporal, через FastAPI/WS. В Temporal сохраняй финальный результат + heartbeat для long-running.

5. **pgvector index** — HNSW > IVFFlat по recall. На bulk-ingest: drop → insert → recreate. Тюнить `m`, `ef_construction` под объём.

6. **Langfuse self-host** — web + worker + postgres + clickhouse + redis. Шарить инфру можно, retention политики разнести.

7. **Эвалы — не опционально** — без golden-set агент молча деградирует. Минимум 50 примеров, прогон в CI.

8. **Multi-tenancy с первого дня** — RLS на Postgres, tenant_id во всех таблицах, namespace в векторной БД, лимиты в Bifrost per-tenant.

9. **Bifrost зрелость** — проверь конкретно своих провайдеров. Bedrock / экзотика — LiteLLM безопаснее.

10. **Temporal versioning** — при изменении workflow-логики `patched()` или versioning, иначе running workflows сломаются на replay.

## Quickstart

```bash
# 1. Настроить env
cp .env.example .env
# впиши OPENAI_API_KEY (минимум) в .env
# сгенери ключ: openssl rand -hex 32 → LANGFUSE_ENCRYPTION_KEY

# 2. Поднять инфру
make up
make seed   # создаёт MinIO бакеты

# 3. Завести Langfuse-проект (один раз)
# открой http://localhost:3000 → создай аккаунт + organization + project
# Settings → API Keys → создай pair → впиши в .env:
#   LANGFUSE_PUBLIC_KEY=pk-lf-...
#   LANGFUSE_SECRET_KEY=sk-lf-...

# 4. Установить питон-зависимости
uv sync

# 5. В двух терминалах:
make worker   # Temporal worker
make api      # FastAPI на :8000

# 6. Дёрни агента
curl -X POST http://localhost:8000/agent/run \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"demo","user_query":"Что такое durable execution?"}'

# 7. Смотри trace в Langfuse: http://localhost:3000
# 8. Смотри workflow в Temporal UI: http://localhost:8233
```

**Порты:**

| Сервис | Порт | URL |
|---|---|---|
| FastAPI | 8000 | http://localhost:8000 |
| Langfuse | 3000 | http://localhost:3000 |
| Temporal UI | 8233 | http://localhost:8233 |
| Bifrost | 8088 | http://localhost:8088 |
| MinIO console | 9001 | http://localhost:9001 |
| Postgres | 5432 | — |
| Redis | 6379 | — |
| ClickHouse | 8123 | http://localhost:8123 |

**Demo durability** (Фаза 2 в действии):

1. Запусти долгий запрос
2. `docker stop ...` или `Ctrl+C` на воркере посреди работы
3. Подними воркер обратно — workflow продолжится с того же места

## Ссылки

- PydanticAI: https://ai.pydantic.dev/
- Temporal Python SDK: https://docs.temporal.io/develop/python
- Bifrost: https://github.com/maximhq/bifrost
- Langfuse: https://langfuse.com/docs
- pgvector: https://github.com/pgvector/pgvector
- ParadeDB: https://docs.paradedb.com/
- Qdrant: https://qdrant.tech/documentation/
