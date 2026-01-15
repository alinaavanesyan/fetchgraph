# app/routers/llm.py
import inspect
import re
from typing import Any, List
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage as SchemaAI
from langchain_core.messages import BaseMessage as SchemaBase
from langchain_core.messages import HumanMessage as SchemaHuman
from langchain_core.messages import SystemMessage as SchemaSystem
from langchain_core.outputs import LLMResult
from openai import OpenAIError
from pydantic import ValidationError

from llm.deps import (
    CachedQueuedChatOpenAI,
    get_chat_queue,
    get_llm,
    get_settings,
)
from llm.logging_config import get_logger
from llm.models.chat import ChatCompletionRequest, ChatMessage
from llm.models.llm import LLMRequest
from llm.routers.chat import _humanize_validation_error
from llm.services.priority_queue import PriorityChatQueue, ProviderError, QueueOverflowError, QueueResult

logger = get_logger(__name__)

router = APIRouter()

@router.get("/health")
def health(settings=Depends(get_settings)):
    return {"status": "ok", "env": settings.environment}

def _validate_message_content(raw: Any) -> str | list[str | dict[str, Any]]:
    if raw is None:
        raise HTTPException(400, "Message content cannot be null")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        validated: list[str | dict[str, Any]] = []
        for idx, item in enumerate(raw):
            if isinstance(item, str):
                validated.append(item)
            elif isinstance(item, dict):
                validated.append(item)
            else:
                raise HTTPException(400, f"Invalid list item at index {idx}: {item!r}")
        return validated
    raise HTTPException(400, f"Unsupported message content type: {type(raw).__name__}")

def extract_messages(nested_list):
    flat_list = []
    if isinstance(nested_list, list):
        for item in nested_list:
            if "messages" in item:
                flat_list.extend(extract_messages(item["messages"]))
        if flat_list:
            return flat_list
    return nested_list


def split_system_message(text: str) -> list[str]:
    """
    Разбивает большой системный текст на части по маркеру "# PROMPT:".
    Если маркер не найден — возвращает список из одного элемента.
    """
    # (?m) — enable multiline, (?=^# PROMPT:) — разделяем, сохранив маркер во второй части
    parts = re.split(r'(?m)(?=^# PROMPT:)', text)
    return [p.strip() for p in parts if p.strip()]

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


def _metrics_headers(result: QueueResult, request_id: str) -> dict[str, str]:
    return {
        "x-llm-proxy-request-id": request_id,
        "x-llm-proxy-queue-wait-ms": str(result.metrics.queue_wait_ms),
        "x-llm-proxy-provider-latency-ms": str(result.metrics.provider_latency_ms),
        "x-llm-proxy-priority": result.metrics.priority,
    }


def _parse_priority(raw_priority: str | None, queue: PriorityChatQueue) -> str:
    if raw_priority is None:
        return queue.default_priority
    lowered = raw_priority.lower()
    if lowered not in queue.priorities:
        raise HTTPException(400, f"Invalid priority header: {raw_priority!r}")
    return lowered


def _schema_to_chat_message(message: SchemaBase) -> ChatMessage:
    if isinstance(message, SchemaSystem):
        role = "system"
    elif isinstance(message, SchemaHuman):
        role = "user"
    elif isinstance(message, SchemaAI):
        role = "assistant"
    else:
        raise HTTPException(400, f"Unsupported message type: {type(message).__name__}")
    return ChatMessage(role=role, content=_validate_message_content(message.content))


def _build_chat_request(
    messages: list[SchemaBase],
    model: str | None,
    temperature: float | None,
    top_p: float | None,
    max_tokens: int | None,
    stop: Any,
) -> ChatCompletionRequest:
    chat_messages = [_schema_to_chat_message(m) for m in messages]
    return ChatCompletionRequest(
        model=model,
        messages=chat_messages,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        stop=stop,
    )


@router.post("/llm", response_class=JSONResponse)
async def call_llm(
    req: LLMRequest,
    request: Request,
    priority: str | None = Header(default=None, alias="X-Priority"),
    llm: CachedQueuedChatOpenAI = Depends(get_llm),
    queue: PriorityChatQueue = Depends(get_chat_queue),
) -> JSONResponse:
    logger.info(f"LLM request: sender={req.sender!r} method={req.method!r} args={req.args} kwargs={list(req.kwargs)}")

    # 1) Фильтруем «безопасные» ключи
    safe = {
        k: v
        for k, v in req.kwargs.items()
        if k in ("input", "prompt", "messages", "stop", "callbacks", "tags", "metadata", "run_manager")
    }
    # 2) Если есть сырой список dict в messages — превращаем его в правильные объекты
    if "messages" in safe:
        messages = extract_messages(safe["messages"])
        norm_msgs: List[SchemaBase] = []
        for m in messages:
            if isinstance(m, dict):
                t = m.get("type", "system")
                c = _validate_message_content(m.get("content"))
                if t == "system":
                    norm_msgs.append(SchemaSystem(content=c))
                elif t in ("user", "human"):
                    norm_msgs.append(SchemaHuman(content=c))
                elif t in ("assistant", "ai"):
                    norm_msgs.append(SchemaAI(content=c))
                else:
                    raise HTTPException(400, f"Unknown message type: {t}")
            elif isinstance(m, SchemaBase):
                norm_msgs.append(m)
            else:
                raise HTTPException(400, f"Invalid message element: {m!r}")
        safe["messages"] = norm_msgs

    # 3) Remap invoke → generate если передали messages
    method_name = req.method
    if method_name == "invoke" and "messages" in safe:
        method_name = "generate"
        #req.args.append('method_name="invoke"')
        logger.info(" ↳ remapping invoke → generate because messages were provided")

    method_name = "a"+method_name

    if not hasattr(llm, method_name):
        raise HTTPException(400, f"Unknown LLM method: {method_name}")

    if "messages" in safe:
        request_id = _generate_request_id()
        try:
            priority_value = _parse_priority(priority, queue)
            chat_request = _build_chat_request(
                messages=safe["messages"],
                model=req.kwargs.get("model"),
                temperature=req.kwargs.get("temperature"),
                top_p=req.kwargs.get("top_p"),
                max_tokens=req.kwargs.get("max_tokens"),
                stop=req.kwargs.get("stop"),
            )
            if req.kwargs.get("stream"):
                raise HTTPException(400, "Streaming is not supported for this endpoint")
            queue_result = await queue.enqueue(request_id, priority_value, chat_request, endpoint="/llm")
        except HTTPException as exc:
            detail = exc.detail if getattr(exc, "detail", None) else str(exc)
            return _error_response(exc.status_code, "invalid_request", str(detail), request_id)
        except ValidationError as exc:
            message = _humanize_validation_error(exc)
            return _error_response(400, "invalid_request", message, request_id)
        except QueueOverflowError as exc:
            return _error_response(429, "queue_overflow", str(exc), request_id)
        except ProviderError as exc:
            logger.exception("Provider error for request %s at /llm", request_id)
            return _error_response(500, "provider_error", str(exc), request_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Internal error for request %s at /llm", request_id)
            return _error_response(500, "internal", str(exc), request_id)

        return JSONResponse(content=queue_result.response_body, headers=_metrics_headers(queue_result, request_id))

    fn = getattr(llm, method_name)

    # 4) Оставляем только параметры, которые ждёт fn
    sig = inspect.signature(fn)
    call_kwargs = {k: v for k, v in safe.items() if k in sig.parameters}

    try:
        # THIS RETURNS A ChatResult object
        result: LLMResult = await fn(*req.args, **call_kwargs)
        # FastAPI will .dict() it for you under the hood
        d = result.model_dump()
        payload = jsonable_encoder(d)
        return JSONResponse(content=payload)
    except OpenAIError as e:
        # ❶ печатаем КОРОТКОЕ описание + traceback
        logger.exception("OpenAI upstream failure (%s): %s", e.__class__.__name__, e)
        # ❷ клиенту отвечаем нейтральным 502 без HTML
        raise HTTPException(
            status_code=502,
            detail=f"Upstream LLM error: {e.__class__.__name__} {getattr(e, 'status_code', '')}"
        ) from e
    except Exception as e:
        logger.exception("LLM request failed")
        raise HTTPException(status_code=502, detail=str(e))
