"""MockLLM — streaming mock chat model for performance benchmarking."""

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
    """Streaming mock chat model for performance benchmarking.

    Parameters
    ----------
    mode:
        ``"fanout"``   – emit tokens with no rate limit (throughput test).
        ``"throttle"`` – emit at ``tokens_per_sec`` (concurrency test).
        ``"semantic"`` – emit AAPL-related tokens at 30 tok/s for 10 s (semantic test).
    total_tokens:
        Number of numbered body tokens to emit.
        Fanout default: 1 000 000.  Throttle default: 100.
    tokens_per_sec:
        Steady-state emission rate; only meaningful in ``"throttle"`` mode.
        Default: 100.
    """

    mode: str = "throttle"
    total_tokens: int = 100
    tokens_per_sec: float = 100.0

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

        if self.mode == "fanout":
            async for tok in self._fanout_tokens():
                yield tok
        elif self.mode == "semantic":
            async for tok in self._semantic_tokens():
                yield tok
        else:
            async for tok in self._throttle_tokens():
                yield tok

        yield _chunk("</think>")
        await asyncio.sleep(0)

        yield _chunk(json.dumps({"total_tokens": self.total_tokens}))

    async def _fanout_tokens(self) -> AsyncIterator[ChatGenerationChunk]:
        """Yield numbered tokens as fast as the event loop allows."""
        for i in range(1, self.total_tokens + 1):
            yield _chunk(f"{i} ")
            await asyncio.sleep(0)

    async def _throttle_tokens(self) -> AsyncIterator[ChatGenerationChunk]:
        """Yield numbered tokens at exactly ``tokens_per_sec`` using
        absolute-time scheduling to prevent drift."""
        interval: float = 1.0 / self.tokens_per_sec
        loop = asyncio.get_event_loop()
        next_emit: float = loop.time()

        for i in range(1, self.total_tokens + 1):
            now = loop.time()
            wait = next_emit - now
            if wait > 0:
                await asyncio.sleep(wait)
            yield _chunk(f"{i} ")
            next_emit += interval

    async def _semantic_tokens(self) -> AsyncIterator[ChatGenerationChunk]:
        """Yield AAPL noun/verb/adj combination tokens at 30 tok/s for 10 s."""
        total = int(SEMANTIC_TOKENS_PER_SEC * SEMANTIC_DURATION_SECS)
        interval: float = 1.0 / SEMANTIC_TOKENS_PER_SEC
        loop = asyncio.get_event_loop()
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
    mode: str = "throttle",
    total_tokens: int = 100,
    tokens_per_sec: float = 100.0,
) -> MockLLM:
    """Convenience factory for ``MockLLM``."""
    return MockLLM(mode=mode, total_tokens=total_tokens, tokens_per_sec=tokens_per_sec)


__all__ = ["MockLLM", "get_mock_llm"]
