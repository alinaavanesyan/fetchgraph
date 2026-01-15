# llm/config/settings.py
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, cast

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MODEL_CONFIG = SettingsConfigDict(
    populate_by_name=True,
    extra="ignore",
)

_SETTINGS_OVERRIDES: dict[str, Any] = {}


class Settings(BaseSettings):
    model_config = _MODEL_CONFIG

    #  Настройки сервиса    
    log_level:          str          = Field("INFO", validation_alias="LOG_LEVEL")

    #  Настройки upstream LLM-провайдера
    llm_api_base:      AnyHttpUrl    = Field(cast(AnyHttpUrl, "https://api.llm7.io/v1"), validation_alias="LLM_API_BASE") # pyright: ignore[reportAssignmentType]
    llm_api_key:       str           = Field("unused",            validation_alias="LLM_API_KEY")
    llm_default_model_name: str      = Field("deepseek-v3-0324",  validation_alias="LLM_DEFAULT_MODEL_NAME")
    llm_model_override: str | None   = Field(None,                validation_alias="LLM_MODEL_NAME")
    llm_temperature:   float         = Field(0.0,                 validation_alias="LLM_TEMPERATURE")
    llm_top_p:         float         = Field(1.0,                 validation_alias="LLM_TOP_P")
    llm_max_tokens:    int           = Field(50000,               validation_alias="LLM_MAX_TOKENS")
    llm_verbose:       bool          = Field(True,                validation_alias="LLM_VERBOSE")
    llm_timeout:       float         = Field(300.0, validation_alias="LLM_TIMEOUT")

    #  Настройки очередей
    llm_max_concurrent:int           = Field(1,                   validation_alias="LLM_MAX_CONCURRENT")
    llm_priority_slots: dict[str, int] = Field(
        default_factory=lambda: {"p1": 2, "p2": 1, "p3": 1}, validation_alias="LLM_PRIORITY_SLOTS"
    )

    llm_priority_slots_p1: int       = Field(2,                   validation_alias="LLM_PRIORITY_SLOTS_P1")
    llm_priority_slots_p2: int       = Field(1,                   validation_alias="LLM_PRIORITY_SLOTS_P2")
    llm_priority_slots_p3: int       = Field(1,                   validation_alias="LLM_PRIORITY_SLOTS_P3")
    llm_priority_default: str        = Field("p2",               validation_alias="LLM_PRIORITY_DEFAULT")
    llm_queue_max_len:   int         = Field(100,                 validation_alias="LLM_QUEUE_MAX_LEN")

    #  Настройки кэша
    llm_cache_enabled: bool          = Field(True,                validation_alias="LLM_CACHE_ENABLED")
    llm_cache_path:    str           = Field("/tmp/llm_cache.db",  validation_alias="LLM_CACHE_PATH")
    # Backward compatible: older scripts set LLM_CACHE_FILE and rely on a mounted directory (/cache by default)
    llm_cache_file:    str           = Field("llm_cache.sqlite",   validation_alias="LLM_CACHE_FILE")
    cache_container_dir: str         = Field("/cache",            validation_alias="CACHE_CONTAINER_DIR")
    llm_cache_ttl:     int           = Field(600000,              validation_alias="LLM_CACHE_TTL")
    
     
    # Окружение сервиса
    environment:       str           = Field("development",      validation_alias="ENV")    
    testing:           bool          = Field(False,              validation_alias="TESTING")

    # Для Bearer-аутентификации
    # llm_auth_url: Optional[str] = Field(None, env="GIGACHAT_AUTH_URL")
    # llm_auth_client_id: Optional[str] = None
    # llm_auth_client_secret: Optional[str] = None
    # Или для Basic-аутентификации при получении токена
    # llm_auth_basic: Optional[str] = Field(None, env="GIGACHAT_API_KEY")  # base64 от "client_id:client_secret"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def is_testing(self) -> bool:
        return self.testing or self.environment.lower() == "testing"
    
    @property
    def debug(self) -> bool:
        return self.log_level.upper() == "DEBUG"

    @property
    def llm_priority_total_slots(self) -> int:
        return sum(max(v, 0) for v in self.llm_priority_limits_map.values())

    @field_validator("llm_model_override")
    @classmethod
    def _normalize_override(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @property
    def llm_priority_limits_map(self) -> dict[str, int]:
        # If the new map-based config was provided explicitly (via env or constructor),
        # honor it as the single source of truth. Otherwise, fall back to legacy fields.
        if "llm_priority_slots" in self.model_fields_set:
            return {k: int(v) for k, v in self.llm_priority_slots.items() if v is not None}

        legacy = {
            "p1": getattr(self, "llm_priority_slots_p1", None),
            "p2": getattr(self, "llm_priority_slots_p2", None),
            "p3": getattr(self, "llm_priority_slots_p3", None),
        }
        return {k: int(v) for k, v in legacy.items() if v is not None}
    
    @property
    def llm_cache_path_resolved(self) -> str:
        """Resolved sqlite path used by both /llm and /v1/chat caches.

        Priority:
          1) If LLM_CACHE_PATH was explicitly provided -> use it.
          2) Else -> join CACHE_CONTAINER_DIR + LLM_CACHE_FILE.
        """
        if "llm_cache_path" in self.model_fields_set:
            return self.llm_cache_path
        if Path(self.llm_cache_file).is_absolute():
            return str(self.llm_cache_file)
        return str(Path(self.cache_container_dir) / self.llm_cache_file)


@lru_cache(maxsize=1)
def _build_settings() -> Settings:
    return Settings(**_SETTINGS_OVERRIDES)

def get_settings() -> Settings:
    return _build_settings()

def configure_settings_overrides(overrides: Mapping[str, Any] | None = None) -> None:
    _SETTINGS_OVERRIDES.clear()
    if overrides:
        _SETTINGS_OVERRIDES.update(overrides)
    _build_settings.cache_clear()

def update_settings_overrides(overrides: Mapping[str, Any]) -> None:
    if overrides:
        _SETTINGS_OVERRIDES.update(overrides)
        _build_settings.cache_clear()

def reset_settings_overrides() -> None:
    _SETTINGS_OVERRIDES.clear()
    _build_settings.cache_clear()
