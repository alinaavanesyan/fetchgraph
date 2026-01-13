from __future__ import annotations

import asyncio

import pytest

from llm.services.cache import SQLiteCache


@pytest.mark.asyncio
async def test_aget_or_set_deduplicates_inflight(tmp_path):
    db = tmp_path / "cache.sqlite"
    cache = SQLiteCache(path=str(db), ttl_seconds=0, enabled=True)

    calls = 0

    async def factory():
        nonlocal calls
        calls += 1
        # Give other tasks a chance to enter inflight path
        await asyncio.sleep(0.05)
        return {"ok": True}

    key = "same"

    results = await asyncio.gather(
        cache.aget_or_set(key, factory),
        cache.aget_or_set(key, factory),
        cache.aget_or_set(key, factory),
    )

    assert results == [{"ok": True}, {"ok": True}, {"ok": True}]
    assert calls == 1

    # Subsequent call should be an ordinary cache hit and not call factory.
    res2 = await cache.aget_or_set(key, factory)
    assert res2 == {"ok": True}
    assert calls == 1