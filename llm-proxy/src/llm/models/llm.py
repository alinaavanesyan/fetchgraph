# src/models/llm.py
from typing import Any, Dict, List

from pydantic import BaseModel


class LLMRequest(BaseModel):
    method: str
    args: List[Any] = []
    kwargs: Dict[str, Any] = {}
    sender: str = "unknown"