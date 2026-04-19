"""Mock LLM provider for streaming performance testing.

Streams ``mock_msg_<thread_id>_<seq_id>`` tokens indefinitely (or until
cancelled / timeout) with a configurable inter-token delay.  Tokens are
yielded directly from ``_astream`` with no internal worker task or queue —
the caller (:mod:`backend.graph.agents.perf_test.tasks.fanout_to_streams`)
owns the queue and backpressure logic.

This provider is never registered in ``LLM_PROVIDER`` — it is instantiated
directly by :mod:`backend.graph.agents.perf_test.tasks.fanout_to_streams`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult

logger = logging.getLogger(__name__)


class MockChatModel(BaseChatModel):
    """Streaming mock LLM for performance/load testing.

    Emits tokens of the form ``mock_msg_<thread_id>_<seq_id>`` where *seq_id*
    increments from 1 until *timeout_secs* elapses or the caller breaks out of
    the async iteration.  Each token is yielded directly — no internal worker
    task or queue is created, so there are no orphaned asyncio tasks on cleanup.

    Attributes:
        thread_id:    LangGraph thread UUID injected by the perf-test caller.
        timeout_secs: Hard stream lifetime in seconds.
    """

    thread_id: str = ""
    timeout_secs: float

    @property
    def _llm_type(self) -> str:
        """Return provider identifier."""
        return "mock"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous generation — not supported; mock is async-only.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("MockChatModel only supports async streaming.")

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Yield mock token chunks until cancelled, timeout, or the caller breaks.

        Yields tokens directly with ``await asyncio.sleep(0)`` between each to
        cooperatively yield the event loop.  No internal worker task or queue is
        created so ``aclose()`` (triggered by a ``break`` in the caller's
        ``async for``) completes without orphaned asyncio tasks.

        Args:
            messages:  Ignored (mock does not parse input).
            stop:      Ignored.
            **kwargs:  Ignored.

        Yields:
            ``ChatGenerationChunk`` with a single mock token as content.
        """
        seq_id = 1
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.timeout_secs
        t_start = time.perf_counter()
        log_interval = 100

        try:
            while loop.time() < deadline:
                token = f"mock_msg_{self.thread_id}_{seq_id} "
                yield ChatGenerationChunk(message=AIMessageChunk(content=token))
                seq_id += 1
                if seq_id % log_interval == 0:
                    elapsed = time.perf_counter() - t_start
                    logger.debug(
                        "[mock_llm] throughput seq_id=%d tps=%.1f thread_id=%s",
                        seq_id, seq_id / max(elapsed, 0.001), self.thread_id,
                    )
                await asyncio.sleep(0)

            elapsed = time.perf_counter() - t_start
            logger.info(
                "[mock_llm] timeout reached seq_id=%d elapsed=%.1fs tps=%.1f thread_id=%s",
                seq_id, elapsed, seq_id / max(elapsed, 0.001), self.thread_id,
            )
        except (asyncio.CancelledError, GeneratorExit):
            elapsed = time.perf_counter() - t_start
            logger.debug(
                "[mock_llm] stream cancelled tokens_yielded=%d elapsed=%.3fs thread_id=%s",
                seq_id - 1, elapsed, self.thread_id,
            )
            raise


def get_mock_llm(thread_id: str, timeout_secs: float) -> MockChatModel:
    """Return a configured :class:`MockChatModel` for *thread_id*.

    Args:
        thread_id:    LangGraph thread UUID to embed in each token.
        timeout_secs: Hard stream lifetime in seconds.

    Returns:
        A ready-to-use :class:`MockChatModel` instance.
    """
    return MockChatModel(thread_id=thread_id, timeout_secs=timeout_secs)
