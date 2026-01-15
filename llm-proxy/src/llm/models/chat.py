from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Any
    name: str | None = None

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def validate_content(self) -> "ChatMessage":
        if self.content is None:
            raise ValueError("Message content cannot be null")
        if not isinstance(self.content, (str, list, dict)):
            raise ValueError(f"Unsupported message content type: {type(self.content).__name__}")
        if isinstance(self.content, list):
            for idx, item in enumerate(self.content):
                if not isinstance(item, (str, dict)):
                    raise ValueError(f"Invalid list item at index {idx}: {item!r}")
        return self


class ChatCompletionRequest(BaseModel):
    model: str | None = Field(None, min_length=1)
    messages: list[ChatMessage] = Field(..., min_length=1)
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: str | list[str] | None = None
    stream: bool = False

    model_config = ConfigDict(extra="allow")

    @field_validator("messages")
    @classmethod
    def _ensure_messages_not_empty(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        if not value:
            raise ValueError("messages cannot be empty")
        return value

    def to_provider_payload(
        self,
        *,
        default_model: str,
        default_temperature: float | None = None,
        default_top_p: float | None = None,
    ) -> dict[str, Any]:
        payload = self.model_dump(exclude_none=True)
        payload.pop("stream", None)
        payload["messages"] = [m.model_dump(exclude_none=True) for m in self.messages]

        payload.setdefault("model", default_model)
        if "temperature" not in payload and default_temperature is not None:
            payload["temperature"] = default_temperature
        if "top_p" not in payload and default_top_p is not None:
            payload["top_p"] = default_top_p
        return payload
