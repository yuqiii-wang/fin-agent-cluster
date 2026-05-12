"""MockLLM — streaming mock chat model for semantic/concurrency testing."""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import AsyncIterator
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from backend.llm.providers.mock_llm.word_pool import (
    SEMANTIC_DURATION_SECS,
    SEMANTIC_TOKENS_PER_SEC,
    build_semantic_token_pool,
)


def _chunk(content: str) -> ChatGenerationChunk:
    return ChatGenerationChunk(message=AIMessageChunk(content=content))


class MockLLM(BaseChatModel):
    """Streaming mock chat model.

    Emits AAPL-related tokens at the configured rate for the configured duration.
    Defaults to 30 tok/s for 10 s when not overridden.
    """

    tokens_per_sec: float = SEMANTIC_TOKENS_PER_SEC
    duration_secs: float = float(SEMANTIC_DURATION_SECS)

    @property
    def _llm_type(self) -> str:
        return "mock_llm"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("MockLLM only supports async streaming.")

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        yield _chunk("<think>")
        await asyncio.sleep(0)

        async for tok in self._semantic_tokens():
            yield tok

        yield _chunk("</think>")
        await asyncio.sleep(0)

        yield _chunk(json.dumps({"total_tokens": int(self.tokens_per_sec * self.duration_secs)}))

    async def _semantic_tokens(self) -> AsyncIterator[ChatGenerationChunk]:
        """Yield AAPL noun/verb/adj combination tokens at the configured rate."""
        total = int(self.tokens_per_sec * self.duration_secs)
        interval: float = 1.0 / self.tokens_per_sec
        loop = asyncio.get_running_loop()
        next_emit: float = loop.time()

        pool = build_semantic_token_pool()
        token_iter = itertools.islice(itertools.cycle(pool), total)

        for phrase in token_iter:
            now = loop.time()
            wait = next_emit - now
            if wait > 0:
                await asyncio.sleep(wait)
            yield _chunk(phrase + " ")
            next_emit += interval


def get_mock_llm(
    tokens_per_sec: float = SEMANTIC_TOKENS_PER_SEC,
    duration_secs: float = float(SEMANTIC_DURATION_SECS),
) -> MockLLM:
    """Convenience factory for ``MockLLM`` with configurable rate and duration."""
    return MockLLM(tokens_per_sec=tokens_per_sec, duration_secs=duration_secs)


__all__ = ["MockLLM", "get_mock_llm"]
