Request Policy & Normalization

Problem Statement
Клиенты LLM используют разные SDK, модели и параметры, что приводит к:

превышению лимитов провайдеров,

нестабильному поведению,

ошибкам апстрима,

невозможности централизованно управлять политиками.

Цель
Обеспечить, что каждый запрос, попадающий в систему исполнения:

валиден,

соответствует политикам платформы,

предсказуем для downstream-компонентов.

Что ВХОДИТ в эту фичу

✅ Overrides:

model (hard override или default)

max_tokens (clamp / strict)

temperature, top_p

provider-specific параметры

✅ Substitutions:

модель по профилю

параметры по environment / tenant / proxy instance

per-model defaults

✅ Validation:

допустимые диапазоны

строгий / мягкий режим (LLM_MAX_TOKENS_STRICT)

fallback значения

✅ Deterministic output:

одинаковый вход → одинаковый “нормализованный” запрос

Что НЕ ВХОДИТ

❌ Очереди
❌ Приоритеты
❌ Concurrency
❌ Admin API
❌ Метрики исполнения

(максимум — debug-лог “request normalized”)

Где она стоит в пайплайне

Это очень важно концептуально:

HTTP request
   ↓
[ Feature: Request Policy & Normalization ]
   ↓
Canonical LLMRequest
   ↓
[ Feature: Priority-based Scheduling ]
   ↓
[ Feature: Concurrency Control ]
   ↓
Provider Adapter


👉 Overrides всегда ДО очереди.

## Правила и инварианты

- Все запросы проходят проверку на лимит `max_tokens` до отправки к провайдеру в режиме strict.
- В случае превышения `LLM_MAX_TOKENS_STRICT` — значение `max_tokens` урезается до лимита, при этом генерируется warning.