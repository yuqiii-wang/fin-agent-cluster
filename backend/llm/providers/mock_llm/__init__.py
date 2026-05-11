"""Mock LLM provider for throughput and concurrency testing.

Token sequence
--------------
Every stream emits exactly the following tokens in order::

    "<think>"
    … body tokens …
    "</think>"
    JSON summary  ← key depends on mode (see below)

Modes
-----
``fanout``
    Emit all body tokens as fast as possible (``await asyncio.sleep(0)``
    between yields).  Use when you want to saturate throughput, e.g. with
    ``total_tokens=1_000_000``.
    Final token: ``'{"total_tokens": <n>}'``

``throttle``
    Emit body tokens at a steady ``tokens_per_sec`` rate (default 100).
    Uses absolute timestamps to avoid drift accumulation.  Use when you
    need a controlled concurrency load.
    Final token: ``'{"total_tokens": <n>}'``

``semantic``
    Emit AAPL-related noun/verb/adjective combinations and permutations at
    exactly 30 tokens/sec for 10 seconds (300 tokens total), using
    absolute-time scheduling to prevent drift.
    Final token: ``'{"conclusion": "…"}''``

Usage
-----
Direct instantiation::

    llm = MockLLM(mode="fanout", total_tokens=1_000_000)
    llm = MockLLM(mode="throttle", total_tokens=500, tokens_per_sec=200.0)
    llm = MockLLM(mode="semantic")

    async for chunk in llm.astream([]):
        print(chunk.content, end="", flush=True)
"""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import AsyncIterator
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult


def _chunk(content: str) -> ChatGenerationChunk:
    return ChatGenerationChunk(message=AIMessageChunk(content=content))


# ---------------------------------------------------------------------------
# Semantic mode: AAPL word pools
# ---------------------------------------------------------------------------

_AAPL_NOUNS: tuple[str, ...] = (
    "AAPL", "stock", "share", "price", "market",
    "rally", "earnings", "revenue", "dividend", "momentum",
    "bull", "bear", "trend", "support", "resistance",
)

_AAPL_VERBS: tuple[str, ...] = (
    "surges", "rallies", "climbs", "drops", "consolidates",
    "rebounds", "targets", "beats", "misses", "breaks",
)

_AAPL_ADJS: tuple[str, ...] = (
    "bullish", "bearish", "volatile", "strong", "weak",
    "oversold", "overbought", "positive", "negative", "technical",
)

_SEMANTIC_TOKENS_PER_SEC: float = 30.0
_SEMANTIC_DURATION_SECS: int = 10


def _build_semantic_token_pool() -> list[str]:
    """Return an ordered pool of AAPL phrases from word combinations."""
    return (
        [f"{a} {n}" for a, n in itertools.product(_AAPL_ADJS, _AAPL_NOUNS)]
        + [f"{n} {v}" for n, v in itertools.product(_AAPL_NOUNS, _AAPL_VERBS)]
        + [f"{a} {v}" for a, v in itertools.product(_AAPL_ADJS, _AAPL_VERBS)]
    )


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

    # ``semantic`` mode ignores total_tokens / tokens_per_sec;
    # it always runs at 30 tok/s for 10 s (300 tokens).

    @property
    def _llm_type(self) -> str:
        return "mock_llm"

    # ------------------------------------------------------------------
    # LangChain BaseChatModel interface
    # ------------------------------------------------------------------

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
        # ── token 1: <think> ──────────────────────────────────────────
        yield _chunk("<think>")
        await asyncio.sleep(0)

        # ── body tokens ───────────────────────────────────────────────
        if self.mode == "fanout":
            async for tok in self._fanout_tokens():
                yield tok
        elif self.mode == "semantic":
            async for tok in self._semantic_tokens():
                yield tok
        else:
            async for tok in self._throttle_tokens():
                yield tok

        # ── second-to-last: </think> ──────────────────────────────────
        yield _chunk("</think>")
        await asyncio.sleep(0)

        # ── last: JSON summary ────────────────────────────────────────
        yield _chunk(json.dumps({"total_tokens": self.total_tokens}))

    # ------------------------------------------------------------------
    # Emission helpers
    # ------------------------------------------------------------------

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
        """Yield AAPL noun/verb/adj combination tokens at 30 tok/s for 10 s.

        Phrases are drawn from the Cartesian products of the three word pools
        and cycled if the pool is exhausted before 300 tokens are emitted.
        Absolute-time scheduling prevents rate drift.
        """
        total = int(_SEMANTIC_TOKENS_PER_SEC * _SEMANTIC_DURATION_SECS)  # 300
        interval: float = 1.0 / _SEMANTIC_TOKENS_PER_SEC
        loop = asyncio.get_event_loop()
        next_emit: float = loop.time()

        pool = _build_semantic_token_pool()
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
