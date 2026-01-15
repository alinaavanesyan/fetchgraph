# Proxy contract (`/v1/chat/completions`)

## Model resolution

- Proxy **MAY override** `request.model` based on server configuration. If override is enabled, sender’s model is ignored.
- Override включается **только если** `LLM_MODEL_NAME` был явно задан в конфигурации прокси (env/профиль/overrides).
- Термины:
  - `default_model_name` — базовая модель прокси (значение по умолчанию), используется **только если** `request.model` отсутствует или null.
  - `model_override` — принудительная модель, применяется всегда (игнорируя `request.model`, включая `"default"`), когда override включён.
- Поведение:
  - При включённом override прокси отправляет upstream-у именно `model_override`. Прокси может (опционально) сообщать, какая модель использована, через заголовок или отдельный `/settings`-endpoint.
  - При выключенном override прокси передаёт `request.model` как есть (включая `"default"`); если поле не передано, подставляется `default_model_name` (обычно `Settings.llm_default_model_name` по умолчанию).
