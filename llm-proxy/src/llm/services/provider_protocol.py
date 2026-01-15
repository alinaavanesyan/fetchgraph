from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from llm.models.chat import ChatCompletionRequest


@runtime_checkable
class ChatProvider(Protocol):
    async def complete(self, request: ChatCompletionRequest) -> dict[str, Any]:
        ...

    @property
    def model_override(self) -> str | None:
        ...
