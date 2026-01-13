from __future__ import annotations

import logging

import pytest


@pytest.mark.asyncio
async def test_wrapper_apredict_uses_cache(tmp_path, monkeypatch, caplog):
    # These tests require the real langchain dependencies.
    pytest.importorskip("langchain_openai")
    pytest.importorskip("langchain_core")

    from langchain_openai import ChatOpenAI

    from llm.services.cache import SQLiteCache
    from llm.services.wrapper import CachedQueuedChatOpenAI

    caplog.set_level(logging.INFO)

    calls = {"n": 0}

    async def fake_apredict(self, prompt: str, stop=None):
        calls["n"] += 1
        return f"OUT:{prompt}:{stop}"

    monkeypatch.setattr(ChatOpenAI, "apredict", fake_apredict, raising=True)

    cache = SQLiteCache(path=str(tmp_path / "cache.sqlite"), ttl_seconds=0, enabled=True)

    llm = CachedQueuedChatOpenAI(
        api_key="test",
        base_url="http://example",
        model_name="gpt-test",
        model="gpt-test",
        temperature=0.0,
        verbose=False,
        max_tokens=16,
        cache_enabled=True,
        cache_path=cache.path,
        cache_ttl=0,
        max_concurrent=5,
        cache=cache,
    )

    out1 = await llm.apredict("hi")
    out2 = await llm.apredict("hi")

    assert out1 == out2
    assert calls["n"] == 1

    logs = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "[CACHE MISS] apredict" in logs
    assert "[CACHE HIT] apredict" in logs
    assert "key =" in logs


@pytest.mark.asyncio
async def test_wrapper_cache_key_includes_llm_params(tmp_path, monkeypatch):
    pytest.importorskip("langchain_openai")
    pytest.importorskip("langchain_core")

    from langchain_openai import ChatOpenAI

    from llm.services.cache import SQLiteCache
    from llm.services.wrapper import CachedQueuedChatOpenAI

    calls = {"n": 0}

    async def fake_apredict(self, prompt: str, stop=None):
        calls["n"] += 1
        return f"OUT:{prompt}:{stop}"

    monkeypatch.setattr(ChatOpenAI, "apredict", fake_apredict, raising=True)

    cache = SQLiteCache(path=str(tmp_path / "cache.sqlite"), ttl_seconds=0, enabled=True)

    llm1 = CachedQueuedChatOpenAI(
        api_key="test",
        base_url="http://example",
        model_name="gpt-test",
        model="gpt-test",
        temperature=0.1,
        verbose=False,
        max_tokens=16,
        cache_enabled=True,
        cache_path=cache.path,
        cache_ttl=0,
        max_concurrent=5,
        cache=cache,
    )

    llm2 = CachedQueuedChatOpenAI(
        api_key="test",
        base_url="http://example",
        model_name="gpt-test",
        model="gpt-test",
        temperature=0.9,
        verbose=False,
        max_tokens=16,
        cache_enabled=True,
        cache_path=cache.path,
        cache_ttl=0,
        max_concurrent=5,
        cache=cache,
    )

    await llm1.apredict("hi")
    await llm2.apredict("hi")

    # Different temperature should produce different cache key => two underlying calls
    assert calls["n"] == 2