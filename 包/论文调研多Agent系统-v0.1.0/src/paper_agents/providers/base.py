"""Provider-neutral interfaces used by agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict


class ChatMessage(TypedDict):
    role: str
    content: str


@dataclass(frozen=True)
class ModelResponse:
    content: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelProvider(Protocol):
    """The smallest model interface needed by our agents."""

    @property
    def model_name(self) -> str: ...

    def complete(self, messages: list[ChatMessage]) -> ModelResponse: ...
