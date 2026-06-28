
"""BaseLLM — base chat model that normalizes prompts and exposes a ``search_and_summary`` capability.

The optional :meth:`search_and_summary` method lets callers ask the LLM (or its built-in
web-search API) run a web search and return both the summarised answer and the
raw search citations.  Providers with native search-and-summary (ARK/Doubao
``web_search``) override it; generic providers (Ollama, mock) return
``None`` so the caller falls back to DDGS + LLM summary.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Optional, Sequence, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


def normalize_spaces(text: str) -> str:
    """Replace multiple consecutive spaces with a single space."""
    return re.sub(r"\s+", " ", text).strip()


class SearchAndSummaryResult(BaseModel):
    """Result returned by :meth:`BaseLLM.search_and_summary` when the provider
    supports native web search.

    Attributes:
        answer:       The summarised textual answer produced by the model after
                      searching the web.
        sources:      Optional list of source URLs / citations (title + url).
        raw:          Optional raw provider-specific payload (for diagnostics).
    """

    answer: str = Field(description="Summarised textual answer.")
    sources: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of source/citation dicts with keys like title, url, snippet.",
    )
    raw: dict[str, Any] | None = Field(
        default=None,
        description="Optional provider-specific raw payload for diagnostics.",
    )


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

    # ------------------------------------------------------------------
    # Optional: native LLM search-and-summary
    # ------------------------------------------------------------------

    async def search_and_summary(
        self,
        query: str,
        **kwargs: Any,
    ) -> Optional["SearchAndSummaryResult"]:
        """Optional native search-and-summary capability.

        Providers with a built-in web search API (ARK Doubao ``web_search``)
        override this to produce an answer plus citation links in a single
        API call.  Generic providers (Ollama, mock) return ``None`` so the
        caller can fall back to an external search (e.g. DDGS) plus a
        separate summarising LLM call.

        Args:
            query: Free-form query string in any language.
            **kwargs: Provider-specific options forwarded to the implementation.

        Returns:
            A :class:`SearchAndSummaryResult` on success, or ``None`` if the
            provider does not support native search-and-summary.
        """
        return None


__all__ = ["BaseLLM", "SearchAndSummaryResult", "normalize_spaces"]

