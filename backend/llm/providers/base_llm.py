
"""BaseLLM — base chat model that normalizes prompts to replace multiple spaces with single ones."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Optional, Sequence, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool


def normalize_spaces(text: str) -> str:
    """Replace multiple consecutive spaces with a single space.
    Also normalizes newlines and tabs to single space if needed,
    but preserves intentional single line breaks.
    """
    # Replace any whitespace sequence (multiple spaces, tabs, newlines)
    # with a single space, but trim leading/trailing.
    return re.sub(r"\s+", " ", text).strip()


class BaseLLM(BaseChatModel, ABC):
    """Base LLM class that normalizes prompt content before sending to provider.
    All provider-specific LLM classes (OllamaLLM, ArkLLM, etc.) should inherit from this.
    """

    provider: str
    model: str

    @property
    @abstractmethod
    def _llm_type(self) -> str:
        """Must implement _llm_type in subclass."""

    def _normalize_messages(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Normalize all message content to replace multiple spaces with single spaces."""
        normalized = []
        for msg in messages:
            new_msg = msg.model_copy()
            if hasattr(new_msg, "content") and new_msg.content:
                if isinstance(new_msg.content, str):
                    new_msg.content = normalize_spaces(new_msg.content)
                elif isinstance(new_msg.content, list):
                    # Handle multimodal content (e.g., images + text)
                    normalized_parts = []
                    for part in new_msg.content:
                        if isinstance(part, dict) and "text" in part:
                            part = {**part, "text": normalize_spaces(part["text"])}
                        normalized_parts.append(part)
                    new_msg.content = normalized_parts
            normalized.append(new_msg)
        return normalized

    @abstractmethod
    def bind_tools(
        self,
        tools: Sequence[Union[dict[str, Any], type, Any, BaseTool]],
        **kwargs: Any,
    ) -> Runnable:
        """Bind tools to this LLM — subclasses must implement."""

    @abstractmethod
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous generation — subclasses must implement this, and should call _normalize_messages first."""

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Asynchronous generation — subclasses may override this, default defers to _generate."""
        import asyncio
        return await asyncio.to_thread(
            lambda: self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        )

    @abstractmethod
    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ):
        """Asynchronous streaming — subclasses must implement this, and should call _normalize_messages first."""


__all__ = ["BaseLLM", "normalize_spaces"]

