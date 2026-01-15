from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from llm.deps import get_chat_queue
from llm.logging_config import get_logger
from llm.models.chat import ChatCompletionRequest
from llm.services.priority_queue import PriorityChatQueue, ProviderError, QueueOverflowError, QueueResult

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/chat")


class InvalidRequestError(Exception):
    pass


def _generate_request_id() -> str:
    return f"r_{uuid4().hex}"


def _error_response(status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
    content = {
        "error": {
            "code": code,
            "http_status": status_code,
            "message": message,
            "request_id": request_id,
        }
    }
    return JSONResponse(status_code=status_code, content=content)


def _parse_priority(raw_priority: str | None, queue: PriorityChatQueue) -> str:
    if raw_priority is None:
        return queue.default_priority
    lowered = raw_priority.lower()
    if lowered in {"highest", "p0"}:
        return queue.priorities[0]
    if lowered == "lowest":
        return queue.priorities[-1]
    if lowered not in queue.priorities:
        raise InvalidRequestError(f"Invalid priority header: {raw_priority!r}")
    return lowered


def _parse_body(raw_body: dict[str, Any], request_id: str) -> ChatCompletionRequest:
    try:
        request_model = ChatCompletionRequest.model_validate(raw_body)
    except ValidationError as exc:  # noqa: B904
        message = _humanize_validation_error(exc)
        raise InvalidRequestError(message) from exc

    if request_model.model is not None and not request_model.model.strip():
        raise InvalidRequestError("Missing required field: model")

    if request_model.stream:
        raise InvalidRequestError("Streaming is not supported for this endpoint")
    return request_model


def _humanize_validation_error(exc: ValidationError) -> str:
    for error in exc.errors():
        if error.get("type") == "missing":
            field = ".".join(str(part) for part in error.get("loc", []) if part != "__root__")
            if field:
                return f"Missing required field: {field}"
        if error.get("type") == "string_too_short" and error.get("loc"):
            return f"Missing required field: {error['loc'][-1]}"
    first_error = exc.errors()[0] if exc.errors() else {}
    return first_error.get("msg", "Invalid request body")


def _metrics_headers(result: QueueResult, request_id: str) -> dict[str, str]:
    return {
        "x-llm-proxy-request-id": request_id,
        "x-llm-proxy-queue-wait-ms": str(result.metrics.queue_wait_ms),
        "x-llm-proxy-provider-latency-ms": str(result.metrics.provider_latency_ms),
        "x-llm-proxy-priority": result.metrics.priority,
    }


def _metrics_body(result: QueueResult) -> dict[str, Any]:
    return {
        "queue_wait_ms": result.metrics.queue_wait_ms,
        "provider_latency_ms": result.metrics.provider_latency_ms,
        "priority": result.metrics.priority,
    }


async def _handle_request(
    path: str,
    request: Request,
    priority_header: str | None,
    queue: PriorityChatQueue,
    include_metrics_in_body: bool = False,
) -> JSONResponse:
    request_id = _generate_request_id()
    try:
        try:
            raw_body = await request.json()
        except json.JSONDecodeError as exc:  # noqa: B904
            raise InvalidRequestError("Invalid JSON payload") from exc

        body_priority = raw_body.get("priority") if isinstance(raw_body, dict) else None
        priority = _parse_priority(priority_header or body_priority, queue)
        request_model = _parse_body(raw_body, request_id)
        queue_state = await queue.snapshot()
        logger.debug(
            "Queue snapshot for incoming request",
            extra={
                "request_id": request_id,
                "priority": priority,
                "queue_len": queue_state.get("queue_len", {}),
                "in_flight": queue_state.get("in_flight", {}),
                "path": path,
            },
        )
        result = await queue.enqueue(request_id, priority, request_model, endpoint=path)
    except InvalidRequestError as exc:
        return _error_response(400, "invalid_request", str(exc), request_id)
    except QueueOverflowError as exc:
        return _error_response(429, "queue_overflow", str(exc), request_id)
    except ProviderError as exc:
        logger.exception("Provider error for request %s at %s", request_id, path)
        return _error_response(500, "provider_error", str(exc), request_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Internal error for request %s at %s", request_id, path)
        return _error_response(500, "internal", str(exc), request_id)

    headers = _metrics_headers(result, request_id)
    payload: dict[str, Any] = {**result.response_body, "request_id": request_id}
    if include_metrics_in_body:
        payload = {**payload, "metrics": _metrics_body(result)}

    return JSONResponse(content=payload, headers=headers)


@router.post("/completions")
async def chat_completions(
    request: Request,
    priority: str | None = Header(default=None, alias="X-Priority"),
    queue: PriorityChatQueue = Depends(get_chat_queue),
) -> JSONResponse:
    return await _handle_request("/v1/chat/completions", request, priority, queue)


@router.post("/invoke")
async def chat_invoke(
    request: Request,
    priority: str | None = Header(default=None, alias="X-Priority"),
    queue: PriorityChatQueue = Depends(get_chat_queue),
) -> JSONResponse:
    return await _handle_request(
        "/v1/chat/invoke", request, priority, queue, include_metrics_in_body=True
    )
