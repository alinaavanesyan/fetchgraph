from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast


def test_deps_build_cache_singleton(tmp_path):
    import llm.deps as llm_deps

    settings = SimpleNamespace(
        llm_cache_path=str(tmp_path / "cache.sqlite"),
        llm_cache_ttl=0,
        llm_cache_enabled=True,
    )

    llm_deps.reset_chat_dependencies()
    c1 = llm_deps.build_cache(cast(Any, settings))
    c2 = llm_deps.build_cache(cast(Any, settings))
    assert c1 is c2


def test_deps_pass_same_cache_to_llm_and_provider(tmp_path, monkeypatch):
    import llm.deps as llm_deps

    captured = {}

    # Patch constructors to capture the injected cache.
    def fake_create_custom_llm(settings, cache=None, **kwargs):
        captured["llm_cache"] = cache
        return object()

    class FakeProvider:
        def __init__(self, settings, *, cache=None):
            captured["provider_cache"] = cache

    monkeypatch.setattr(llm_deps, "create_custom_llm", fake_create_custom_llm)
    monkeypatch.setattr(llm_deps, "OpenAIChatProvider", FakeProvider)

    settings = SimpleNamespace(
        # Cache settings used by build_cache
        llm_cache_path=str(tmp_path / "cache.sqlite"),
        llm_cache_ttl=0,
        llm_cache_enabled=True,

        # Required by build_llm/create_custom_llm in the real code (but our fake ignores)
        llm_priority_total_slots=1,
        llm_max_concurrent=1,
        llm_api_base="http://example",
        llm_default_model_name="gpt-test",
        llm_model_override=None,
        llm_temperature=0.0,
        llm_api_key="x",
        llm_verbose=False,
        llm_max_tokens=16,
        llm_top_p=1.0,
        llm_timeout=30,

        # Required by build_chat_queue in case it is called
        llm_priority_limits_map={},
        llm_queue_max_len=100,
        llm_priority_default=0,
    )

    llm_deps.reset_chat_dependencies()

    llm_deps.build_llm(cast(Any, settings))
    llm_deps.build_chat_provider(cast(Any, settings))

    assert captured["llm_cache"] is captured["provider_cache"]
