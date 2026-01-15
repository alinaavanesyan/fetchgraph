# LLM Proxy — System Context (для разработчиков)

## Что это за сервис

**LLM Proxy** — небольшой FastAPI‑сервис, который выступает *прокси‑слоем* между клиентами и upstream LLM‑провайдерами.
Его цель — сделать вызовы LLM **предсказуемыми в проде**:

- ограничивать конкурентность (и тем самым защищать upstream/сеть/сервер),
- добавлять кэширование ответов,
- поддерживать приоритизацию запросов,
- держать совместимость с OpenAI‑подобным API (`/v1/chat/completions`),
- инкапсулировать различия провайдеров (OpenAI‑совместимые и GigaChat).

> Документ описывает **текущую** архитектуру по коду репозитория (модули `main.py`, `deps.py`, `services/*` и т.д.).

---

## Внешние интерфейсы

### HTTP API

- **Health/metrics**
  - `GET /health` (есть в смоук‑сценариях и деплое; реализация обычно в роутерах/приложении)
  - `GET /metrics` (Prometheus, через `llm.metrics.prometheus.router`)
- **Chat completions (OpenAI‑style)**
  - `POST /v1/chat/completions` (через `llm.routers.chat`)
- **LLM (внутренний/legacy)**
  - дополнительные эндпоинты через `llm.routers.llm` (контракт зависит от роутера)

### Конфигурация

Настройки загружаются через Pydantic Settings (`llm.config.settings.Settings` + `get_settings()`).
Есть механизм **overrides** для тестов/интеграции (см. `configure_settings_overrides/update/reset`).

---

## Основные сценарии

1) **Обычный запрос chat completion**
- Клиент отправляет `POST /v1/chat/completions`.
- Запрос проходит через зависимости (settings/cache/provider/queue).
- Применяется ограничение конкурентности и (опционально) кэш.
- Выполняется вызов провайдера (OpenAI‑совместимый или GigaChat).
- Возвращается ответ.

2) **Кэш‑хит**
- Для запроса вычисляется ключ (`make_key(...)`).
- Если запись валидна по TTL — ответ возвращается без вызова upstream.

3) **Dedup “inflight”**
- При одновременных одинаковых запросах (один и тот же ключ) — второй и последующие ждут `Future` первого,
  затем получают тот же результат (без повторного вызова upstream).

4) **Приоритизация**
- Запросы ставятся в очередь с приоритетом.
- Планировщик очереди выбирает следующий запрос с учётом лимитов по приоритетам.

---

## Внутренняя модель рантайма

### Процессы / воркеры

Сервис предполагает работу **в одном процессе / одном воркере** для корректности ограничений конкурентности и очереди.
В docker entrypoint присутствует “hard guard”, запрещающий `--workers > 1`.

### Параллельность

- Входящие HTTP‑запросы обрабатываются асинхронно (FastAPI/ASGI).
- Конкурентность upstream вызовов регулируется **PriorityChatQueue**:
  - отдельные лимиты по приоритетам,
  - учёт inflight,
  - метрики Prometheus (inflight/queue/latency/ошибки).

---

## Ключевые компоненты и границы ответственности


| ID | Component | Layer | Code | Responsibility | Public contracts |
|---|---|---|---|---|---|
| app | FastAPI app factory | Interface | `main.py` | Создание приложения, подключение роутеров, middleware логирования запросов | ASGI app |
| settings | Settings & overrides | Infrastructure | `settings.py` (`llm.config.settings`) | Загрузка env/settings, вычисление derived полей, overrides для тестов | `get_settings()`, `configure_settings_overrides()` |
| deps | Dependency graph (DI) | Application | `deps.py` (`llm.deps`) | Инициализация singleton‑зависимостей: cache/provider/queue/llm wrapper | `get_chat_queue()`, `reset_chat_dependencies()` |
| cache | SQLite cache + inflight | Infrastructure | `cache.py` (`llm.services.cache`) | TTL кэш, pickle storage, inflight dedup для одинаковых ключей | `SQLiteCache.get/set/get_or_set()` |
| key | Cache key builder | Infrastructure | `cache.py` | Стабильное построение ключей на основе namespace+payload | `make_key(...)` |
| queue | Priority chat queue | Application | `priority_queue.py` (`llm.services.priority_queue`) | Очередь с приоритетами + лимиты inflight + метрики | `PriorityChatQueue.submit(...)` |
| provider | Provider interface | Infrastructure | `chat_provider.py` | Протокол провайдера и фабрика выбора реализаций | `ChatProvider`, `make_chat_provider()` |
| provider_openai | OpenAI provider | Infrastructure | `chat_provider.py` | Отправка `/chat/completions` через `openai.AsyncOpenAI` + опции HTTP/mTLS/verify | `OpenAIChatProvider.chat_completions(...)` |
| provider_gigachat | GigaChat provider | Infrastructure | `chat_provider.py` | GigaChat‑специфичная реализация (обычно mTLS) | `GigaChatProvider.chat_completions(...)` |
| wrapper | Cached & queued LC wrapper | Application | `wrapper.py` (`llm.services.wrapper`) | Обёртка вокруг LangChain модели: асинхронные вызовы через очередь + кэш; блок синхронных методов | `CachedQueuedChatOpenAI.ainvoke/apredict/...` |
| client_factory | LLM client factory | Application | `client.py` (`llm.services.client`) | Создание LangChain ChatOpenAI + обёртка `CachedQueuedChatOpenAI` | `create_custom_llm(...)` |
| chat_models | Chat request/response models | Domain | `chat.py` + *implied* `llm.models.chat` | Pydantic модели сообщений и запроса chat completion | `ChatCompletionRequest.to_openai_payload(...)` |
| llm_models | Legacy LLM request model | Domain | `llm.py` | Pydantic модель “method+args+kwargs+sender” | `LLMRequest` |
| routers_chat | Chat router | Interface | *implied* `llm.routers.chat` | HTTP endpoint `/v1/chat/completions` | `POST /v1/chat/completions` |
| routers_llm | Legacy LLM router | Interface | *implied* `llm.routers.llm` | Доп. endpoints (legacy) | depends |
| metrics | Prometheus metrics router | Interface | *implied* `llm.metrics.prometheus` | Экспорт `/metrics` | `GET /metrics` |

### 1) Settings / Config

- Источник правды — `Settings` (Pydantic Settings).
- Конфиг влияет на:
  - upstream base url / key / модель по умолчанию,
  - параметры генерации (temperature/top_p),
  - кэш (enabled/ttl/path),
  - лимиты очереди (по приоритетам).

**Инварианты**
- Кэш‑путь вычисляется через `llm_cache_path_resolved` (explicit path > join dir+file).
- Overrides используются для тестов и должны сбрасываться.

### 2) Provider abstraction

`ChatProvider` — протокол (интерфейс) “как отправить запрос в upstream и получить ответ”.

`make_chat_provider()` выбирает реализацию:
- `OpenAIChatProvider` — OpenAI‑совместимые endpoints (через `openai.AsyncOpenAI`)
- `GigaChatProvider` — GigaChat (в реальном коде обычно требует mTLS; параметры берутся из settings)

**Инварианты**
- Провайдер должен принимать `ChatCompletionRequest` и возвращать совместимый ответ/структуру.
- Ошибки upstream оборачиваются/логируются так, чтобы не ломать прокси целиком.

### 3) Cache

`SQLiteCache`:
- хранит значения (pickle) в sqlite,
- поддерживает TTL,
- поддерживает inflight‑dedup для одинаковых ключей,
- ведёт счётчики hits/misses (и должен логировать ошибки десериализации).

### 4) Priority queue (ограничение конкурентности + приоритеты)

`PriorityChatQueue`:
- принимает задачу (callable) с приоритетом и endpoint,
- решает: выполнить сразу или поставить в очередь,
- поддерживает max_queue (0 = “no queue”: если лимит занят — вернуть ошибку/отказ),
- даёт наблюдаемость через Prometheus (latency, inflight, queue size, outcomes).

### 5) Wrapper вокруг LangChain LLM

`CachedQueuedChatOpenAI` — “обёртка”, которая:
- блокирует синхронные методы (чтобы не обходить контроль конкурентности/кэш),
- предоставляет асинхронные методы, которые:
  - вычисляют ключ кэша,
  - используют очередь для вызова upstream,
  - возвращают LangChain‑совместимые сообщения/результаты.

---

## Потоки данных

### Flow: POST /v1/chat/completions (упрощённо)

1. FastAPI получает запрос.
2. Роутер валидирует вход (Pydantic модель запроса).
3. Из DI берутся `Settings`, `SQLiteCache`, `ChatProvider`, `PriorityChatQueue`.
4. Строится payload (модель по умолчанию, temperature/top_p).
5. (Опционально) проверка кэша по ключу.
6. Если miss: enqueue в `PriorityChatQueue` callable, который вызывает `ChatProvider`.
7. Результат кладётся в кэш.
8. Возврат ответа клиенту.

---

## Наблюдаемость

- Prometheus метрики внутри очереди (inflight/latency/outcomes).
- Логи:
  - middleware логирует входящие запросы (в debug),
  - компоненты кэша/провайдера/очереди должны логировать ошибки и ключевые события.

---

## Типовые failure modes и как дебажить

- **HTTP code 000** на нагрузочных тестах: часто означает сетевой/транспортный сбой на стороне клиента (`curl`/бенчмарк),
  таймаут или разрыв соединения, а не HTTP‑ответ сервиса.
- **Рост inflight без спадов**: зависшие задачи upstream или отсутствие release в finally.
- **Постоянные cache misses**: ключ нестабилен (включены поля, которые меняются) или TTL слишком мал.
- **Отключение кэша**: settings (enabled=false) или невалидный путь к sqlite.

---

## Где читать дальше

- Тесты: `test_cache_*`, `test_chat_provider.py`, `test_chat_priority_queue.py`, `test_wrapper_cache.py`.
