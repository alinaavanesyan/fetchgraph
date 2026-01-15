from __future__ import annotations

import logging
from typing import Any, cast

import pytest

from llm.models.chat import ChatCompletionRequest, ChatMessage
from llm.services.cache import SQLiteCache
from llm.services.chat_provider import OpenAIChatProvider


class DummySettings:
    def __init__(
        self,
        *,
        cache_path: str,
        llm_default_model_name: str = "gpt-test",
        llm_model_override: str | None = None,
    ):
        self.llm_api_key = "test"
        self.llm_api_base = "http://example"
        self.llm_timeout = 30
        self.llm_default_model_name = llm_default_model_name
        self.llm_model_override = llm_model_override
        self.llm_temperature = 0.1
        self.llm_top_p = 1.0
        self.llm_cache_ttl = 0
        self.llm_cache_enabled = True
        self.llm_cache_path_resolved = cache_path


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


@pytest.mark.asyncio
async def test_chat_provider_caches_identical_requests(tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.INFO)

    cache = SQLiteCache(path=str(tmp_path / "cache.sqlite"), ttl_seconds=0, enabled=True)
    settings = DummySettings(cache_path=cache.path)

    provider = OpenAIChatProvider(cast(Any, settings), cache=cache)

    # Install async stub for openai call
    calls = {"n": 0}

    async def create(**payload):
        calls["n"] += 1
        return _Resp({"echo": payload})

    # provider._client.chat.completions.create
    monkeypatch.setattr(provider._client.chat.completions, "create", create, raising=False)

    req = ChatCompletionRequest(
        model=None,
        messages=[ChatMessage(role="user", content="hi")],
        temperature=None,
    )

    r1 = await provider.complete(req)
    r2 = await provider.complete(req)

    assert calls["n"] == 1
    assert r1 == r2

    # We should see one miss and one hit, each with a key.
    logs = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "[CACHE MISS] /v1/chat key=" in logs
    assert "[CACHE HIT] /v1/chat key=" in logs

    import re
    assert re.search(r"\[CACHE MISS\] /v1/chat key=(?:[a-z0-9_-]+:)?[0-9a-f]{64}\b", logs)
    assert re.search(r"\[CACHE HIT\] /v1/chat key=(?:[a-z0-9_-]+:)?[0-9a-f]{64}\b", logs)


@pytest.mark.asyncio
async def test_chat_provider_cache_key_changes_when_params_change(tmp_path, monkeypatch):
    cache = SQLiteCache(path=str(tmp_path / "cache.sqlite"), ttl_seconds=0, enabled=True)
    settings = DummySettings(cache_path=cache.path)
    provider = OpenAIChatProvider(cast(Any, settings), cache=cache)

    calls = {"n": 0}

    async def create(**payload):
        calls["n"] += 1
        return _Resp({"ok": True, "payload": payload})

    monkeypatch.setattr(provider._client.chat.completions, "create", create, raising=False)

    base = {
        "model": None,
        "messages": [ChatMessage(role="user", content="hi")],
    }

    req_t1 = ChatCompletionRequest(**base, temperature=0.2)
    req_t2 = ChatCompletionRequest(**base, temperature=0.7)

    await provider.complete(req_t1)
    await provider.complete(req_t2)

    # Different temperature => different cache key => two provider calls
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_model_override_respected_when_explicit(tmp_path, monkeypatch):
    cache = SQLiteCache(path=str(tmp_path / "cache.sqlite"), ttl_seconds=0, enabled=False)
    settings = DummySettings(
        cache_path=cache.path,
        llm_model_override="override-model",
    )
    provider = OpenAIChatProvider(cast(Any, settings), cache=cache)

    captured_payloads: list[dict[str, Any]] = []

    async def create(**payload):
        captured_payloads.append(payload)
        return _Resp({"ok": True, "payload": payload})

    monkeypatch.setattr(provider._client.chat.completions, "create", create, raising=False)

    req = ChatCompletionRequest(
        model="sender-model",
        messages=[ChatMessage(role="user", content="hi")],
    )

    await provider.complete(req)
    assert captured_payloads[-1]["model"] == "override-model"

    req_no_model = ChatCompletionRequest(
        model=None,
        messages=[ChatMessage(role="user", content="hi 2")],
    )
    await provider.complete(req_no_model)
    assert captured_payloads[-1]["model"] == "override-model"

    req_default_literal = ChatCompletionRequest(
        model="default",
        messages=[ChatMessage(role="user", content="hi 3")],
    )
    await provider.complete(req_default_literal)
    assert captured_payloads[-1]["model"] == "override-model"


@pytest.mark.asyncio
async def test_sender_model_respected_when_no_override(tmp_path, monkeypatch):
    cache = SQLiteCache(path=str(tmp_path / "cache.sqlite"), ttl_seconds=0, enabled=False)
    settings = DummySettings(
        cache_path=cache.path,
        llm_default_model_name="proxy-default",
    )
    provider = OpenAIChatProvider(cast(Any, settings), cache=cache)

    captured_payloads: list[dict[str, Any]] = []

    async def create(**payload):
        captured_payloads.append(payload)
        return _Resp({"ok": True, "payload": payload})

    monkeypatch.setattr(provider._client.chat.completions, "create", create, raising=False)

    sender_model = ChatCompletionRequest(
        model="sender-model",
        messages=[ChatMessage(role="user", content="hi")],
    )
    await provider.complete(sender_model)
    assert captured_payloads[-1]["model"] == "sender-model"

    missing_model = ChatCompletionRequest(
        model=None,
        messages=[ChatMessage(role="user", content="hi 2")],
    )
    await provider.complete(missing_model)
    assert captured_payloads[-1]["model"] == "proxy-default"

    default_literal = ChatCompletionRequest(
        model="default",
        messages=[ChatMessage(role="user", content="hi 3")],
    )
    await provider.complete(default_literal)
    assert captured_payloads[-1]["model"] == "default"
