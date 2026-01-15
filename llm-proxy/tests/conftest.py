from __future__ import annotations

import sys
import types
from typing import Any, cast


def _install_openai_stub_if_needed() -> None:
    try:
        import openai  # noqa: F401
        import openai as _openai
        if hasattr(_openai, "AsyncOpenAI") and hasattr(_openai, "OpenAIError"):
            return
    except Exception:
        pass

    mod = types.ModuleType("openai")

    class OpenAIError(Exception):
        pass

    class _Completions:
        def __init__(self) -> None:
            self.create = None

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class AsyncOpenAI:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.chat = _Chat()

    mod_any = cast(Any, mod)
    mod_any.AsyncOpenAI = AsyncOpenAI
    mod_any.OpenAIError = OpenAIError
    sys.modules["openai"] = mod

_install_openai_stub_if_needed()
