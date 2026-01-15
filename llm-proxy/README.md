# llm-proxy (Docker-first)

`llm-proxy` — LLM proxy-сервис с очередью, приоритетами и кэшированием, рассчитанный **исключительно на запуск в Docker**.
Управление окружениями и профилями осуществляется через CLI `llm-proxy`, который работает поверх `docker compose`.

Проект предназначен для:
- проксирования OpenAI-compatible LLM API,
- ограничения и балансировки нагрузки,
- изоляции конфигураций через профили,
- использования как shared LLM backend.

---

## TL;DR

```bash
./cli/llm-proxy init default
./cli/llm-proxy up
./cli/llm-proxy logs
```

По умолчанию сервис будет доступен на:
```
http://localhost:8002
```

---

## Требования

- Docker
- Docker Compose v2 (`docker compose ...`)
- bash (Linux / macOS)

Проверка:
```bash
docker --version
docker compose version
```

---

## Архитектурные принципы (важно)

- ❗ **Только single-worker**
- ❌ Gunicorn не поддерживается
- ❌ Multiprocess Prometheus не поддерживается
- ❌ WEB_CONCURRENCY / UVICORN_WORKERS > 1 запрещены

Эти ограничения проверяются на старте контейнера.
Если они нарушены — контейнер завершится с ошибкой.

---

## Быстрый старт

### 1. Инициализация профиля

```bash
./cli/llm-proxy init default
```

Будет создан профиль `default`, включающий:

- `<profile>.env` — переменные **docker compose**
- `<profile>.llm.env` — **runtime-конфигурация приложения**
- bind-mount директории (кэш, логи, дампы)

Файлы профиля открываются в редакторе автоматически.

---

### 2. Запуск

```bash
./cli/llm-proxy up
```

### 3. Логи

```bash
./cli/llm-proxy logs
```

### 4. Остановка

```bash
./cli/llm-proxy down
```

---

## CLI

### Основные команды

```bash
llm-proxy init <name>      # создать профиль
llm-proxy list             # список профилей
llm-proxy use <name>       # сделать профиль активным
llm-proxy active           # показать активный профиль
llm-proxy up [name]        # запустить
llm-proxy down             # остановить
llm-proxy logs             # логи
llm-proxy status           # статус контейнеров
llm-proxy delete <name>    # удалить профиль и данные
```

### Редактирование конфигурации

```bash
llm-proxy edit             # runtime env
llm-proxy edit-compose     # compose env
```

---

## Где хранятся профили

Используются XDG-пути (или legacy `~/.llm-proxy`, если уже существует):

### Конфигурация
```
~/.config/llm-proxy/profiles/
  ├── default.env
  ├── default.llm.env
  └── staging.env
```

### Данные профилей (bind mounts)
```
~/.cache/llm-proxy/profiles/<profile>/
~/.local/share/llm-proxy/logs/<profile>/
~/.local/share/llm-proxy/profiles/<profile>/crash_dumps/
```

При `llm-proxy delete <profile>` все эти директории удаляются.

---

## Makefile (если работаете из репозитория)

### CLI

```bash
make cli-install
make cli-reinstall
make cli-uninstall
```

### Управление сервисом

```bash
make up PROFILE=default
make down PROFILE=default
make logs PROFILE=default
make status PROFILE=default
```

### Разработка

```bash
make lint
make test
make help
```

---

## Runtime конфигурация (`<profile>.llm.env`)

### Upstream LLM

```env
LLM_PROVIDER=openai
LLM_API_BASE=https://api.llm7.io/v1
LLM_API_KEY=...
LLM_DEFAULT_MODEL_NAME=deepseek-v3-0324
# optional hard override (forces this model for all requests)
# LLM_MODEL_NAME=gemini-2.0-flash
LLM_TEMPERATURE=0.7
LLM_TIMEOUT=300
```

Поддерживается любой OpenAI-compatible API.

---

## Очередь и приоритеты

Поддерживаются приоритеты:
- `p1` — высокий
- `p2` — default
- `p3` — background

### Базовые настройки

```env
LLM_MAX_CONCURRENT=3
LLM_PRIORITY_DEFAULT=p2
LLM_QUEUE_MAX_LEN=100
```

### Лимиты слотов (рекомендуется)

```env
LLM_PRIORITY_SLOTS={"p1":2,"p2":1,"p3":1}
```

### Legacy-совместимость

```env
LLM_PRIORITY_SLOTS_P1=2
LLM_PRIORITY_SLOTS_P2=1
LLM_PRIORITY_SLOTS_P3=1
```

Если `LLM_PRIORITY_SLOTS` задан — legacy-поля игнорируются.

---

## Кэширование

Используется **единый SQLite-кэш** для всех chat endpoint'ов.

### Настройки

```env
LLM_CACHE_ENABLED=true
LLM_CACHE_TTL=600000
```

### Пути

```env
LLM_CACHE_PATH=/tmp/llm_cache.db
```

или legacy:

```env
CACHE_CONTAINER_DIR=/cache
LLM_CACHE_FILE=llm_cache.sqlite
```

Правило выбора:
1. Если задан `LLM_CACHE_PATH`
2. Иначе → `CACHE_CONTAINER_DIR/LLM_CACHE_FILE`

---

## HTTP API

### Основные endpoints

- `POST /llm`
- `POST /v1/chat/completions`

Формат совместим с OpenAI Chat Completions API.

---

## Запуск не из репозитория

Если CLI установлен в `$PATH`, но вы не в директории репозитория:

```bash
export LLM_PROXY_PROJECT_DIR=/path/to/llm-proxy
llm-proxy up
```

Рекомендуется добавить переменную в shell-профиль.

---

## Установка CLI

```bash
./cli/llm-proxy install
```

Проверка:

```bash
llm-proxy help
```

Удаление:

```bash
llm-proxy uninstall
```

---

## Troubleshooting

### compose.yaml not found

Вы либо:
- не в корне репозитория
- либо не указали `LLM_PROXY_PROJECT_DIR`

### Порт занят

Измените `LLM_PORT` в `<profile>.env`.

### Контейнер сразу падает

Проверьте:
- нет ли `WEB_CONCURRENCY`
- нет ли `UVICORN_WORKERS`
- нет ли `PROMETHEUS_MULTIPROC_DIR`

---

## Лицензия

MIT
