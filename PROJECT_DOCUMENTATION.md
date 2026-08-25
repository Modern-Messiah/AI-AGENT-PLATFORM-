# 📖 AI Agent Platform — Полная документация

## Содержание

1. 🧠 Что это такое и зачем
2. 🗺️ Общая карта системы
3. 🧱 Стек технологий
4. 🤖 Как работает агент — главная глава
5. 📚 RAG: документы, эмбеддинги и поиск по смыслу
6. 🗂️ Структура проекта
7. 🔄 Полный флоу запроса
8. ⚙️ Переменные окружения
9. 🚀 Запуск проекта
10. 💸 Стоимость и лимиты
11. 🧩 Ключевые решения — почему так, а не иначе
12. ❓ FAQ для новичка в AI
13. 🗃️ Модель данных и где что хранится
14. 🧭 UI, API и жизненный цикл приложения
15. 👤 Пользовательские сценарии от начала до конца
16. 🛡️ Tenant isolation, авторизация и безопасность
17. 🚨 Ошибки, повторы и деградация сервисов
18. 🧪 Тесты, evals и проверка качества
19. ⚠️ Реальные ограничения текущей версии
20. 📌 Краткая карта: куда идти за изменением поведения

---

## 1. 🧠 Что это такое и зачем

AI Agent Platform — это приложение, в которое пользователь загружает документы, а потом задаёт вопросы по этим документам в чате. Система сама находит нужные фрагменты в базе знаний, отправляет их в языковую модель и показывает ответ пользователю. Если говорить языком обычной разработки: это backend + frontend + хранилища, где вместо фиксированной бизнес-логики часть решений принимает LLM.

LLM, или Large Language Model, — это большая языковая модель. Аналогия для разработчика: представь функцию `generateAnswer(prompt)`, которая принимает текстовую инструкцию и возвращает текст, но внутри умеет понимать естественный язык, переформулировать, обобщать и выбирать следующий шаг. В этом проекте LLM нужна не для магии, а для задач, где обычный `if/else` быстро становится невозможным: пользователь может спросить одно и то же тысячей способов, документы могут быть разного формата, а ответ нужно собрать из нескольких фрагментов.

Почему не просто “вызвать ChatGPT”? Потому что ChatGPT сам по себе не знает ваши локальные документы, не умеет безопасно читать вашу базу, не знает `tenant_id`, не сохраняет события в вашу аналитику и не запускает Temporal workflows. Этот проект строит вокруг LLM прикладную систему: авторизация, загрузка файлов, индексация, поиск, кэш, лимиты, стоимость, стриминг, workflow-ретраи и human-in-the-loop.

Почему это сделано как агент? Агент — это LLM плюс набор инструментов, которые модель может вызвать. Tool calling — это как callback-функции, только не код решает `if should_call_tool`, а модель по описанию инструмента решает: “мне нужно вызвать `retrieve(query)`” или “мне нужно сделать `sql_query(...)`”. В проекте есть два режима: быстрый RAG-stream для обычного чата и более тяжёлый PydanticAI agent loop для workflow/HITL/research.

Что умеет система, чего не умел бы простой `if/else`:

- понимать вопросы в свободной форме;
- искать документы по смыслу, а не по точной строке;
- комбинировать найденные фрагменты в связный ответ;
- вызывать tools, когда модели нужны данные;
- стримить ответ по мере генерации;
- кэшировать похожие вопросы через semantic cache;
- запускать долгие процессы через Temporal и переживать рестарты worker’а.

---

## 2. 🗺️ Общая карта системы

```mermaid
graph TD
    User["👤 Пользователь"] --> Frontend["Vue UI"]
    Frontend -->|HTTP + X-API-Key| Backend["FastAPI Backend"]
    Frontend -->|SSE stream| Stream["POST /agent/stream"]

    Backend --> Auth["API key auth"]
    Backend --> Sessions["Chat sessions API"]
    Backend --> Documents["Documents API"]
    Backend --> AnalyticsAPI["Analytics API"]
    Backend --> Temporal["Temporal Server"]

    Stream --> Cache["Redis semantic cache"]
    Stream --> Rag["Fast RAG retrieval"]
    Rag --> VectorDB["PostgreSQL + pgvector"]
    Stream --> LLM["Moonshot / DeepSeek LLM"]
    Stream --> ClickHouse["ClickHouse usage analytics"]

    Temporal --> Worker["Temporal Worker"]
    Worker --> Agent["PydanticAI Agent"]
    Agent --> Tools["Agent Tools"]
    Agent --> LLM
    Tools --> VectorDB
    Tools --> ExternalHTTP["External HTTP"]
    Tools --> AppDB["PostgreSQL app tables"]

    Documents --> MinIO["MinIO object storage"]
    Documents --> Temporal
    Worker --> MinIO
    Worker --> Embedder["FastEmbed embeddings"]
    Embedder --> VectorDB

    Backend --> Langfuse["Langfuse / OpenTelemetry"]
    Worker --> Langfuse
```

`Vue UI` — браузерный интерфейс. Он похож на обычную SPA-админку: хранит активную сессию чата, отправляет HTTP-запросы, читает streaming-ответ и показывает документы/аналитику.

`FastAPI Backend` — центральный HTTP слой. Он проверяет API-ключи, создаёт сессии, принимает файлы, запускает workflows и отдаёт SSE stream. SSE, или Server-Sent Events, — это как длинный HTTP-response, в который сервер постепенно дописывает события.

`/agent/stream` — быстрый путь обычного чата. Здесь нет полноценного agent loop с tools: backend сам делает retrieval, сам собирает prompt и напрямую стримит ответ LLM. Это сделано ради скорости.

`PydanticAI Agent` — агентный путь. Агент получает system prompt, user query, tools и ожидаемый тип результата `AgentRunOutput`. PydanticAI управляет tool calling и проверяет, что финальный ответ подходит под Pydantic-схему.

`Tools` — функции, которые агент может вызвать. Аналогия: это API методов, которые ты даёшь модели как SDK. В проекте tools: `retrieve`, `sql_query`, `http_fetch`, опционально `code_exec`.

`LLM` — языковая модель Moonshot/Kimi или DeepSeek. Она не “подключена к базе” напрямую. Она видит только текст prompt’а, описания tools и результаты tools, которые ей передали.

`PostgreSQL + pgvector` — обычная реляционная БД плюс векторный поиск. Векторная БД — это как обычная БД, только она умеет искать “похожие по смыслу” записи, а не только `WHERE title = '...'`.

`Redis semantic cache` — кэш похожих вопросов. Semantic cache — это как обычный cache по ключу, но ключом является не точная строка, а embedding вопроса.

`Temporal` — оркестратор долгих задач. Аналогия: если HTTP-запрос — это синхронный вызов функции, то workflow в Temporal — это durable job, который можно ретраить, ждать, сигналить и продолжать после рестарта.

`MinIO` — S3-подобное хранилище файлов. PostgreSQL хранит метаданные, MinIO хранит bytes исходных документов.

`ClickHouse` — аналитическая БД для событий LLM usage. Она нужна, чтобы быстро считать токены, стоимость и latency по tenant/model/provider.

`Langfuse / OpenTelemetry` — наблюдаемость. Langfuse в этом проекте также может хранить prompt версии, но если ключи не настроены, используется fallback prompt из кода.

Важное нестандартное место: README упоминает Bifrost как LLM gateway, и в `infra/bifrost/config.json` есть конфиг, но в текущем `docker-compose.yml` активного Bifrost-сервиса нет. Реальные LLM-вызовы сейчас идут напрямую через OpenAI-compatible API Moonshot/DeepSeek.

---

## 3. 🧱 Стек технологий

### Backend, AI и infrastructure

| Технология | Категория | Что это | Зачем в этом проекте |
|-----------|----------|---------|----------------------|
| Python 3.12 | Runtime | Язык backend-части. | API, worker, RAG, tools, LLM-клиент и миграции написаны на Python. |
| FastAPI | Backend API | Async web framework. | Все HTTP endpoints живут в `apps/api/main.py`. |
| Uvicorn | ASGI server | Сервер для FastAPI. | Запускает API-контейнер командой `uvicorn apps.api.main:app`. |
| Pydantic | Data validation | Типизированные модели данных. | Описывает API-схемы, agent input/output и settings. |
| Pydantic Settings | Config | Загрузка `.env` в typed settings. | `packages/core/settings.py` превращает env в объект `settings`. |
| PydanticAI | AI framework | Фреймворк для LLM-агентов с tools и structured output. | Строит `research-agent`, регистрирует tools и валидирует `AgentRunOutput`. Это легче, чем вручную парсить tool calls. |
| OpenAI Python SDK | LLM client | Клиент для OpenAI-compatible Chat Completions API. | Moonshot и DeepSeek имеют похожий API, поэтому можно использовать один клиент. |
| Moonshot/Kimi | LLM provider | Провайдер языковых моделей Kimi. | Основная strong model для сложных ответов и tool calling. |
| DeepSeek | LLM provider | Провайдер моделей DeepSeek. | Более дешёвая/быстрая модель для weak/simple задач. |
| Temporal Python SDK | Orchestration | Durable workflows и activities. | Ingestion, HITL и multi-step research идут через workflow. |
| PostgreSQL 16 | Database | Реляционная БД. | Документы, chunks, chat sessions, messages, API keys. |
| pgvector | Vector DB extension | Векторный поиск внутри PostgreSQL. | Хранит `embedding vector(384)` и ищет похожие chunks. |
| SQLAlchemy async | ORM/SQL | Python-инструмент для работы с SQL. | Модели и запросы к PostgreSQL. |
| asyncpg | DB driver | Async драйвер PostgreSQL. | Нужен SQLAlchemy для `postgresql+asyncpg`. |
| Alembic | Migrations | Версионирование схемы БД. | Миграции лежат в `migrations/versions`. |
| Redis | Cache | In-memory key-value storage. | Semantic cache и rate limiting. |
| ClickHouse | Analytics DB | Колонночная БД для аналитики. | LLM usage events: tokens, cost, latency. |
| clickhouse-connect | DB client | Python client для ClickHouse. | Запись и чтение usage analytics. |
| MinIO | Object storage | S3-compatible хранилище. | Исходные документы пользователя. |
| minio Python SDK | Object client | Клиент MinIO. | `object_store.put/get` в `packages/storage/object_store.py`. |
| FastEmbed | Embeddings | Локальная библиотека для эмбеддингов. | Считает vectors для документов и вопросов. |
| BAAI/bge-small-en-v1.5 | Embedding model | Модель, превращающая текст в 384-мерный vector. | Используется для RAG-поиска. |
| MarkItDown | Document parsing | Парсер разных форматов в plain text. | DOCX/TXT/MD/CSV/HTML и часть других файлов превращаются в текст. |
| PyMuPDF | PDF parsing | Библиотека чтения PDF. | PDF парсятся отдельно, потому что PyMuPDF хорошо извлекает текстовый слой. |
| langchain-text-splitters | Chunking | Разбиение текста на chunks. | `RecursiveCharacterTextSplitter` режет документы на куски с overlap. |
| httpx | HTTP client | Async HTTP-запросы. | Используется tool’ом `http_fetch`. |
| python-multipart | Uploads | Поддержка multipart/form-data. | Нужен для `POST /documents` и bulk upload. |
| Langfuse | LLM observability | Prompt management, traces, analytics. | Prompt может подтягиваться из Langfuse, fallback лежит в коде. |
| OpenTelemetry | Observability | Стандарт трассировки. | `setup_tracing` подключается в API и worker. |
| structlog | Logging | Структурированные логи. | Зависимость есть, но основная настройка сейчас через `logging.basicConfig`. |
| Docker Compose | Local infra | Запуск многих сервисов одной командой. | Поднимает БД, Redis, MinIO, Temporal, Langfuse, API, worker, UI. |
| Ruff | Dev tooling | Линтер и форматтер. | `make lint`, `make format`. |
| mypy | Dev tooling | Проверка типов. | Настроен strict mode. |
| pytest | Tests | Тестовый framework. | `make test`. |
| pytest-asyncio | Tests | Async-тесты. | Нужен для async backend кода. |
| pytest-cov | Tests | Покрытие тестов. | Для coverage report. |
| greenlet | SQLAlchemy support | Низкоуровневая зависимость SQLAlchemy. | Требуется SQLAlchemy async stack. |

### Frontend

| Технология | Категория | Что это | Зачем в этом проекте |
|-----------|----------|---------|----------------------|
| Vue 3 | Frontend framework | Реактивный UI-фреймворк. | Основной интерфейс: чат, документы, аналитика, настройки. |
| Pinia | State management | Store для Vue. | `chat.js` хранит сессии, сообщения, loading state и streaming state. |
| Vue Router | Routing | Client-side маршруты. | `/chat`, `/documents`, `/analytics`; `/workflows` редиректит в чат. |
| Vite | Build tool | Dev server и сборка frontend. | Локальная разработка и production build. |
| @vitejs/plugin-vue | Build plugin | Плагин Vue для Vite. | Позволяет Vite собирать `.vue` компоненты. |

### Почему не LangChain / LlamaIndex / CrewAI?

В проекте нет LangChain как agent framework, есть только `langchain-text-splitters` для chunking. Агентный слой построен на PydanticAI. Это более узкий и типизированный выбор: проекту нужны tools и structured output, но не нужен большой графовый framework.

LlamaIndex обычно выбирают, когда главный центр системы — сложный document/RAG pipeline. Здесь RAG pipeline написан кастомно: MinIO → parser → chunks → FastEmbed → pgvector.

CrewAI/AutoGen обычно нужны для мультиагентных сценариев, где несколько агентов общаются друг с другом. В этом проекте настоящей мультиагентности нет: есть `MultiStepResearchWorkflow`, который запускает несколько child workflows параллельно, но это fan-out/fan-in orchestration, а не чат агентов между собой.

MCP, Model Context Protocol, в проекте не используется. Ни MCP-серверов, ни MCP-клиентов, ни конфигов подключения не найдено.

---

## 4. 🤖 Как работает агент — главная глава

### 4.1 Что такое агент в этом проекте

В этом проекте “агент” — это PydanticAI объект, созданный в `packages/agents/base.py`:

```python
Agent(
    model=build_model(model_name),
    deps_type=AgentDeps,
    result_type=AgentRunOutput,
    system_prompt=get_system_prompt(),
)
```

`model` — LLM, например Kimi или DeepSeek. `deps_type` — зависимости выполнения, сейчас это `tenant_id` и список источников. `result_type` — Pydantic-схема финального ответа:

```json
{
  "answer": "Финальный ответ пользователю",
  "confidence": 0.85,
  "sources": ["license.txt"],
  "cached": false
}
```

Агент умеет:

- искать chunks в базе знаний через `retrieve`;
- читать ограниченные таблицы через `sql_query`;
- получать внешний URL через `http_fetch`;
- выполнять маленький Python snippet через `code_exec`, если `ENABLE_CODE_EXEC=true`;
- вернуть структурированный финальный ответ `AgentRunOutput`.

Триггеры запуска агента:

- `POST /agent/run` — обычный agent workflow через Temporal;
- `POST /agent/run` с `require_approval=true` — agent workflow + human approval;
- `POST /agent/research` — multi-step workflow с child workflows.

Важно: обычный UI-чат сейчас использует не этот agent loop, а быстрый endpoint `POST /agent/stream`. Там backend сам делает retrieval и напрямую зовёт LLM. Это осознанная оптимизация скорости.

### 4.2 Agent Loop — цикл работы агента

Agent loop — это цикл “LLM → tool → LLM → tool → final answer”. Аналогия: обычная программа сама вызывает функции по `if/else`, а agent loop отдаёт LLM право выбрать следующую функцию из разрешённого списка.

```mermaid
flowchart TD
    Start(["Получен user_query"]) --> Prompt["Формируем system prompt + user prompt + tool schemas"]
    Prompt --> LLM["Отправляем в LLM"]
    LLM --> Decision{"Что решила модель?"}
    Decision -->|"Нужен документ"| Retrieve["Tool retrieve(query, k)"]
    Decision -->|"Нужны метаданные"| SQL["Tool sql_query(query)"]
    Decision -->|"Нужен URL"| HTTP["Tool http_fetch(url)"]
    Decision -->|"Нужно посчитать"| Code["Tool code_exec(code)"]
    Retrieve --> ToolResult["Результат tool добавляется в контекст"]
    SQL --> ToolResult
    HTTP --> ToolResult
    Code --> ToolResult
    ToolResult --> LLM
    Decision -->|"Готов финальный ответ"| Validate["PydanticAI валидирует AgentRunOutput"]
    Validate --> Answer(["Возвращаем ответ"])
```

Шаги внутри:

1. Backend или worker получает `user_query`.
2. PydanticAI собирает system prompt, user prompt и JSON-описания tools.
3. LLM получает текст и список доступных функций.
4. Если модели не хватает данных, она возвращает tool call, например `retrieve`.
5. Python-код реально выполняет tool.
6. Результат tool добавляется в новое сообщение для LLM.
7. LLM снова думает над уже расширенным контекстом.
8. Когда данных достаточно, модель возвращает финальный structured output.
9. PydanticAI проверяет, что ответ можно превратить в `AgentRunOutput`.

Что происходит внутри LLM, когда она “принимает решение”? Важно не мистифицировать: модель не выполняет Python и не читает базу напрямую. Она генерирует следующий текстовый/JSON-токен на основе prompt’а, описаний tools и предыдущих сообщений. Tool calling — это договорённый формат ответа модели: вместо обычного текста она может вернуть “вызови функцию X с такими аргументами”.

### 4.3 System Prompt

System prompt — это инструкция верхнего уровня. Аналогия: это README для модели на каждый запрос. Он говорит, какую роль выполнять, какие инструменты есть и какие правила ответа соблюдать.

Fallback prompt для structured agent:

```text
You are a helpful research assistant grounded in the user's knowledge base.

Available tools:
- retrieve      : search the vector knowledge base for relevant chunks
- sql_query     : run a SELECT against the documents/chunks tables
- http_fetch    : fetch content from an external URL
- code_exec     : run a Python snippet for computation or data transformation

When answering:
1. Call retrieve first for knowledge-base questions.
2. Use sql_query to look up document metadata or counts.
3. Use http_fetch only when you need fresh external content.
4. Use code_exec for calculations or non-trivial data wrangling.

Always set confidence in [0,1]. In sources, list ONLY the filename of each
document whose content you directly cited or paraphrased in your answer.
If a retrieved chunk was not helpful, do not include its filename. Never invent filenames.
```

Streaming prompt похожий, но просит plain text, потому что streaming path работает с текстовым ответом:

```text
Respond in clear, concise plain text.
If the knowledge base contains no relevant information, say so directly.
```

Почему prompt написан так:

- “grounded in knowledge base” снижает шанс hallucination, то есть выдуманных фактов;
- список tools объясняет модели доступные “callback-функции”;
- “Call retrieve first” направляет модель к RAG перед ответом;
- “Never invent filenames” защищает UI от фальшивых sources;
- `confidence in [0,1]` нужен для Pydantic-схемы.

Если изменить prompt:

- убрать `retrieve first` — агент может отвечать из общих знаний вместо документов;
- убрать запрет на выдуманные filenames — sources станут ненадёжными;
- сделать prompt слишком длинным — вырастут токены и стоимость;
- добавить бизнес-правила — агент начнёт следовать им, если они не конфликтуют с user prompt и tools.

Langfuse: `get_system_prompt()` сначала пытается получить prompt `research-agent` с label `production` из Langfuse. Если ключей нет или Langfuse недоступен, используется fallback из кода.

### 4.4 Tools / Инструменты агента

```mermaid
graph LR
    Agent["🤖 PydanticAI Agent"] --> Retrieve["retrieve(query, k)"]
    Agent --> SQL["sql_query(query)"]
    Agent --> HTTP["http_fetch(url)"]
    Agent --> Code["code_exec(code)"]
    Retrieve --> PGV["PostgreSQL + pgvector"]
    SQL --> PG["PostgreSQL"]
    HTTP --> Web["Allowed HTTP URL"]
    Code --> Py["Sandboxed Python subprocess"]
```

Tool — это функция, которую модель может попросить вызвать. Для разработчика это похоже на публичный метод SDK, только caller — LLM.

#### `retrieve(query, k=5)`

Что делает: ищет релевантные chunks в базе знаний tenant’а через embeddings и pgvector.

Когда агент вызывает: когда вопрос может относиться к загруженным документам.

Параметры:

```json
{
  "query": "кто автор лицензии и что это за проект",
  "k": 5
}
```

Возвращает:

```json
[
  {
    "document_id": "56ee3351-fa70-4192-bd4c-10e06c78c879",
    "filename": "license.txt",
    "content": "MIT License ...",
    "score": 0.82
  }
]
```

`score` — это похожесть. В коде pgvector считает cosine distance, а score = `1 - distance`.

#### `sql_query(query)`

Что делает: выполняет read-only SQL SELECT по разрешённым таблицам.

Когда агент вызывает: когда нужны метаданные: сколько документов, какие статусы, какие сообщения, какие chunks есть.

Ограничения безопасности:

- обязателен `{tenant_id}` в запросе;
- запрещены `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`;
- запрещены `api_keys`, `pg_catalog`, `information_schema`;
- разрешены только `documents`, `chunks`, `chat_sessions`, `chat_messages`;
- лимит 500 строк, если нет `LIMIT`;
- `SET TRANSACTION READ ONLY`;
- `statement_timeout = 5000`.

Пример tool call:

```json
{
  "query": "SELECT filename, status, size_bytes FROM documents WHERE tenant_id = '{tenant_id}' LIMIT 20"
}
```

Пример результата:

```json
[
  {
    "filename": "project.md",
    "status": "done",
    "size_bytes": 18432
  }
]
```

Если SQL падает, tool возвращает ошибку как данные, а не бросает exception:

```json
[
  {
    "error": "SQL execution failed: relation \"documnts\" does not exist"
  }
]
```

#### `http_fetch(url)`

Что делает: загружает текст внешнего URL до 20 000 символов.

Когда агент вызывает: когда нужна свежая внешняя документация или web/API ответ.

Параметры:

```json
{
  "url": "https://docs.python.org/3/library/json.html"
}
```

Возвращает plain text или ошибку:

```json
"HTTP 404: Not Found"
```

SSRF-защита: в production нужно задать `HTTP_FETCH_ALLOWED_DOMAINS`. SSRF — это атака, где сервер заставляют сходить во внутреннюю сеть. Аналогия: пользователь просит курьера принести публичную страницу, а на самом деле отправляет его в закрытый офис.

#### `code_exec(code)`

Что делает: выполняет маленький Python snippet в subprocess.

Когда агент вызывает: когда нужно посчитать, преобразовать JSON, сделать небольшую обработку данных.

По умолчанию выключен. Включается только `ENABLE_CODE_EXEC=true`.

Параметры:

```json
{
  "code": "import json\nprint(json.dumps({'answer': 2 + 2}))"
}
```

Возвращает:

```json
"{\"answer\": 4}"
```

Ограничения:

- timeout 10 секунд;
- пустое окружение без секретов;
- `python -S -E`, то есть без site-packages и env-переменных;
- доступна только стандартная библиотека.

### 4.5 MCP

MCP, Model Context Protocol, — это стандартный способ подключать внешние инструменты к AI-агенту. Представь это как USB: один стандартный разъём, через который агент может подключить “устройства” вроде файловой системы, GitHub, браузера, базы данных или почты.

В этом проекте MCP не используется:

- нет MCP-серверов в `docker-compose.yml`;
- нет MCP client dependency в `pyproject.toml`;
- tools регистрируются напрямую через PydanticAI decorators;
- frontend/backend не вызывают MCP endpoints.

Что используется вместо MCP: локальные Python tools (`retrieve`, `sql_query`, `http_fetch`, `code_exec`). Это проще и прозрачнее для текущего проекта. MCP имело бы смысл, если нужно было бы подключать внешние инструменты стандартным способом: например GitHub, Slack, filesystem, browser automation или CRM.

### 4.6 Context Window и Memory

Context window — это максимальный объём текста, который LLM видит в одном запросе. Аналогия: это размер стека вызова или буфера. Если туда не положить данные, модель их не знает. Если положить слишком много, растёт стоимость и может падать качество.

Что попадает в контекст в fast streaming path `/agent/stream`:

- system message с правилом отвечать только по контексту;
- текущий user query;
- top-N chunks из RAG, ограниченные `FAST_RAG_TOP_K` и `FAST_RAG_CONTEXT_MAX_CHARS`.

Что не попадает в контекст fast path:

- вся история чата;
- все документы целиком;
- все chunks;
- приватные env-секреты;
- цепочка рассуждений модели.

Chain of thought — это внутренние рассуждения модели. В проекте они не сохраняются и не показываются. Более того, для Kimi/DeepSeek в коде явно добавляется `thinking: {"type": "disabled"}` для совместимости и снижения лишнего reasoning overhead.

Memory в проекте:

- долгосрочная память документов: `documents` + `chunks` + embeddings;
- история чатов: `chat_sessions` + `chat_messages`, но fast LLM prompt её сейчас не использует;
- semantic cache: Redis хранит похожие вопросы и ответы примерно на 1 час;
- HITL pending state во frontend: `localStorage` map workflow IDs.

Если context window заполняется, текущий код не делает summarization history. Вместо этого fast path заранее режет RAG context через `FAST_RAG_CONTEXT_MAX_CHARS`. Это простое и предсказуемое решение.

---

## 5. 📚 RAG

RAG, Retrieval Augmented Generation, — это когда перед отправкой вопроса в LLM мы сначала находим нужные документы в базе и добавляем их в prompt. Аналогия: вместо того чтобы просить junior-разработчика ответить по памяти, ты сначала даёшь ему нужные фрагменты документации.

```mermaid
flowchart LR
    Q["❓ Вопрос пользователя"] --> EQ["Эмбеддинг вопроса"]
    EQ --> Search["Поиск в pgvector"]
    Search --> Chunks["Top-N релевантных chunks"]
    Chunks --> Prompt["Контекст в prompt"]
    Q --> Prompt
    Prompt --> LLM["🧠 LLM"]
    LLM --> Answer["✅ Ответ"]
```

Эта схема описывает runtime-запрос. Сначала вопрос превращается в embedding, затем PostgreSQL/pgvector ищет похожие embeddings chunks, потом найденные куски добавляются в prompt.

### Как документы попадают в векторную БД

```mermaid
flowchart TD
    Upload["Файл загружен через UI"] --> API["POST /documents"]
    API --> MinIO["Сохранить bytes в MinIO"]
    API --> DocRow["Создать documents status=pending"]
    API --> Temporal["Start IngestionWorkflow"]
    Temporal --> Kind{"Visual document?"}
    Kind -->|"No"| TextDoc["ingest_text_document"]
    Kind -->|"PDF/image"| Visual["process_visual_batch"]
    TextDoc --> Parse["parse_original_document"]
    Parse --> ChunkEmbed["build_chunk_batch (chunk + embed)"]
    ChunkEmbed --> Store["store_chunk_batch"]
    Visual --> Finalize["finalize_visual_document"]
    Store --> PG["PostgreSQL chunks + pgvector"]
    Finalize --> PG
    PG --> Done["documents status=done"]
```

Ingestion pipeline:

1. API читает upload с лимитом размера.
2. Исходный файл сохраняется в MinIO.
3. В `documents` создаётся строка со статусом `pending`.
4. API запускает `IngestionWorkflow`.
5. Worker ставит статус `processing`.
6. Для обычного текста `ingest_text_document` внутри одной activity парсит файл, строит chunks и embeddings. Большие промежуточные данные поэтому не попадают в Temporal history.
7. Для PDF и изображений workflow сначала строит visual manifest, затем обрабатывает страницы батчами с concurrency `2`: рендерит WebP preview, запускает OCR и при необходимости Vision-анализ.
8. URL и GitHub-источники сначала скачиваются API, нормализуются в сохранённый объект, а найденные схемы/изображения описываются отдельным visual-проходом.
9. `RecursiveCharacterTextSplitter` режет parsed segments по `CHUNK_SIZE=2000` и `CHUNK_OVERLAP=200`, сохраняя metadata страницы/asset.
10. `embed_texts` считает embedding каждого chunk батчами по `EMBEDDING_BATCH_SIZE=256`.
11. `store_chunk_batch` атомарно заменяет chunks документа, записывает vectors, summary, suggested questions и warnings (в БД действует `UniqueConstraint("tenant_id", "document_id", "chunk_idx", name="uq_chunks_tenant_doc_chunk_idx")` для защиты от дубликатов при повторах активности).
12. Статус документа становится `done`; при исчерпании activity retries — `failed` с корневой причиной.

### Что такое embeddings

Embedding — это массив чисел, который кодирует смысл текста. В проекте используется `BAAI/bge-small-en-v1.5`, размер вектора `384`. Для разработчика можно думать так: это не hash, потому что похожие тексты дают похожие vectors. Обычный hash меняется полностью при изменении одного символа, а embedding сохраняет близость по смыслу.

Пример концептуально:

```json
{
  "text": "MIT License",
  "embedding": [0.012, -0.044, 0.108, "... 381 more floats"]
}
```

### Как определяется релевантность

`retrieve_chunks()` считает cosine distance:

- `0` — очень похоже;
- больше — хуже;
- `score = 1 - distance`.

Запрос фильтруется через `RETRIEVAL_MAX_DISTANCE`. Если дистанция больше порога, chunk не попадёт в контекст. Это защищает от нерелевантных документов, но если порог слишком строгий, система может сказать “не нашёл релевантной информации”.

### Какая векторная БД используется и почему

Используется PostgreSQL + pgvector, а не Pinecone/Qdrant/Chroma. Причина видна по архитектуре: проект уже хранит документы и tenants в PostgreSQL, а pgvector позволяет добавить vector search без отдельного сервиса. Для MVP и небольшого/среднего объёма это проще в эксплуатации.

Альтернативы:

- Qdrant — сильный отдельный vector DB, хорош при большом объёме и сложных payload filters;
- Pinecone — managed vector DB, меньше DevOps, но платный внешний сервис;
- Chroma — удобен для локальных прототипов;
- ParadeDB/VectorChord — варианты усилить PostgreSQL-подход.

---

## 6. 🗂️ Структура проекта

```text
ai-agent-platform/
├── apps/
│   ├── api/
│   │   ├── main.py                 # FastAPI lifecycle, CORS, router registration
│   │   ├── routers/                # agent, documents, notebooks, sessions, workflows, analytics
│   │   └── services/               # URL sources, notebook queries, cache invalidation, limits
│   ├── ui/
│   │   ├── Dockerfile              # Сборка Vue UI в nginx/static container
│   │   ├── package.json            # Vue/Pinia/Router/Vite зависимости
│   │   └── src/
│   │       ├── composables/
│   │       │   └── useApi.js        # apiFetch и apiStreamFetch с X-API-Key
│   │       ├── stores/
│   │       │   ├── chat.js          # Chat state, sessions, SSE parsing, HITL pending
│   │       │   └── settings.js      # API key/base URL в localStorage
│   │       ├── router/
│   │       │   └── index.js         # /chat, /documents/:id, /notebooks/:id, /analytics
│   │       ├── views/               # Chat, Documents, DocumentDetail, Notebooks, Analytics
│   │       └── components/          # UI-компоненты чата, документов, layout
│   └── worker/
│       ├── main.py                  # Temporal worker entrypoint
│       ├── activities/
│       │   ├── agent_step.py        # PydanticAI agent activity + semantic cache + usage
│       │   ├── ingestion.py         # facade visual/text ingestion activities
│       │   ├── document_chunks.py   # parse, chunk, embed, replace chunks
│       │   ├── visual_analysis.py   # OCR + Vision page analysis
│       │   ├── visual_storage.py    # assets/previews/progress
│       │   ├── url_visuals.py       # diagrams/images referenced by URL/GitHub
│       │   └── human_approval.py    # activity для HITL approval notification
│       └── workflows/
│           ├── agent_run.py         # AgentRunWorkflow с optional approve/reject
│           ├── ingestion.py         # IngestionWorkflow
│           └── multi_step.py        # Fan-out child workflows + synthesis
├── packages/
│   ├── agents/
│   │   ├── base.py                  # build_research_agent, register tools
│   │   ├── deps.py                  # AgentDeps: tenant_id, sources
│   │   ├── prompts.py               # System prompts + Langfuse fallback
│   │   ├── schemas.py               # AgentRunInput/Output, MultiStepResearchInput
│   │   └── tools/
│   │       ├── retrieve.py           # RAG search tool
│   │       ├── sql_query.py          # Safe read-only SQL tool
│   │       ├── http_fetch.py         # HTTP fetch tool with SSRF guard
│   │       └── code_exec.py          # Optional sandboxed Python tool
│   ├── rag/
│   │   ├── parser.py                # PDF/MarkItDown text extraction
│   │   ├── chunker.py               # RecursiveCharacterTextSplitter
│   │   ├── embedder.py              # FastEmbed lazy singleton
│   │   └── retriever.py             # pgvector semantic search
│   ├── llm/
│   │   └── client.py                # Moonshot/DeepSeek OpenAI-compatible client
│   ├── cache/
│   │   ├── redis.py                 # Redis client
│   │   └── semantic.py              # Semantic cache over Redis ZSET + vectors
│   ├── storage/
│   │   ├── models.py                # SQLAlchemy tables
│   │   ├── db.py                    # async engine + tenant_session RLS
│   │   └── object_store.py          # MinIO wrapper
│   ├── analytics/
│   │   ├── events.py                # ClickHouse usage insert
│   │   └── pricing.py               # Approx model prices
│   ├── auth/
│   │   └── api_keys.py              # API key generation/hash/require_tenant
│   └── core/
│       ├── settings.py              # Typed env config
│       └── tenant_utils.py          # tenant checks for workflow IDs
├── migrations/
│   └── versions/                    # Alembic migrations: docs, chunks, RLS, chat, size
├── infra/
│   ├── clickhouse/init.sql          # analytics.llm_usage_events
│   ├── postgres/init.sql            # Postgres init
│   └── bifrost/config.json          # Bifrost config exists, service not active in compose
├── scripts/
│   ├── backup.py                    # Backup helper
│   └── seed.sh                      # Seed helper
├── tests/                           # pytest tests
├── docker-compose.yml               # Local infra + app services
├── Dockerfile                       # Python API/worker image
├── Makefile                         # up/down/logs/test/lint/migrate
├── pyproject.toml                   # Python dependencies/tooling
├── .env.example                     # Env template
└── README.md                        # High-level overview and operations
```

AI-специфичные файлы, которые стоит читать первыми:

- `packages/agents/prompts.py` — как агенту объясняют поведение;
- `packages/agents/base.py` — где собирается PydanticAI agent;
- `packages/agents/tools/*.py` — какие tools доступны модели;
- `packages/rag/retriever.py` — как работает semantic search;
- `apps/api/routers/agent.py` — быстрый `/agent/stream` path и запуск agent workflows;
- `apps/worker/activities/agent_step.py` — durable PydanticAI path;
- `packages/llm/client.py` — provider quirks Kimi/DeepSeek.

---

## 7. 🔄 Полный флоу запроса

Возьмём реальный сценарий: пользователь загрузил `license.txt`, потом спрашивает в чате: “кто автор лицензии и что за проект?”.

### Быстрый UI path: `/agent/stream`

```mermaid
sequenceDiagram
    actor User as "👤 Пользователь"
    participant UI as "Vue UI"
    participant API as "FastAPI /agent/stream"
    participant Redis as "Redis semantic cache"
    participant VDB as "PostgreSQL + pgvector"
    participant LLM as "Moonshot/DeepSeek"
    participant CH as "ClickHouse"

    User->>UI: Отправляет вопрос
    UI->>API: POST /agent/stream {user_query, model}
    API->>API: require_tenant + validate length + rate limit
    API->>Redis: semantic_cache.get(query, tenant_id)
    alt Cache hit
        Redis-->>API: AgentRunOutput
        API-->>UI: SSE token + done
    else Cache miss
        API->>VDB: retrieve_chunks(query, tenant_id, k=FAST_RAG_CANDIDATE_K)
        VDB-->>API: chunks + filename + score
        API->>API: select_diverse_chunks + build_grounded_messages
        API->>LLM: stream_chat_text(model, messages)
        loop Каждый токен
            LLM-->>API: token
            API-->>UI: SSE data: {"type":"token","content":"..."}
            UI-->>User: Показывает текст
        end
        LLM-->>API: usage tokens
        API-->>UI: SSE data: {"type":"done",...}
        API->>CH: record_usage(...)
        API->>Redis: semantic_cache.set(query, answer)
    end
    UI->>API: POST /sessions/{id}/messages с ответом
```

Подробно:

1. UI создаёт user message и сохраняет его в текущую session.
2. UI открывает `fetch` на `/agent/stream` и читает `ReadableStream`.
3. Backend проверяет API key. Сырой ключ хэшируется SHA-256 и ищется в `api_keys`.
4. Backend получает `tenant_id` из ключа.
5. Rate limit хранится в Redis ключом вида `rl:{tenant_id}:agent:{minute}`.
6. Semantic cache ищет похожий прошлый вопрос. Для этого новый вопрос тоже превращается в embedding.
7. Если cache miss, backend получает до `FAST_RAG_CANDIDATE_K` кандидатов через pgvector, отбрасывает всё дальше `RETRIEVAL_MAX_DISTANCE`, затем выбирает до `FAST_RAG_TOP_K` разнообразных chunks. В глобальном режиме действует лимит `FAST_RAG_PER_DOCUMENT_K`, чтобы один файл не вытеснил остальные.
8. Backend строит grounded prompt: system instruction + текущий вопрос + пронумерованные источники. Общий объём контекста ограничен `FAST_RAG_CONTEXT_MAX_CHARS`.
9. LLM начинает генерировать ответ. Backend не ждёт весь ответ, а сразу отправляет token events в UI.
10. После завершения backend пишет usage в ClickHouse и сохраняет ответ в semantic cache.

В этом path LLM не вызывает tools. Решение “какие documents взять” принимает backend retrieval code, а не модель. Это быстрее и дешевле, но менее гибко.

### Agent workflow path: `/agent/run`

```mermaid
sequenceDiagram
    actor User as "👤 Пользователь"
    participant API as "FastAPI"
    participant T as "Temporal"
    participant W as "Worker activity"
    participant Agent as "PydanticAI Agent"
    participant LLM as "LLM"
    participant Tools as "Tools"
    participant DB as "DB / Vector DB"

    User->>API: POST /agent/run
    API->>T: execute_workflow AgentRunWorkflow
    T->>W: run_agent_step(payload)
    W->>Redis: semantic cache lookup
    W->>Agent: agent.run(user_query, deps)
    Agent->>LLM: prompt + tool schemas
    LLM-->>Agent: tool_call retrieve(...)
    Agent->>Tools: retrieve(query, k)
    Tools->>DB: pgvector search
    DB-->>Tools: chunks
    Tools-->>Agent: tool result
    Agent->>LLM: prompt + tool result
    LLM-->>Agent: final AgentRunOutput
    Agent-->>W: validated output
    W->>CH: record_usage
    W->>Redis: semantic cache set
    W-->>T: AgentRunOutput
    T-->>API: result
    API-->>User: JSON response
```

Здесь агент действительно “решает”, нужен ли tool. На практике это означает: LLM генерирует специальный tool call в формате, который PydanticAI и provider понимают. Python-код выполняет этот tool, а результат возвращается обратно модели как новое сообщение.

Если `require_approval=true`, workflow после генерации ответа ждёт signal `approve` или `reject` до 24 часов. Это human-in-the-loop: человек может подтвердить или отклонить ответ.

---

## 8. ⚙️ Переменные окружения

| Переменная | Зачем нужна | Где взять | Обязательная? |
|-----------|-------------|-----------|---------------|
| `POSTGRES_USER` | Пользователь PostgreSQL. | Локально любое значение; default `postgres`. | Да для compose. |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL. | Придумать локально; в prod хранить в secret manager. | Да. |
| `POSTGRES_DB` | Имя app database. | Обычно `app`. | Да. |
| `CLICKHOUSE_USER` | Пользователь ClickHouse. | Локально default `default`. | Да для analytics. |
| `CLICKHOUSE_PASSWORD` | Пароль ClickHouse. | Придумать/задать в `.env`. | Да. |
| `CLICKHOUSE_DB` | Имя БД ClickHouse. | Обычно `analytics`. | Да. |
| `MINIO_ROOT_USER` | Root user MinIO. | Локально можно `minioadmin`; в prod сменить. | Да. |
| `MINIO_ROOT_PASSWORD` | Root password MinIO. | Локально можно default; в prod сменить. | Да. |
| `LANGFUSE_NEXTAUTH_SECRET` | Secret для Langfuse auth. | Сгенерировать случайную строку. | Да для Langfuse container. |
| `LANGFUSE_SALT` | Salt для Langfuse. | Сгенерировать случайную строку. | Да для Langfuse. |
| `LANGFUSE_ENCRYPTION_KEY` | 64 hex chars для шифрования Langfuse. | `openssl rand -hex 32`. | Да для Langfuse. |
| `LANGFUSE_PUBLIC_KEY` | Public key проекта Langfuse. | Langfuse UI → Project Settings → API Keys. | Нет, есть fallback prompt. |
| `LANGFUSE_SECRET_KEY` | Secret key проекта Langfuse. | Langfuse UI → Project Settings → API Keys. | Нет, но нужен для prompt fetch/traces. |
| `LANGFUSE_HOST` | URL Langfuse. | Локально `http://localhost:3000`; в Docker API получает `http://langfuse-web:3000`. | Нет, есть default. |
| `MOONSHOT_API_KEY` | Ключ Moonshot/Kimi LLM. | Moonshot platform. Сервис платный, цена зависит от модели и токенов. | Да, если используешь Moonshot model. |
| `DEEPSEEK_API_KEY` | Ключ DeepSeek LLM. | DeepSeek API dashboard. Сервис платный, обычно дешевле strong Kimi. | Да, если используешь DeepSeek model. |
| `APP_ENV` | Режим окружения: local/prod. | Задать вручную. | Нет, default `local`. |
| `LOG_LEVEL` | Уровень логов. | `INFO`, `DEBUG`, `WARNING`. | Нет. |
| `ADMIN_SECRET` | Защищает `POST /auth/keys`. | Придумать; в prod обязательно сменить. | Да для создания API keys. |
| `STRONG_MODEL` | Основная сильная модель. | Формат `provider/model`, например `moonshot/kimi-k2-turbo-preview`. | Да для LLM. |
| `WEAK_MODEL` | Дешёвая/простая модель. | Формат `provider/model`, например `deepseek/deepseek-v4-flash`. | Нет, но полезна. |
| `AGENT_QUERY_MAX_CHARS` | Максимальная длина вопроса. | Число символов, default `12000`. | Нет. |
| `AGENT_RATE_LIMIT_PER_MINUTE` | Лимит agent-запросов на tenant в минуту. | Число, default `20`. | Нет. |
| `LLM_TIMEOUT_SECONDS` | Таймаут LLM request. | Число секунд, default `60`. | Нет. |
| `RETRIEVAL_MAX_DISTANCE` | Порог релевантности chunks. | Float, default `0.75`. | Нет. |
| `FAST_RAG_CANDIDATE_K` | Сколько ближайших chunks получить до reranking/diversification. | Integer, default `12`. | Нет. |
| `SCOPED_RAG_CANDIDATE_K` | Расширенный пул кандидатов для document/notebook scope. | Integer, default `32`. | Нет. |
| `FAST_RAG_TOP_K` | Сколько chunks оставить в fast stream после отбора. | Integer, default `6`. | Нет. |
| `FAST_RAG_PER_DOCUMENT_K` | Максимум chunks одного документа в глобальном ответе. | Integer, default `2`. | Нет. |
| `FAST_RAG_CONTEXT_MAX_CHARS` | Максимум символов RAG-контекста. | Integer, default `8000`. | Нет. |
| `TEMPORAL_ADDRESS` | Адрес Temporal server. | Локально `localhost:7233`, в Docker `temporal:7233`. | Да для workflows. |
| `TEMPORAL_NAMESPACE` | Namespace Temporal. | Обычно `default`. | Да. |
| `TEMPORAL_TASK_QUEUE` | Очередь worker tasks. | Обычно `agent-tasks`. | Да. |
| `DATABASE_URL` | SQLAlchemy URL PostgreSQL. | Собирается из Postgres credentials. | Да. |
| `REDIS_URL` | URL Redis. | Локально `redis://localhost:6379/0`. | Да. |
| `CLICKHOUSE_URL` | URL ClickHouse analytics DB. | Собирается из ClickHouse credentials. | Да для analytics. |
| `MINIO_ENDPOINT` | Адрес MinIO API. | Локально `localhost:9002`; в Docker `minio:9000`. | Да для файлов. |
| `MINIO_ACCESS_KEY` | Access key MinIO. | Обычно равен `MINIO_ROOT_USER`. | Да. |
| `MINIO_SECRET_KEY` | Secret key MinIO. | Обычно равен `MINIO_ROOT_PASSWORD`. | Да. |
| `MINIO_BUCKET` | Bucket для файлов. | Например `app-files`. | Да. |

Дополнительные settings есть в `packages/core/settings.py`, но не перечислены в `.env.example`: `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `EMBEDDING_BATCH_SIZE`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `BUDGET_ALERT_USD_PER_CALL`, `ENABLE_CODE_EXEC`, `HTTP_FETCH_ALLOWED_DOMAINS`, `ALLOWED_ORIGINS`, `MAX_UPLOAD_BYTES`, `MAX_BULK_TOTAL_BYTES`.

Про AI-ключи:

- Moonshot/Kimi и DeepSeek — внешние платные API. Бесплатность и лимиты нужно проверять в кабинетах провайдеров.
- Стоимость зависит от tokens. Token — это кусочек текста, примерно 3-4 символа английского текста или меньше для других языков. Модель берёт оплату отдельно за input tokens и output tokens.
- Если ключ пустой, LLM-вызовы к соответствующему provider будут падать.

---

## 9. 🚀 Запуск проекта

### Шаг 1: Подготовка

Проверь, что установлены Docker, Git и Make:

```bash
docker --version
docker compose version
git --version
make --version
```

Если Docker не запущен, `docker compose up` не сможет поднять Postgres/Redis/Temporal/MinIO.

### Шаг 2: Ключи и конфиги

Скопируй env:

```bash
cp .env.example .env
```

Открой `.env` и заполни:

```bash
MOONSHOT_API_KEY=...
DEEPSEEK_API_KEY=...
ADMIN_SECRET=замени-на-свой-секрет
LANGFUSE_ENCRYPTION_KEY=<openssl rand -hex 32>
```

Сгенерировать Langfuse encryption key:

```bash
openssl rand -hex 32
```

Langfuse API keys можно добавить после первого запуска: открыть `http://localhost:3000`, создать проект, скопировать keys в `.env`, затем перезапустить containers.

### Шаг 3: Установка зависимостей

Для Docker-first сценария вручную ставить Python/Node зависимости не нужно: Docker соберёт образы.

Если хочешь локально разрабатывать frontend:

```bash
cd apps/ui
npm install
```

Если хочешь локально разрабатывать backend без контейнера:

```bash
pip install -e ".[dev]"
```

В README упоминается `uv sync`; Dockerfile действительно использует `uv sync --no-dev`.

### Шаг 4: Первый запуск

```bash
make up
```

Проверить контейнеры:

```bash
make ps
```

Посмотреть логи:

```bash
make logs
```

Ожидаемые признаки, что всё живо:

- UI открывается на `http://localhost:5173`;
- API health отвечает:

```bash
curl http://localhost:8000/health
```

Ответ:

```json
{"status":"ok"}
```

- Temporal UI открывается на `http://localhost:8233`;
- MinIO console открывается на `http://localhost:9001`;
- Langfuse открывается на `http://localhost:3000`.

### Шаг 5: Создать API key

```bash
curl -X POST http://localhost:8000/auth/keys \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: change-me-before-deploy" \
  -d '{"tenant_id":"demo","name":"local-dev"}'
```

Ответ содержит `raw_key`. Его нужно вставить в UI settings. Сырой ключ показывается один раз, в базе хранится только SHA-256 hash.

### Шаг 6: Тест документа и чата

Создай простой файл:

```bash
printf "Project: AI Agent Platform\nLicense author: Denis\nPurpose: RAG assistant for documents\n" > /tmp/aap-test.txt
```

Загрузи документ:

```bash
curl -X POST http://localhost:8000/documents \
  -H "X-API-Key: <RAW_KEY>" \
  -F "file=@/tmp/aap-test.txt"
```

Подожди, пока status станет `done`:

```bash
curl http://localhost:8000/documents \
  -H "X-API-Key: <RAW_KEY>"
```

Проверь streaming endpoint:

```bash
curl -N -X POST http://localhost:8000/agent/stream \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <RAW_KEY>" \
  -d '{"user_query":"кто автор лицензии и что за проект?"}'
```

Ты должен увидеть события вида:

```text
data: {"type":"token","content":"..."}

data: {"type":"done","answer":"...","sources":["aap-test.txt"],"confidence":0.85,"cached":false}
```

---

## 10. 💸 Стоимость и лимиты

Проект использует платные LLM API Moonshot/Kimi и DeepSeek. Стоимость считается по токенам.

Token — это кусок текста. Для разработчика можно представить, что prompt сериализуется в массив маленьких string fragments, и provider считает длину этого массива. Есть input tokens — что отправили модели, и output tokens — что модель сгенерировала.

Цены в коде `packages/analytics/pricing.py` указаны за 1 000 000 токенов:

| Модель | Input $/1M | Output $/1M | Комментарий |
|-------|------------|-------------|-------------|
| `kimi-k2.6` | 0.60 | 2.50 | Strong Kimi model. |
| `kimi-k2-turbo-preview` | 0.60 | 2.50 | Используется в `.env.example` как strong. |
| `deepseek-v4-flash` | 0.14 | 0.28 | Дешевле и быстрее для простых задач. |
| `deepseek-chat` | 0.14 | 0.28 | Alias в pricing code. |
| `deepseek-reasoner` | 0.55 | 2.19 | Reasoning model. |

Пример: запрос к Kimi, где 5 000 input tokens и 800 output tokens:

```text
input:  5 000 * $0.60 / 1 000 000 = $0.0030
output:   800 * $2.50 / 1 000 000 = $0.0020
total: $0.0050
```

Почему RAG влияет на стоимость: chunks добавляются в prompt, значит увеличивают input tokens. Чем больше `FAST_RAG_CONTEXT_MAX_CHARS`, тем больше потенциальная стоимость и latency.

Как не потратить лишнего:

- держать `FAST_RAG_TOP_K` небольшим;
- не отправлять всю историю чата без summarization;
- использовать semantic cache;
- включить rate limiting;
- на dev использовать дешёвую модель;
- следить за `/analytics/usage`;
- смотреть `BUDGET ALERT` в логах, если один вызов дороже `BUDGET_ALERT_USD_PER_CALL`.

Лимиты в проекте:

- `AGENT_RATE_LIMIT_PER_MINUTE` — сколько agent-запросов в минуту;
- `AGENT_QUERY_MAX_CHARS` — максимальная длина вопроса;
- `LLM_TIMEOUT_SECONDS` — сколько ждать LLM;
- `MAX_UPLOAD_BYTES` — размер одного файла;
- `MAX_BULK_TOTAL_BYTES` — суммарный размер bulk upload.

---

## 11. 🧩 Ключевые решения — почему так, а не иначе

**Решение:** Обычный чат идёт через `/agent/stream`, а не через полный agent workflow.  
**Почему:** Пользователь хочет видеть первый текст быстро. Fast path делает retrieval и прямой streaming LLM без PydanticAI loop.  
**Альтернатива:** Всегда использовать `/agent/run` через Temporal. Это надёжнее, но медленнее и хуже для UX интерактивного чата.

**Решение:** Temporal используется для ingestion и HITL.  
**Почему:** Обработка документов и ожидание approve могут длиться долго. Temporal сохраняет состояние и позволяет retry.  
**Альтернатива:** Background tasks в FastAPI. Проще, но хуже переживает рестарты и сложнее отслеживается.

**Решение:** pgvector вместо отдельной vector DB.  
**Почему:** Уже есть PostgreSQL, RLS и tenant tables. pgvector даёт semantic search без отдельной инфраструктуры.  
**Альтернатива:** Qdrant/Pinecone. Лучше для масштабного vector search, но добавляет сервис/стоимость.

**Решение:** Semantic cache в Redis.  
**Почему:** Похожие вопросы могут возвращать готовый ответ без LLM, это быстрее и дешевле.  
**Альтернатива:** Только точный HTTP cache. Он не поймает переформулированные вопросы.

**Решение:** API keys хранятся как SHA-256 hash.  
**Почему:** Если база утечёт, сырые ключи не лежат в таблице.  
**Альтернатива:** Хранить raw keys. Проще, но небезопасно.

**Решение:** `sql_query` tool возвращает ошибку как JSON-строку, а не роняет activity.  
**Почему:** LLM может увидеть ошибку и попробовать исправить запрос или объяснить пользователю проблему.  
**Альтернатива:** Бросать exception. Тогда workflow может упасть раньше, чем модель адаптируется.

**Решение:** Документы хранятся в MinIO, а chunks в PostgreSQL.  
**Почему:** Bytes файлов удобнее хранить как objects, а searchable text/vectors — в БД.  
**Альтернатива:** Класть всё в PostgreSQL. Проще на старте, но хуже для больших файлов.

**Решение:** Row Level Security через `tenant_id`.  
**Почему:** Даже если разработчик забудет фильтр, БД дополнительно защищает строки tenant’а.  
**Альтернатива:** Только фильтры в коде. Быстрее писать, но выше риск утечки данных между tenants.

---

## 12. ❓ FAQ для новичка в AI

### Почему агент иногда даёт разные ответы на один вопрос?

LLM генерирует текст вероятностно. Даже при одинаковом prompt provider может вернуть немного другой ответ, особенно если temperature не зафиксирована. В этом проекте `temperature` явно не задаётся в большинстве LLM-вызовов, значит используется default provider’а.

### Что такое temperature и почему она здесь именно такая?

Temperature — это параметр случайности генерации. Аналогия: при `0` модель выбирает самый вероятный следующий token, при больших значениях чаще выбирает альтернативы. В текущем коде temperature почти не управляется, потому что для RAG-ответов важнее стабильность prompt’а, retrieval и контекста. Если нужны более повторяемые ответы, стоит явно поставить низкую temperature.

### Почему нельзя просто сделать один большой prompt вместо агента с инструментами?

Можно, и fast `/agent/stream` почти так и делает: retrieval context + query → LLM. Но один большой prompt не умеет сам сходить в SQL, получить URL, выполнить расчёт или уточнить данные. Tools нужны, когда данные нужно получать динамически.

### Как агент знает, когда остановиться?

В PydanticAI path модель должна вернуть финальный результат в формате `AgentRunOutput`. Пока ей нужны данные, она может вернуть tool call. Когда модель возвращает structured output, PydanticAI валидирует его и завершает loop.

### Что делать, если LLM вернул невалидный JSON для tool call?

PydanticAI частично берёт это на себя: он знает schema tools/result и может ретраить/валидировать. Если проблема повторяется, нужно смотреть provider logs, system prompt и совместимость tool calling. В `packages/llm/client.py` уже есть provider-specific fixes для Kimi/DeepSeek.

### Почему используется именно Kimi/DeepSeek, а не OpenAI/Claude/Gemini?

Код построен вокруг OpenAI-compatible API. Moonshot и DeepSeek подходят под этот интерфейс и указаны в settings. OpenAI/Claude/Gemini можно добавить, но нужно прописать provider config, API key, model quirks и pricing.

### Зачем платить за API, если есть ChatGPT?

ChatGPT — это готовый продукт для человека. API — это строительный блок для приложения: можно передавать документы, управлять prompt, писать usage в ClickHouse, ограничивать tenants, стримить в свой UI и интегрировать workflows.

### Как понять, что агент “завис”?

Смотри логи API/worker. Для `/agent/stream` полезны сообщения:

- `agent_stream cache lookup`;
- `agent_stream retrieve`;
- `agent_stream first token`;
- `agent_stream done`.

Если `first token` долго не появляется, проблема до или во время первого ответа LLM: retrieval, embedding или provider latency. Если first token быстрый, но done долго, модель медленно генерирует длинный ответ.

### Как перезапустить?

Локально:

```bash
docker compose restart api worker
```

Если проблема в инфраструктуре:

```bash
docker compose ps
docker compose logs --tail=100 api worker temporal redis postgres
```

Temporal workflows не должны теряться при рестарте worker’а: worker переподключится и продолжит выполнять activities.

### Почему модель иногда отвечает “не нашёл релевантной информации”?

Fast RAG path фильтрует chunks по `RETRIEVAL_MAX_DISTANCE`. Если документы плохо распарсились, ещё не имеют status `done`, или вопрос слишком далёк от текста chunks, retrieval вернёт пустой список. Тогда backend специально не заставляет LLM фантазировать.

### Есть ли здесь настоящая мультиагентность?

Нет в смысле “несколько агентов общаются между собой”. Есть `MultiStepResearchWorkflow`: он запускает несколько child workflows по sub-queries и потом синтезирует финальный ответ. Это orchestration pattern, а не CrewAI/AutoGen-style multi-agent conversation.

### Есть ли MCP?

Нет. MCP в этом проекте не подключён. Tools реализованы напрямую в Python через PydanticAI.

---

## 13. 🗃️ Модель данных и где что хранится

У проекта не одно «хранилище», а четыре хранилища с разными задачами. PostgreSQL — источник истины для прикладных сущностей и vectors. MinIO хранит bytes исходных файлов и previews. Redis хранит короткоживущий semantic cache и rate-limit counters. ClickHouse хранит события использования LLM, по которым строится аналитика.

```mermaid
erDiagram
    API_KEYS {
        uuid id PK
        string tenant_id
        string key_hash UK
        boolean is_active
        datetime last_used_at
    }

    DOCUMENTS {
        uuid id PK
        string tenant_id
        string filename
        string source_type
        string source_url
        string object_key
        enum status
        string processing_stage
        text summary
        json suggested_questions
        json warnings
    }

    DOCUMENT_ASSETS {
        uuid id PK
        string tenant_id
        uuid document_id FK
        int page_number
        string asset_kind
        string preview_object_key
        text ocr_text
        text vision_description
        enum status
    }

    CHUNKS {
        uuid id PK
        string tenant_id
        uuid document_id FK
        int chunk_idx
        text content
        vector embedding
        json metadata
    }

    NOTEBOOKS {
        uuid id PK
        string tenant_id
        string title
        text description
        text summary
        json suggested_questions
        json key_topics
    }

    NOTEBOOK_DOCUMENTS {
        uuid notebook_id PK_FK
        uuid document_id PK_FK
        string tenant_id
    }

    CHAT_SESSIONS {
        uuid id PK
        string tenant_id
        string title
        string model
        string scope_type
        uuid document_id FK
        uuid notebook_id FK
    }

    CHAT_MESSAGES {
        uuid id PK
        uuid session_id FK
        string tenant_id
        string role
        text content
        json sources
        boolean cached
    }

    DOCUMENTS ||--o{ CHUNKS : contains
    DOCUMENTS ||--o{ DOCUMENT_ASSETS : contains
    NOTEBOOKS ||--o{ NOTEBOOK_DOCUMENTS : groups
    DOCUMENTS ||--o{ NOTEBOOK_DOCUMENTS : belongs_to
    CHAT_SESSIONS ||--o{ CHAT_MESSAGES : contains
    DOCUMENTS o|--o{ CHAT_SESSIONS : scopes
    NOTEBOOKS o|--o{ CHAT_SESSIONS : scopes
```

### `documents`

Одна строка соответствует одному источнику знаний. Источник может быть:

- `file` — загруженный файл;
- `url` — обычная web-страница, text или PDF по URL;
- `github` — GitHub repository, tree или отдельный blob/raw file.

`object_key` указывает на исходный объект в MinIO. Поля `status` и `processing_stage` отвечают на разные вопросы:

- `status`: общий итог `pending`, `processing`, `done`, `failed`;
- `processing_stage`: более точный этап вроде queued, OCR/Vision, embedding;
- `processed_pages` / `total_pages`: прогресс visual-документа;
- `warnings`: частичные проблемы, при которых документ всё же может быть полезен;
- `error`: причина полной ошибки.

`summary` и `suggested_questions` строятся при ingestion. Это не RAG chunks и не генерируются при каждом открытии страницы.

### `document_assets`

Asset — отдельная визуальная единица: страница PDF, загруженное изображение или найденная в URL/GitHub схема. Для неё сохраняются OCR text, confidence, Vision description, размеры, статус и ключ preview.

Preview отдаётся через защищённый API endpoint, а не прямой публичный URL MinIO. Исключение в текущей реализации: asset типа `url_image` не отдаётся через content endpoint, то есть он участвует в извлечении знаний, но не обязательно доступен как UI preview.

### `chunks`

Chunk — поисковая единица RAG. Он содержит:

- исходный текст фрагмента;
- embedding фиксированной размерности `384`;
- порядковый номер;
- `document_id` и `tenant_id`;
- metadata, например page, asset id и тип визуального источника.

При reindex старые chunks заменяются новой версией. Ответ не читает исходный файл целиком: runtime retrieval работает именно по `chunks`.

### `notebooks` и `notebook_documents`

Notebook — коллекция документов, а не копия данных. Связующая таблица хранит membership. Поэтому один документ может входить в несколько notebooks.

Notebook insights содержат общий summary, suggested questions и key topics. При изменении состава документов insights сбрасываются. При завершении reindex/ingestion связанного документа они тоже инвалидируются, потому что старое резюме уже может не соответствовать источникам.

### `chat_sessions` и `chat_messages`

Session хранит заголовок, выбранную модель и необязательный scope:

- scope отсутствует — глобальный поиск по knowledge base tenant’а;
- `document` — поиск только внутри одного документа;
- `notebook` — поиск только по документам одной коллекции.

Ограничение БД запрещает одновременно привязать session и к document, и к notebook. При удалении scoped сущности FK становится `NULL`; сами сообщения не удаляются.

Messages хранят роль, текст, citations и флаг semantic-cache hit. Важно: это история для UI и аудита, а не conversation memory модели. Текущий `/agent/stream` передаёт LLM только новый вопрос и найденные chunks.

### `api_keys`

В таблице лежит SHA-256 hash, tenant, имя, активность и время последнего использования. Raw key возвращается только при создании. Проверка ключа кэшируется в памяти конкретного API-процесса на 30 секунд.

### MinIO

Ключи объектов имеют tenant/document prefix:

```text
{tenant_id}/{document_id}/{filename}
{tenant_id}/{document_id}/assets/page-1.webp
{tenant_id}/{document_id}/visual-batches/1-10.json
```

Временные visual batch JSON удаляются после успешной финализации. Оригинал и previews живут до удаления документа. Для URL дополнительно хранится sidecar со списком найденных изображений.

### Redis

Semantic cache не требует Redis Vector Search. Для каждого tenant хранится ZSET последних entry ids и отдельные JSON strings с embedding вопроса и `AgentRunOutput`.

Параметры зафиксированы в коде:

- TTL — 1 час;
- hit threshold — cosine similarity строго выше `0.92`;
- scan — до 500 последних entries;
- hard cap — 1000 entries на tenant.

Scoped document/notebook chat cache пропускает, потому что одинаковый вопрос в разных scopes имеет разный смысл. При upload, reindex и delete кэш tenant’а очищается.

### ClickHouse

`analytics.llm_usage_events` содержит model/provider, prompt/completion/total tokens, рассчитанную стоимость, latency, status, workflow id и run id. `/analytics/usage` группирует данные по модели и по дням в пределах tenant.

---

## 14. 🧭 UI, API и жизненный цикл приложения

### Запуск backend

При старте FastAPI:

1. включается tracing для сервиса `aap-api`;
2. embedding model прогревается тестовой строкой; ошибка warmup не останавливает API;
3. создаётся Temporal client и сохраняется в `app.state.temporal`;
4. регистрируются routers;
5. CORS берётся из `ALLOWED_ORIGINS`, а в local режиме без настройки разрешается `*`.

`GET /health` возвращает только `{"status":"ok"}`. Это liveness endpoint процесса, а не полноценная проверка Postgres, Redis, MinIO, Temporal, ClickHouse и LLM provider.

### Запуск worker

Worker — отдельный процесс. Он тоже прогревает embeddings, подключается к Temporal и слушает одну task queue. Зарегистрированы три workflows:

- `IngestionWorkflow`;
- `AgentRunWorkflow`;
- `MultiStepResearchWorkflow`.

Невоспроизводимые операции — сеть, БД, MinIO, OCR, embeddings, LLM — находятся в activities. Workflow code хранит только порядок, timers, signals и retry policy. Поэтому Temporal может replay workflow после рестарта.

### Навигация UI

Основные маршруты:

| Route | Что показывает |
|---|---|
| `/chat` | чат, session history, model selector, HITL toggle, scope banner |
| `/documents` | upload/drop zone, URL/GitHub input, список и статусы документов |
| `/documents/:id` | summary, questions, progress, warnings, chunks, visual assets |
| `/notebooks` | список и создание коллекций |
| `/notebooks/:id` | состав, upload, insights, scoped chat |
| `/analytics` | стоимость, tokens, latency и вызовы по моделям/дням |
| `/settings` | redirect, открывающий settings UI |
| `/workflows` | redirect обратно в chat |

`WorkflowsView.vue` есть в репозитории, но текущий router его не использует, и sidebar не содержит отдельного раздела workflows. Human approval живёт прямо в chat cards.

### Настройки браузера

UI хранит API base URL, язык и тему в `localStorage`. Если API key не внедрён через build-time environment, он тоже хранится в `localStorage` как plain text. `useApi()` добавляет `X-API-Key` ко всем запросам.

Статус ключа не проверяется отдельным запросом при вводе. Он становится `valid` после первого успешного API response и `invalid` после HTTP 401.

### Сессии чата

При открытии UI загружает `/sessions` и автоматически выбирает последнюю обновлённую/первую возвращённую session. При выборе session отдельно загружаются messages.

Если пользователь отправляет первый вопрос без session, UI сначала создаёт её, используя первые 40 символов вопроса как title. Если session называлась «Новый чат», title обновляется асинхронно после отправки.

Сохранение сообщения не объединено с LLM-запросом в одну backend-транзакцию:

1. UI fire-and-forget сохраняет user message;
2. отдельно запускает `/agent/stream` или `/agent/run`;
3. после `done` UI fire-and-forget сохраняет assistant message.

Следствие: при сетевом сбое возможна session только с user message, отсутствующий assistant message или показанный в браузере, но не сохранённый ответ.

### SSE protocol

`POST /agent/stream` отвечает `text/event-stream`. UI ожидает JSON events:

```json
{"type":"token","content":"часть ответа"}
{"type":"done","answer":"полный ответ","sources":[],"confidence":0.85,"cached":false}
{"type":"error","message":"описание ошибки"}
```

До первого token UI показывает loading indicator. После первого token создаёт streaming message и дописывает текст. `done` заменяет накопленный текст каноническим полным ответом и добавляет citations.

При переключении/сбросе state активный `AbortController` отменяет stream. Частичный ответ можно оставить без streaming cursor или удалить — это UI state, он не считается завершённым серверным сообщением.

### Citations

Backend формирует `CitationSource` из выбранных chunks: document id, chunk id, filename, content/excerpt и порядковый source id. После генерации `select_answer_sources` пытается оставить только те источники, на которые реально ссылается ответ. UI показывает sources у assistant message и умеет вести на document detail с конкретным chunk.

Confidence в fast path не является вероятностью, рассчитанной моделью:

- `0.85`, если есть ответ и выбранные sources;
- `0.2`, если текст есть, но sources не подтверждены;
- `0.0`, если модель не дала ответ;
- `0.2`, если retrieval ничего не нашёл.

В structured agent path confidence возвращает сама LLM внутри валидируемой схемы.

### Полный API

Кроме `/health` и `/auth/keys`, endpoints используют tenant из `X-API-Key`.

| Method | Endpoint | Результат |
|---|---|---|
| `POST` | `/auth/keys` | создать tenant API key по admin secret |
| `POST` | `/agent/stream` | быстрый SSE RAG |
| `POST` | `/agent/run` | Temporal agent run, optional HITL |
| `POST` | `/agent/research` | parallel sub-research + synthesis |
| `GET` | `/workflows/{id}/result` | получить результат или pending |
| `POST` | `/workflows/{id}/approve` | послать approve signal |
| `POST` | `/workflows/{id}/reject` | послать reject signal |
| `GET/POST` | `/sessions` | список / создание sessions |
| `GET/PATCH/DELETE` | `/sessions/{id}` | чтение/переименование/удаление session |
| `GET/POST` | `/sessions/{id}/messages` | история / добавление message |
| `GET/POST` | `/documents` | список / upload файла |
| `POST` | `/documents/bulk` | до 20 файлов после общей валидации |
| `POST` | `/documents/url/check` | проверить внешний источник без создания document |
| `POST` | `/documents/url` | сохранить URL/GitHub source и начать ingestion |
| `GET` | `/documents/{id}` | состояние и metadata |
| `GET` | `/documents/{id}/chunks` | paginated chunk previews |
| `GET` | `/documents/{id}/assets` | paginated visual assets |
| `GET` | `/documents/{id}/assets/{asset}/content` | защищённый WebP preview |
| `POST` | `/documents/{id}/reindex` | обновить источник и/или пересобрать index |
| `DELETE` | `/documents/{id}` | удалить DB rows и MinIO objects |
| `GET/POST` | `/notebooks` | список / создать collection |
| `GET/DELETE` | `/notebooks/{id}` | detail / удалить collection |
| `PUT` | `/notebooks/{id}/documents` | полностью заменить membership |
| `POST` | `/notebooks/{id}/documents/upload` | загрузить и сразу прикрепить документ |
| `POST` | `/notebooks/{id}/insights` | пересобрать overview/topics/questions |
| `GET` | `/analytics/usage?days=N` | tenant usage за 1–365 дней |

---

## 15. 👤 Пользовательские сценарии от начала до конца

### Сценарий 1. Первый вход и подключение

Предусловие: администратор уже создал raw API key через `/auth/keys`.

1. Пользователь открывает UI.
2. Без ключа навигация видна, но chat input и операции с документами заблокированы.
3. В settings пользователь вводит key и при необходимости API base URL.
4. UI сохраняет конфигурацию и начинает загружать sessions/documents.
5. Первый успешный request меняет индикатор на connected; 401 отмечает key как invalid.

Backend по ключу находит `api_keys.key_hash`, проверяет `is_active`, возвращает `tenant_id` dependency и обновляет `last_used_at`. После этого все запросы пользователя автоматически ограничены этим tenant.

### Сценарий 2. Загрузка обычного текстового документа

1. Пользователь перетаскивает файл на `/documents`.
2. UI отправляет multipart `POST /documents`.
3. API проверяет грубый `Content-Length`, затем читает файл с точным лимитом 50 MB.
4. Bytes пишутся в MinIO.
5. В PostgreSQL создаётся `Document(status=pending, processing_stage=queued)`.
6. Semantic cache tenant’а очищается.
7. API запускает `IngestionWorkflow` с уникальным id и возвращает HTTP 202.
8. UI показывает pending и периодически обновляет список/detail.
9. Worker переводит документ в processing.
10. В text activity файл парсится, chunks создаются и embedятся внутри одной activity.
11. В одной tenant transaction старые chunks заменяются, сохраняются summary/questions/warnings.
12. Workflow ставит status `done`.
13. После этого документ доступен для global, document и notebook RAG.

Если Temporal workflow не удалось даже запустить, API ставит `failed` и возвращает 503. Если activity падает после retries, workflow вызывает `mark_failed`.

### Сценарий 3. Сканированный PDF или изображение

1. Начало такое же: MinIO, DB row, Temporal.
2. Worker определяет visual document и считает страницы.
3. Страницы делятся на batches; одновременно выполняются максимум два batch.
4. Для каждой страницы создаётся ограниченный по размеру render и WebP preview.
5. PaddleOCR извлекает текст и confidence.
6. Если OCR недостаточен или странице нужен смысловой разбор, вызывается Vision model.
7. OCR text и Vision description разделяются на sections.
8. Для страницы upsertится `DocumentAsset`; metadata asset попадает в будущие chunks.
9. Progress обновляется после каждой страницы, activity посылает heartbeat.
10. Batch сохраняет небольшой JSON в MinIO, а не большой payload в Temporal history.
11. Finalize activity объединяет batches, строит insights, chunks и embeddings.
12. Временные batch objects удаляются.

Отдельная плохая страница может дать warning и failed asset, но не обязана провалить весь документ. Документ падает полностью, если после всех страниц нет ни одного извлекаемого segment.

### Сценарий 4. Добавление web URL или GitHub

1. Пользователь вводит URL и сначала вызывает check.
2. API нормализует URL и проверяет scheme/host.
3. В production без `HTTP_FETCH_ALLOWED_DOMAINS` URL ingestion закрыт.
4. Redirect обрабатывается вручную, и каждая новая цель снова проверяется.
5. Для HTML извлекаются title, readable text и ссылки на полезные изображения.
6. Для text source добавляется заголовок с source URL.
7. PDF сохраняется как binary и дальше идёт visual pipeline.
8. GitHub распознаёт:
   - repository URL;
   - `tree/{ref}/{path}`;
   - `blob/{ref}/{path}`;
   - `raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}`.
9. GitHub repository/tree собирается из archive, фильтруя полезные Markdown/text/config/diagram source files; blob получает один raw file.
10. Нормализованный source и image sidecar сохраняются в MinIO, затем запускается обычный ingestion.
11. Из найденных схем/изображений worker извлекает дополнительный OCR/Vision text, который участвует в RAG.

URL source имеет лимит 10 MB. Число найденных изображений ограничено отдельно: 8 для обычного URL и 24 для GitHub; одно изображение — до 5 MB.

### Сценарий 5. Глобальный вопрос в чате

1. Пользователь создаёт session или UI создаёт её автоматически.
2. User message сразу появляется в UI и асинхронно сохраняется.
3. UI вызывает `/agent/stream` без scope.
4. API проверяет длину вопроса и minute rate limit.
5. Semantic cache ищет похожий вопрос только внутри tenant.
6. При hit готовый ответ отправляется одним token event и затем done.
7. При miss вопрос embedится, pgvector возвращает кандидатов.
8. Backend ограничивает distance, разнообразит документы и строит grounded context.
9. LLM получает только этот вопрос и этот context.
10. Tokens сразу уходят через SSE.
11. После завершения backend выбирает citations, пишет usage в ClickHouse и ответ в Redis.
12. UI сохраняет assistant message.

Если relevant chunks нет, LLM вообще не вызывается. Backend возвращает контролируемое «не нашёл релевантной информации».

### Сценарий 6. Вопрос по одному документу

Пользователь открывает document detail и нажимает chat или один из suggested questions.

1. UI создаёт новую session с `scope_type=document`.
2. URL `/chat` несёт `document` и optional `ask` query parameters.
3. Backend проверяет, что документ принадлежит tenant и имеет status `done`.
4. Retrieval получает `document_id` filter.
5. Semantic cache полностью пропускается.
6. Diversity limit «не больше N chunks на документ» не нужен: все chunks уже из одного файла.
7. В chat показывается scope banner; session history помечается как document-scoped.

Переключатель human approval для scoped запроса фактически отключается: UI принудительно отправляет fast stream. Это не ошибка интерфейса, а текущее ограничение реализации.

### Сценарий 7. Notebook и вопрос по коллекции

1. Пользователь создаёт notebook с title/description и списком existing document ids.
2. Можно позже полностью заменить membership или загрузить новый файл прямо в notebook.
3. Uploaded file становится обычным Document и одновременно получает NotebookDocument link.
4. До окончания ingestion он виден в collection, но не участвует в scoped RAG.
5. `POST /notebooks/{id}/insights` берёт только документы со status `done`.
6. Система строит общий summary, questions и key topics.
7. Перед записью backend повторно проверяет набор ready document ids. Если membership изменился во время LLM call, возвращается 409 вместо сохранения устаревшего overview.
8. При открытии notebook chat создаётся `scope_type=notebook`.
9. `/agent/stream` разворачивает notebook в список ready document ids и фильтрует retrieval.
10. Кэш пропускается, HITL отключён.

Удаление notebook удаляет только collection и links. Сами документы остаются в knowledge base.

### Сценарий 8. Human-in-the-loop

HITL работает только для глобального chat.

1. Пользователь включает «Human approval» и отправляет вопрос.
2. UI сохраняет user message и вызывает `/agent/run` с `require_approval=true`.
3. API запускает `AgentRunWorkflow` асинхронно и возвращает workflow id.
4. Worker выполняет настоящий PydanticAI agent loop.
5. Готовый ответ пока не возвращается пользователю как обычный assistant message.
6. Workflow выполняет approval notification activity и ждёт signal до 24 часов.
7. UI сохраняет pending workflow id в `localStorage` и показывает HITL card.
8. После approve UI посылает signal и polls `/result` с exponential backoff до 5 минут.
9. Workflow завершается исходным ответом; UI заменяет card ответом и сохраняет его в session.
10. После reject workflow завершает ответ с префиксом `[REJECTED by reviewer]`, но текущий UI просто удаляет pending card и не polls rejected result.
11. Если signal не пришёл за 24 часа, workflow возвращает ответ с `[APPROVAL TIMED OUT]`.

Здесь есть два разных timeout: Temporal ждёт решение 24 часа, но браузер после approve polls только 5 минут. Pending state до approve хранится только в browser localStorage, не в PostgreSQL.

### Сценарий 9. Multi-step research

Этот режим доступен через API, но не имеет активного отдельного UI.

1. Клиент отправляет main query и заранее подготовленный список sub-queries.
2. API валидирует длину каждого вопроса и запускает `MultiStepResearchWorkflow`.
3. Workflow запускает отдельный `AgentRunWorkflow` для каждого sub-query.
4. Child workflows идут параллельно.
5. После fan-in ответы собираются в synthesis prompt.
6. Ещё одна `run_agent_step` activity строит финальный ответ.
7. Citation sources child results дедуплицируются по `(document_id, chunk_id)` и добавляются к final sources.

Это не autonomous planner: sub-queries не придумываются автоматически. Это также не разговор нескольких персонажей-агентов. Это параллельная orchestration одного типа агента.

### Сценарий 10. Reindex

Для upload-файла reindex повторно использует оригинал из MinIO. Для URL/GitHub backend сначала заново скачивает источник.

1. Reindex запрещён, пока status pending/processing.
2. URL/GitHub source сравнивается с сохранёнными объектами.
3. Если внешний источник не изменился и документ уже `done`, API возвращает `changed=false`, workflow не стартует.
4. Если изменился, object/metadata обновляются, status сбрасывается в pending.
5. Semantic cache очищается.
6. Новый workflow заменяет chunks/assets/insights.

### Сценарий 11. Удаление документа

1. Backend проверяет tenant ownership.
2. Удаляет Document; FK cascade удаляет chunks, assets и notebook links.
3. Собирает object keys оригинала, URL sidecar и previews.
4. После DB transaction пытается удалить каждый MinIO object.
5. Ошибка удаления object логируется, но API не откатывает уже совершённое удаление DB.
6. Semantic cache очищается.

Это означает, что при сбое MinIO возможен orphan object, но не видимый пользователю «полуживой» документ.

### Сценарий 12. Просмотр аналитики

1. UI запрашивает `/analytics/usage?days=30`.
2. ClickHouse агрегирует calls, tokens, cost и average latency по model/provider.
3. Второй query строит daily series.
4. Ответ строго фильтруется по tenant.

Если ClickHouse недоступен во время ответа агента, запись usage обычно является best effort и основной ответ продолжает работать. Но сам analytics endpoint при ошибке ClickHouse возвращает 500.

---

## 16. 🛡️ Tenant isolation, авторизация и безопасность

### Граница tenant

Tenant определяется только проверенным API key, а не полем request body. В `/agent/run`, `/agent/research`, upload и остальных маршрутах backend перезаписывает/добавляет tenant id после auth.

Защита двухуровневая:

1. application queries явно фильтруют `tenant_id`;
2. `tenant_session()` выполняет `set_config('app.tenant_id', tenant_id, true)`, после чего PostgreSQL RLS применяет tenant policies.

Workflow ids содержат tenant, а signal/result routes дополнительно проверяют, что id относится к текущему tenant.

### API keys

- raw key генерируется через `secrets.token_urlsafe(32)`;
- в БД сохраняется только SHA-256 hash;
- создание ключа защищено `X-Admin-Secret`;
- inactive key не принимается;
- positive auth result кэшируется на 30 секунд;
- в non-local окружении default admin secret запрещает запуск settings validation.

SHA-256 здесь не password hashing. Это допустимо для случайного ключа с высокой энтропией, но не было бы хорошей схемой для пользовательского пароля.

### SQL tool

Агент не получает произвольный DB connection. Tool:

- требует literal placeholder `{tenant_id}`;
- разрешает только `SELECT`;
- запрещает locking clauses;
- проверяет FROM/JOIN tables по allowlist;
- запрещает comma joins как обход простого parser;
- не разрешает `api_keys`, catalogs и arbitrary tables;
- ставит transaction read-only и timeout 5 секунд;
- ограничивает результат 500 строк.

Это существенная защита, но parser основан на regular expressions, а не полном SQL AST. Для высокорискового production лучше заменить свободный SQL на заранее определённые query tools.

### HTTP и URL ingestion

В production внешний fetch fail-closed без domain allowlist. Проверяются private, loopback, link-local, reserved, multicast и unspecified addresses. Redirects не следуются автоматически: каждая target URL валидируется заново.

В local режиме fallback с DNS resolution снижает риск SSRF, но сам код честно признаёт риск DNS rebinding. Production должен использовать `HTTP_FETCH_ALLOWED_DOMAINS`.

### Code execution

`code_exec` выключен по умолчанию. При включении он запускает subprocess:

- без credentials/environment;
- с `-S` и `-E`;
- без third-party packages;
- с timeout 10 секунд.

Это ограничение, но не полноценный security sandbox: нет container/VM boundary, syscall filter, filesystem isolation или resource quotas кроме wall-clock timeout. На недоверенных пользователях `ENABLE_CODE_EXEC` лучше оставлять false.

### Browser storage

Если key не внедрён через environment, UI хранит его plain text в localStorage. Это удобно для local/self-hosted режима, но XSS в origin сможет прочитать ключ. Для публичного deployment лучше перейти на серверную session/cookie модель или изолированный reverse proxy.

### CORS и secrets

В local режиме пустой `ALLOWED_ORIGINS` превращается в wildcard. В non-local settings требуют непустой список и запрещают `*`. Это предотвращает случайный production launch с полностью открытым CORS.

MinIO в compose использует root credentials как app credentials. Для production правильнее создать отдельного пользователя и policy только на нужный bucket/prefix.

---

## 17. 🚨 Ошибки, повторы и деградация сервисов

### Ingestion retries

Большинство ingestion activities выполняются максимум три раза:

- initial interval 1 секунда;
- exponential/backoff до 30 секунд;
- maximum attempts 3.

Visual batch имеет timeout 30 минут и heartbeat timeout 2 минуты. Text ingestion — start-to-close timeout 42 минуты и heartbeat timeout 2 минуты. Если retries исчерпаны, workflow извлекает наиболее содержательную root cause из цепочки `ActivityError`, обрезает её до 2000 символов и вызывает `mark_failed` без retry.

### Agent workflow retries

`run_agent_step` имеет максимум две попытки, initial 2 секунды и maximum 30 секунд. `ValueError` и `ApplicationError` объявлены non-retryable.

Semantic cache в worker path не обёрнут в best-effort `try/except`, поэтому недоступный Redis способен провалить agent activity. В fast streaming path Redis cache get/set, ClickHouse usage и часть side effects деградируют мягко.

### Fast stream errors

Ошибки после открытия SSE не могут превратиться в обычный HTTP 500. Generator отправляет event `type=error`, UI заменяет partial message ошибкой. Ошибки scope validation происходят до открытия stream и возвращают 404/409 как обычный HTTP response.

### Частичные сбои

- warmup embeddings failed: сервис стартует и повторит при первом use;
- ClickHouse usage insert failed: ответ пользователю сохраняется;
- Redis cache failed в fast path: выполняется обычный retrieval/LLM;
- одна visual page failed: warning/failed asset, остальные страницы продолжаются;
- MinIO cleanup failed после DB delete/finalize: warning и возможный orphan object;
- notebook sources изменились во время insights: 409 и просьба retry;
- Temporal start failed после upload: Document переводится в failed;
- LLM вернул пустой stream: controlled answer «Не удалось получить ответ от модели».

### Что наблюдать

Для чата важны timestamps:

- cache lookup latency;
- retrieval latency и matched filenames/scores;
- first-token latency;
- total latency;
- prompt/completion tokens.

Для visual ingestion:

- pages range;
- OCR latency;
- Vision calls/latency;
- unrecognized pages;
- warning count;
- activity heartbeat и processing progress.

Temporal UI показывает workflow history и retries. Langfuse подключается опционально для traces/prompts. ClickHouse отвечает за агрегированную стоимость, но не заменяет operational logs.

---

## 18. 🧪 Тесты, evals и проверка качества

### Unit tests backend

Тесты покрывают:

- schemas и pagination;
- tenant isolation;
- API-key auth cache;
- agent rate limit;
- SQL tool restrictions;
- semantic cache;
- LLM client provider behavior;
- RAG citations и reranking/diversity;
- object storage wrapper;
- document assets, chunk storage, metadata и summaries;
- visual/OCR workflow behavior;
- URL/GitHub sources и URL images;
- reindex;
- notebook mode, insights и summaries;
- chat session scope;
- settings security и compose environment.

### Frontend tests

Node tests проверяют чистые UI utilities и layout contracts:

- API config;
- i18n и theme;
- citations;
- document/notebook normalization;
- chat scope;
- analytics transforms;
- settings route;
- pane/sidebar state;
- ожидаемые элементы document/notebook layouts.

Это не browser E2E: Vue components не проходят полный click-through в реальном браузере в этих tests.

### E2E

E2E требуют live Docker services, Temporal worker и иногда provider access. Есть smoke flow, URL image ingestion и полный URL/GitHub lifecycle.

### Golden evals

`evals/golden/suite.py` и datasets проверяют retrieval/answer quality на заранее ожидаемых случаях, включая OCR/Vision и GitHub. `retrieval_eval.py` оценивает retrieval отдельно, `golden_eval.py` — end-to-end expectations.

Важно различать:

- unit test доказывает локальный контракт кода;
- integration/E2E доказывает связность сервисов;
- golden eval измеряет качество AI-результата, которое не сводится к `pass/fail` обычной функции.

Рекомендуемый baseline перед изменением RAG или ingestion:

```bash
pytest -q
cd apps/ui && npm test
npm run build
```

После изменения prompts, embedding model, chunk size, retrieval threshold или OCR/Vision нужно дополнительно запускать golden evals. Обычные unit tests не покажут, что ответы стали менее релевантными.

---

## 19. ⚠️ Реальные ограничения текущей версии

Это рабочая self-hosted платформа для небольшой команды, но не законченный public SaaS. Ниже не «будущие идеи», а границы текущего кода.

### Нет разговорной памяти модели

История видна пользователю и лежит в PostgreSQL, но в prompt не передаётся. Вопрос «а что ты имел в виду в прошлом ответе?» не имеет контекста прошлого ответа, если он не повторён в новом сообщении или не содержится в документах.

### Два режима дают разное поведение

Fast chat не вызывает tools и имеет heuristic confidence. `/agent/run` вызывает tools и получает structured confidence от LLM. Один и тот же вопрос может получить отличающийся ответ, citations и cache behavior.

### HITL — review после генерации, а не до внешнего действия

Агентские tools в основном read-only, поэтому это разумно. Но approval не блокирует каждый tool call и не предоставляет reviewer’у diff/план действий. Он просто удерживает уже сгенерированный ответ.

### Reject UX неполный

Temporal workflow после reject формирует результат с `[REJECTED by reviewer]`, но UI удаляет card и не сохраняет rejected result. Серверная семантика и browser UX расходятся.

### Pending HITL хранится в одном браузере

Workflow durable в Temporal, но список ожидающих cards — localStorage. Другой браузер, очищенный storage или другой пользователь tenant’а не увидит pending approvals автоматически.

### Research требует готовых sub-queries

Система не разбивает main query самостоятельно и не корректирует план на основе промежуточных результатов. API client должен подготовить sub-queries заранее.

### URL fetching зависит от allowlist

Правильный production setup безопаснее, но ограничивает произвольный web research. Allowlist нужно поддерживать явно.

### Semantic cache не учитывает версию prompt/model/documents в key

Upload/reindex/delete очищают tenant cache, а TTL короткий. Но смена model, prompt или некоторых settings сама по себе не инвалидирует existing entries. Кроме того, глобальный cache key семантически зависит только от query и tenant, не от выбранной model.

### Health check поверхностный

`/health` не обнаружит отвалившийся Temporal, Postgres, Redis, MinIO, ClickHouse или provider. Compose healthchecks частично закрывают инфраструктуру, но внешнему orchestrator нужен отдельный readiness endpoint.

### Нет полноценного background job UI

Документы показывают status/progress, HITL встроен в chat, Temporal имеет отдельную техническую UI. Единого пользовательского центра jobs/workflows нет; существующий `WorkflowsView.vue` не подключён к router.

### Отдельные операции не атомарны между системами

PostgreSQL, MinIO, Redis, Temporal и ClickHouse не участвуют в общей distributed transaction. Код выбирает практичные compensations и best-effort cleanup, поэтому возможны orphan objects, несохранённые chat messages или пропущенные usage events.

### Code exec не является hardened sandbox

Пустое окружение и timeout полезны, но subprocess всё ещё работает на host/container worker. Для hostile multi-user среды нужен отдельный execution service.

### Масштаб

README прямо позиционирует проект для private/local deployment и порядка 1–20 пользователей. Semantic cache делает линейный scan до 500 vectors в application process; pgvector index strategy и worker concurrency не выглядят настроенными под большой публичный traffic.

---

## 20. 📌 Краткая карта: куда идти за изменением поведения

| Нужно изменить | Главные файлы |
|---|---|
| Fast chat retrieval/streaming | `apps/api/routers/agent.py`, `packages/rag/retriever.py`, `packages/rag/citations.py`, `packages/llm/client.py` |
| Agent tools и structured loop | `packages/agents/base.py`, `packages/agents/prompts.py`, `packages/agents/tools/`, `apps/worker/activities/agent_step.py` |
| HITL | `apps/worker/workflows/agent_run.py`, `apps/api/routers/workflows.py`, `apps/ui/src/stores/chat.js` |
| Parallel research | `apps/worker/workflows/multi_step.py`, `apps/api/routers/agent.py` |
| Upload/reindex/delete | `apps/api/routers/documents.py` |
| URL/GitHub import | `apps/api/services/url_sources.py`, `apps/worker/activities/url_visuals.py` |
| Text ingestion | `apps/worker/activities/document_chunks.py`, `packages/rag/parser.py`, `packages/rag/chunker.py`, `packages/rag/embedder.py` |
| OCR/Vision ingestion | `apps/worker/workflows/ingestion.py`, `apps/worker/activities/visual_analysis.py`, `visual_storage.py`, `packages/rag/visual.py` |
| Notebook behavior | `apps/api/routers/notebooks.py`, `apps/api/services/notebooks.py`, `apps/ui/src/views/NotebookDetailView.vue` |
| Sessions/scopes | `apps/api/routers/sessions.py`, `packages/storage/models.py`, `apps/ui/src/stores/chat.js`, `apps/ui/src/utils/chatScope.js` |
| Tenant security/RLS | `packages/auth/api_keys.py`, `packages/storage/db.py`, migrations `0002`, `0005`, `0011` |
| Limits/configuration | `packages/core/settings.py`, `docker-compose.yml`, `.env.example` |
| Cost analytics | `packages/analytics/events.py`, `pricing.py`, `clickhouse.py`, `apps/api/routers/analytics.py` |
| UI routes/layout | `apps/ui/src/router/index.js`, `App.vue`, `AppSidebar.vue`, views/components |

Если читать проект впервые, рациональный порядок такой:

1. `apps/api/routers/agent.py` — увидеть два runtime paths;
2. `apps/ui/src/stores/chat.js` — понять, что реально делает пользователь;
3. `apps/worker/workflows/ingestion.py` — увидеть durable document pipeline;
4. `apps/worker/activities/ingestion.py` и `document_chunks.py` — увидеть I/O;
5. `packages/storage/models.py` — связать всё с данными;
6. `packages/rag/retriever.py` и `citations.py` — понять grounding;
7. `packages/agents/base.py` и tools — понять настоящий agent loop;
8. `docker-compose.yml` — увидеть все runtime services и их зависимости.

Итоговая ментальная модель проекта:

```text
Пользователь
  → Vue UI
  → tenant-authenticated FastAPI
     → быстрый RAG + SSE для обычного диалога
     → Temporal для долгих и durable операций
        → worker activities
           → OCR/Vision / embeddings / PydanticAI tools
  → PostgreSQL/pgvector как источник прикладной истины
  → MinIO для файлов
  → Redis для короткой памяти-кэша
  → ClickHouse для стоимости и latency
  → Langfuse/логи/Temporal UI для наблюдения
```

Это и есть проект без маркетингового упрощения: self-hosted knowledge-base assistant с двумя путями ответа, durable ingestion, tenant-scoped RAG, scoped collections и ограниченным, но реальным tool-calling agent mode.
