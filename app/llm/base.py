"""Abstract base class for LLM clients.

All providers (OpenAI-compatible, llama.cpp, etc.) implement this interface
so agent nodes can swap LLM backends without changing orchestration logic.
"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    """A single chat message."""

    role: str = Field(..., description="Message role: 'system', 'user', or 'assistant'")
    content: str = Field(..., description="Message content text")


class LLMResponse(BaseModel):
    """Standardized LLM response wrapper."""

    content: str = Field(..., description="Generated text content")
    model: str = Field(default="", description="Model name that generated the response")
    usage: dict[str, int] = Field(default_factory=dict, description="Token usage stats")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw provider response")


class LLMClientBase(ABC):
    """Abstract interface for LLM inference clients."""

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.3,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: List of chat messages (system, user, assistant).
            temperature: Sampling temperature (0.0 = deterministic).
            max_tokens: Max tokens to generate (None = provider default).
            **kwargs: Provider-specific parameters.

        Returns:
            LLMResponse with generated content and metadata.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources held by the client."""
        ...

    def to_langchain_chat_model(self) -> Any:
        """Return a LangChain-compatible ChatModel wrapper.

        Override in subclasses that natively integrate with LangChain.
        Returns None if not supported.
        """
        return None
