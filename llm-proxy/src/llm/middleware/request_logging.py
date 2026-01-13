# llm/middleware/request_logging.py
from __future__ import annotations

import re
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from llm.logging_config import get_logger, request_id_var

logger = get_logger(__name__)

_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key"}
_SENSITIVE_BODY_KEYS = re.compile(r'("?(api[_-]?key|token|authorization|password)"?\s*:\s*)"[^"]+"', re.I)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)

        response.headers["x-request-id"] = rid
        return response


class DebugRequestLoggingMiddleware(BaseHTTPMiddleware):
    """Логирует входящие запросы ТОЛЬКО для debug, безопасно и с ограничениями."""
    def __init__(self, app, max_body_bytes: int = 4096):
        super().__init__(app)
        self._max = max_body_bytes

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()

        # headers (redacted)
        headers = {}
        for k, v in request.headers.items():
            if k.lower() in _SENSITIVE_HEADERS:
                headers[k] = "<redacted>"
            else:
                headers[k] = v

        body_preview = None
        try:
            raw = await request.body()
            raw = raw[: self._max]
            try:
                body_preview = raw.decode("utf-8", errors="replace")
                # redact simple JSON secrets
                body_preview = _SENSITIVE_BODY_KEYS.sub(r'\1"<redacted>"', body_preview)
            except Exception:
                body_preview = "<non-textual payload>"
        except Exception:
            body_preview = "<unavailable>"

        response = await call_next(request)

        dur_ms = int((time.perf_counter() - start) * 1000)
        logger.debug(
            "HTTP %s %s -> %s (%dms) headers=%s body=%s",
            request.method,
            str(request.url),
            response.status_code,
            dur_ms,
            headers,
            body_preview,
        )
        return response
