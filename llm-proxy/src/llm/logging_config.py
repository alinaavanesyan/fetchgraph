# llm/utils/logging_config.py
from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import time
from logging import Formatter, LogRecord, StreamHandler
from logging.handlers import RotatingFileHandler
from typing import Iterable

from llm.config.logging_settings import LoggingSettings  # сделай свой settings как обсуждали

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_HEALTHCHECK_PATHS: tuple[str, ...] = ("/health", "/healthz")

_DEFAULT_NOISY_LOGGERS: tuple[str, ...] = (
    "httpx",
    "openai",
    "httpcore",
)

_HANDLER_MARK = "_llm_logging_handler_kind"
_OUR_KINDS = ("console", "file")


class _HealthcheckFilter(logging.Filter):
    def __init__(self, paths: Iterable[str]):
        super().__init__(name="healthcheck-filter")
        self._needles = tuple(paths)

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        request_line = getattr(record, "request_line", "")
        if request_line and any(f"GET {p}" in request_line for p in self._needles):
            return False
        try:
            msg = record.getMessage()
        except Exception:
            msg = ""
        if msg and any(f"GET {p}" in msg for p in self._needles):
            return False
        return True


class _RequestIdFilter(logging.Filter):
    """Inject request_id from contextvars into every record."""
    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        rid = request_id_var.get()
        if rid:
            setattr(record, "request_id", rid)
        return True


class JsonFormatter(Formatter):
    def __init__(self, service_name: str):
        super().__init__()
        self._service = (service_name or "service").strip()

    def format(self, record: LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "service": self._service,
            "logger": record.name,
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        rid = getattr(record, "request_id", None)
        if rid:
            payload["request_id"] = rid

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def _coerce_level(level: str, default: int) -> int:
    lvl = (level or "").upper().strip()
    return getattr(logging, lvl, default)


def _mark_handler(handler: logging.Handler, kind: str) -> None:
    setattr(handler, _HANDLER_MARK, kind)


def _is_our_handler(handler: logging.Handler) -> bool:
    return getattr(handler, _HANDLER_MARK, None) in _OUR_KINDS


def _find_our_handler(root: logging.Logger, kind: str) -> logging.Handler | None:
    for h in root.handlers:
        if getattr(h, _HANDLER_MARK, None) == kind:
            return h
    return None


def _remove_our_handlers(root: logging.Logger) -> None:
    for h in list(root.handlers):
        if _is_our_handler(h):
            root.removeHandler(h)


def _ensure_filters() -> None:
    # healthcheck фильтр только для access логгера
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _HealthcheckFilter) for f in access_logger.filters):
        access_logger.addFilter(_HealthcheckFilter(_HEALTHCHECK_PATHS))

    # request_id фильтр — лучше вешать на root (чтобы распространялся на все)
    root = logging.getLogger()
    if not any(isinstance(f, _RequestIdFilter) for f in root.filters):
        root.addFilter(_RequestIdFilter())


def configure_logging(settings: LoggingSettings | None = None, *, force: bool = False) -> None:
    s = settings or LoggingSettings()

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # handler levels decide output

    for noisy in _DEFAULT_NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _ensure_filters()

    if force:
        _remove_our_handlers(root)

    console_level = _coerce_level(s.log_level, logging.INFO)
    file_level = _coerce_level(s.file_log_level, logging.ERROR)

    formatter: Formatter
    if (s.log_format or "").lower() == "json":
        formatter = JsonFormatter(s.service_name)
    else:
        formatter = logging.Formatter(
            f"%(asctime)s - {s.service_name} - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Console handler (stdout)
    console_handler = _find_our_handler(root, "console")
    if console_handler is None:
        console_handler = StreamHandler(stream=sys.stdout)
        _mark_handler(console_handler, "console")
        root.addHandler(console_handler)

    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)

    # File handler (optional)
    file_handler = _find_our_handler(root, "file")
    if not s.log_file_path:
        if file_handler is not None:
            root.removeHandler(file_handler)
        return

    if file_handler is None:
        try:
            os.makedirs(os.path.dirname(s.log_file_path) or ".", exist_ok=True)
            file_handler = RotatingFileHandler(
                s.log_file_path,
                maxBytes=int(s.log_max_bytes),
                backupCount=int(s.log_backup_count),
                encoding="utf-8",
            )
            _mark_handler(file_handler, "file")
            root.addHandler(file_handler)
        except Exception as e:
            root.error("Failed to configure file logging: %s", e)
            return

    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(name)
