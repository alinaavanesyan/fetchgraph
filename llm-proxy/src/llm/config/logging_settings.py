from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class LoggingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    service_name: str = "llm-proxy"

    # console
    log_level: str = "INFO"
    log_format: str = "json"  # "json" | "text"

    # file (optional)
    log_file_path: str | None = None
    file_log_level: str = "ERROR"
    log_max_bytes: int = 50_000_000
    log_backup_count: int = 5
