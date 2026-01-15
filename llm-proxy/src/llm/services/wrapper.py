# llm/services/wrapper.py
import asyncio
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Union, cast

from langchain_core.callbacks.stdout import StdOutCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatResult, LLMResult
from langchain_core.prompt_values import PromptValue
from langchain_openai import ChatOpenAI
from pydantic import ConfigDict, Field

from llm.logging_config import get_logger
from llm.services.cache import SQLiteCache, make_key

logger = get_logger(__name__)

# ───────────────────────────────────────────────────────────
# Silence verbose on_chat_model_start spam in logs
# ───────────────────────────────────────────────────────────
def _no_op_on_chat_model_start(self, serialized: dict, messages: list[Any], **kwargs):
    logger.info(f"[LLM START] model={serialized.get('model_name')}  messages={len(messages)}")
    return None
StdOutCallbackHandler.on_chat_model_start = _no_op_on_chat_model_start


class CachedQueuedChatOpenAI(ChatOpenAI):
    """
    ChatOpenAI with:
      - SQLite cache (optional)
      - Async concurrency limiter (asyncio.Semaphore)
      - In-flight deduplication for identical requests
      - No thread executors; all calls use native async methods
    """
    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    # NOTE: ChatOpenAI is a pydantic model with dynamic fields.
    # These annotations exist primarily for static type checkers (pyright).
    cache_enabled: bool = Field(default=True, exclude=True)
    cache_path: str = Field(default=":memory:", exclude=True)
    cache_ttl: int = Field(default=0, exclude=True)
    # Do NOT use the name "cache": it exists on BaseLanguageModel with a different type
    # (BaseCache | bool | None) and pyright flags overrides as incompatible.
    bp_cache: SQLiteCache | None = Field(default=None, exclude=True)

    def __init__(self, **kwargs):
        # Custom params
        cache_enabled  = kwargs.pop("cache_enabled", True)
        cache_path     = kwargs.pop("cache_path", ":memory:")
        cache_ttl      = kwargs.pop("cache_ttl", 0)
        max_concurrent = kwargs.pop("max_concurrent", 4)
        # Prefer explicit bp_cache injection. Also support passing SQLiteCache via
        # kwarg "cache" (but only if it's our SQLiteCache; otherwise leave for LangChain).
        bp_cache: SQLiteCache | None = kwargs.pop("bp_cache", None)
        if bp_cache is None and isinstance(kwargs.get("cache"), SQLiteCache):
            bp_cache = cast(SQLiteCache, kwargs.pop("cache"))
        # Init parent (ChatOpenAI)
        super().__init__(**kwargs)

        # Store custom params
        object.__setattr__(self, "cache_enabled",  cache_enabled)
        object.__setattr__(self, "cache_path",     cache_path)
        object.__setattr__(self, "cache_ttl",      cache_ttl)
        object.__setattr__(self, "bp_cache",       bp_cache)

        # Async queue & inflight map
        self._sem = asyncio.Semaphore(max_concurrent)
        self._inflight: Dict[str, asyncio.Future] = {}

        # Shared cache backend (preferred). If not provided, create a private one.
        if self.cache_enabled:
            self._cache = bp_cache or SQLiteCache(
                path=self.cache_path,
                ttl_seconds=self.cache_ttl,
                enabled=True,
            )
        else:
            self._cache = bp_cache or SQLiteCache(
                path=self.cache_path,
                ttl_seconds=self.cache_ttl,
                enabled=False,
            )

    # -------------- utilities --------------

    @contextmanager
    def no_cache(self):
        prev = self.cache_enabled
        object.__setattr__(self, "cache_enabled", False)
        try:
            yield
        finally:
            object.__setattr__(self, "cache_enabled", prev)

    def _llm_fingerprint(self) -> Dict[str, Any]:
        """A best-effort, stable fingerprint of params that affect generation."""
        fields = [
            "model",
            "model_name",
            "temperature",
            "top_p",
            "max_tokens",
            "presence_penalty",
            "frequency_penalty",
            "seed",
            "base_url",
            "openai_api_base",
        ]
        fp: Dict[str, Any] = {}
        for name in fields:
            if hasattr(self, name):
                val = getattr(self, name)
                if val is not None:
                    fp[name] = val
        # model_kwargs can affect results (logit_bias, etc.)
        if hasattr(self, "model_kwargs"):
            mk = getattr(self, "model_kwargs")
            if mk:
                fp["model_kwargs"] = mk
        return fp

    def _make_key(self, method: str, args: tuple, kwargs: dict) -> str:
        return make_key(
            namespace="langchain.chatopenai",
            data={
                "method": method,
                "args": args,
                "kwargs": kwargs,
                "llm": self._llm_fingerprint(),
            },
        )

    def _get_cached(self, key: str):
        return self._cache.get(key)

    def _set_cached(self, key: str, value: Any):
        self._cache.set(key, value)

    def _normalize_messages(self, messages: List[Any]) -> List[BaseMessage]:
        norm: List[BaseMessage] = []
        for m in messages:
            if isinstance(m, BaseMessage):
                norm.append(m)
            elif isinstance(m, dict):
                t = m.get("type")
                c = m.get("content", "")
                if t == "system":
                    norm.append(SystemMessage(content=c))
                elif t in ("user", "human"):
                    norm.append(HumanMessage(content=c))
                elif t in ("assistant", "ai"):
                    norm.append(AIMessage(content=c))
                else:
                    raise ValueError(f"Unknown message type: {t}")
            else:
                raise ValueError(f"Unsupported message element: {m!r}")
        return norm

    @staticmethod
    def _message_dump(message: BaseMessage) -> Dict[str, Any]:
        """Return a stable dictionary representation of a message."""
        if hasattr(message, "model_dump"):
            return message.model_dump()
        if hasattr(message, "dict"):
            return message.dict()  # pyright: ignore[reportDeprecated]
        if hasattr(message, "__dict__"):
            return dict(message.__dict__)
        raise TypeError(f"Unsupported message type for dumping: {type(message)!r}")

    async def _run_queued(self, key: str, coro_factory):
        """In-flight dedup + concurrency limiting wrapper for async calls."""
        existing = self._inflight.get(key)
        if existing:
            return await existing
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._inflight[key] = fut
        try:
            async with self._sem:
                result = await coro_factory()
                fut.set_result(result)
                return result
        except Exception as e:
            fut.set_exception(e)
            raise
        finally:
            self._inflight.pop(key, None)

    # -------------- async public API --------------

    async def apredict( # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        prompt: str,
        stop: Optional[str] = None,
        sender: Optional[str] = None,
    ) -> str:  
        method = "apredict"
        key = self._make_key(method, (prompt,), {"stop": stop, "sender": sender})
        if self.cache_enabled:
            cached = self._get_cached(key)
            if cached is not None:
                logger.info(f"[CACHE HIT] apredict, key = {key}")
                return cached
        logger.info(f"[CACHE MISS] apredict, key = {key}")
        async def _call():
            parent = cast(Any, super(CachedQueuedChatOpenAI, self))
            return await parent.apredict(prompt, stop=stop)
        out = await self._run_queued(key, _call)
        if self.cache_enabled:
            self._set_cached(key, out)
        return out

    async def acomplete( # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        prompt: str,
        stop: Optional[str] = None,
        sender: Optional[str] = None,
    ) -> LLMResult:  
        method = "acomplete"
        key = self._make_key(method, (prompt,), {"stop": stop, "sender": sender})
        if self.cache_enabled:
            cached = self._get_cached(key)
            if cached is not None:
                logger.info(f"[CACHE HIT] acomplete, key = {key}")
                return cached
        logger.info(f"[CACHE MISS] acomplete, key = {key}")
        async def _call():
            parent = cast(Any, super(CachedQueuedChatOpenAI, self))
            return await parent.acomplete(prompt, stop=stop)
        out = await self._run_queued(key, _call)
        if self.cache_enabled:
            self._set_cached(key, out)
        return out

    async def abatch( # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        prompts: List[str],
        stop: Optional[str] = None,
        sender: Optional[str] = None,
    ) -> LLMResult:  
        method = "abatch"
        key = self._make_key(method, (tuple(prompts),), {"stop": stop, "sender": sender})
        if self.cache_enabled:
            cached = self._get_cached(key)
            if cached is not None:
                logger.info(f"[CACHE HIT] abatch, key = {key}")
                return cached
        logger.info(f"[CACHE MISS] abatch, key = {key}")
        async def _call():
            parent = cast(Any, super(CachedQueuedChatOpenAI, self))
            # LangChain's type stubs may define a more generic input type.
            return await parent.abatch(cast(Any, prompts), stop=stop)
        out = await self._run_queued(key, _call)
        if self.cache_enabled:
            self._set_cached(key, out)
        return out

    async def agenerate( # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        messages: List[Union[BaseMessage, dict]],
        stop: Optional[List[str]] = None,
        callbacks: Optional[List[Any]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        run_manager: Any = None,
        sender: Optional[str] = None,
    ) -> ChatResult:  
        method = "agenerate"
        msgs = self._normalize_messages(messages)
        msgs = [msgs]
        key = self._make_key(
            method,
            (tuple(self._message_dump(m) for m in msgs[0]),),
            {"stop": stop, "sender": sender},
        )
        if self.cache_enabled:
            cached = self._get_cached(key)
            if cached is not None:
                logger.info(f"[CACHE HIT] agenerate, key = {key}")
                return cached
        logger.info(f"[CACHE MISS] agenerate, key = {key}")
        async def _call():
            parent = cast(Any, super(CachedQueuedChatOpenAI, self))
            return await parent.agenerate(
                messages=cast(Any, msgs),
                stop=stop,
                callbacks=callbacks,
                tags=tags,
                metadata=metadata,
                # run_manager опускаем — в текущей версии LC его уже прокидывают внутри
            )
        out = await self._run_queued(key, _call)
        if self.cache_enabled:
            self._set_cached(key, out)
        return out

    async def ainvoke( # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        input: Optional[Union[PromptValue, str]] = None,
        /,
        *,
        messages: Optional[List[Union[BaseMessage, dict]]] = None,
        stop: Optional[List[str]] = None,
        callbacks: Optional[List[Any]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        run_manager: Any = None,
        sender: Optional[str] = None,
    ) -> ChatResult:  
        method = "ainvoke"
        key_args: tuple[Any, ...]
        if messages is not None:
            msgs = self._normalize_messages(messages)
            key_args = (tuple(self._message_dump(m) for m in msgs),)
        else:
            key_args = (input,)
        key = self._make_key(method, key_args, {"stop": stop, "sender": sender})

        if self.cache_enabled:
            cached = self._get_cached(key)
            if cached is not None:
                logger.info(f"[CACHE HIT] ainvoke, key = {key}")
                return cached
        logger.info(f"[CACHE MISS] ainvoke, key = {key}")
        async def _call():
            parent = cast(Any, super(CachedQueuedChatOpenAI, self))
            return await parent.ainvoke(
                cast(Any, input),
                messages=cast(Any, messages),
                stop=stop,
                callbacks=callbacks,
                tags=tags,
                metadata=metadata,
            )
        out = await self._run_queued(key, _call)
        if self.cache_enabled:
            self._set_cached(key, out)
        return out

    # -------------- disable sync API --------------
    def _no_sync_guard(self, *args, **kwargs):
        raise RuntimeError("Sync методы отключены. Используйте a*-версии (async).")

    # Disable sync methods explicitly
    predict = _no_sync_guard
    complete = _no_sync_guard
    batch = _no_sync_guard
    generate = _no_sync_guard
    invoke = _no_sync_guard
    stream = _no_sync_guard
