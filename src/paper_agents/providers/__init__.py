"""Model provider adapters."""

from paper_agents.providers.base import ChatMessage, ModelProvider, ModelResponse
from paper_agents.providers.openai_compatible import OpenAICompatibleProvider

__all__ = [
    "ChatMessage",
    "ModelProvider",
    "ModelResponse",
    "OpenAICompatibleProvider",
]
