# llm/services/chat_provider.py
from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI, OpenAIError

from llm.config.settings import Settings
from llm.logging_config import get_logger
from llm.models.chat import ChatCompletionRequest
from llm.services.cache import SQLiteCache, make_key

logger = get_logger(__name__)


class OpenAIChatProvider:
    def __init__(self, settings: Settings, *, cache: SQLiteCache | None = None):
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=str(settings.llm_api_base),
            timeout=settings.llm_timeout,
        )
        self._base_url = str(settings.llm_api_base)
        self._default_model = settings.llm_default_model_name
        self._model_override = settings.llm_model_override
        self._default_temperature = settings.llm_temperature
        self._default_top_p = settings.llm_top_p
        # Prefer injected shared cache (from deps.build_cache).
        if cache is not None:
            self._cache = cache
        else:
            cache_path = getattr(settings, "llm_cache_path_resolved", None) or settings.llm_cache_path
            self._cache = SQLiteCache(
                path=str(cache_path),
                ttl_seconds=int(getattr(settings, "llm_cache_ttl", 0) or 0),
                enabled=bool(getattr(settings, "llm_cache_enabled", False)),
            )

    def _cache_key(self, payload: dict[str, Any]) -> str:
        digest = make_key(
            namespace="openai.chat.completions.create",
            data={"base_url": self._base_url, "payload": payload},
        )
        # Prefix is only for readability/debugging.
        return f"chat:{digest}"

    async def complete(self, request: ChatCompletionRequest) -> dict[str, Any]:
        payload = request.to_provider_payload(
            default_model=self._default_model,
            default_temperature=self._default_temperature,
            default_top_p=self._default_top_p,
        )
        if self._model_override:
            payload["model"] = self._model_override

        key = self._cache_key(payload)

        async def _call_provider() -> dict[str, Any]:
            try:
                response = await self._client.chat.completions.create(**payload)
            except OpenAIError:
                logger.exception("Provider error while executing chat completion")
                raise

            if hasattr(response, "model_dump"):
                return response.model_dump()  # type: ignore[no-any-return]
            if hasattr(response, "dict"):
                return response.dict()  # type: ignore[no-any-return]
            return response  # type: ignore[no-any-return]

        def _on_hit(k: str) -> None:
            logger.info("[CACHE HIT] /v1/chat key=%s model=%s", k, payload.get("model"))

        def _on_miss(k: str) -> None:
            logger.info("[CACHE MISS] /v1/chat key=%s model=%s", k, payload.get("model"))

        # SQLiteCache handles disabled mode internally.
        return await self._cache.aget_or_set(key, _call_provider, on_hit=_on_hit, on_miss=_on_miss)

    @property
    def model_override(self) -> str | None:
        return self._model_override
