"""Mock LLM provider for streaming performance testing.

Simulates a thinking LLM: the first token is always ``<think>``.  When
*total_tokens* is supplied the stream is finite — the second-to-last token is
``</think>`` and the last token is a short answer string.  Without a budget
the stream runs until *timeout_secs* elapses (open-ended concurrency mode).

Tokens are yielded directly from ``_astream`` with no internal worker task or
queue — the caller owns the queue and backpressure logic.

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

    Token structure
    ---------------
    * **Finite mode** (``total_tokens`` ≥ 1):

      1. ``<think>``
      2 … N-2. ``mock_msg_<thread_id>_<seq>`` body tokens
      N-1. ``</think>``  (omitted when total_tokens < 3)
      N.   ``mock_answer_<thread_id>``

    * **Open-ended mode** (``total_tokens`` is ``None``):

      1. ``<think>``
      2 …  ``mock_msg_<thread_id>_<seq>`` tokens until *timeout_secs* elapses.

    Attributes:
        thread_id:    LangGraph thread UUID injected by the perf-test caller.
        timeout_secs: Hard stream lifetime in seconds.
        total_tokens: Optional finite token budget.  When set the model stops
                      after emitting exactly this many tokens.
    """

    thread_id: str = ""
    stream_id: str = ""
    timeout_secs: float
    total_tokens: Optional[int] = None

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
        """Yield mock token chunks simulating a thinking LLM.

        In finite mode (``total_tokens`` set) the stream is:
        ``<think>`` → body tokens → ``</think>`` → answer.
        In open-ended mode only ``<think>`` and body tokens are emitted.

        Args:
            messages:  Ignored (mock does not parse input).
            stop:      Ignored.
            **kwargs:  Ignored.

        Yields:
            ``ChatGenerationChunk`` with a single mock token as content.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.timeout_secs
        t_start = time.perf_counter()
        log_interval = 100
        seq_id = 1  # body-token sequence counter (starts at 1)

        def _chunk(content: str) -> ChatGenerationChunk:
            return ChatGenerationChunk(message=AIMessageChunk(content=content))

        try:
            # ── Token 1: <think> ────────────────────────────────────────────
            yield _chunk("<think>")
            await asyncio.sleep(0)

            if self.total_tokens is None:
                # ── Open-ended mode: stream until timeout ───────────────────
                while loop.time() < deadline:
                    yield _chunk(f"mock_msg_{self.thread_id}_{seq_id} ")
                    seq_id += 1
                    if seq_id % log_interval == 0:
                        elapsed = time.perf_counter() - t_start
                        logger.debug(
                            "[mock_llm] throughput seq_id=%d tps=%.1f stream_id=%s",
                            seq_id, seq_id / max(elapsed, 0.001), self.stream_id,
                        )
                    await asyncio.sleep(0)

                elapsed = time.perf_counter() - t_start
                logger.info(
                    "[mock_llm] timeout reached seq_id=%d elapsed=%.1fs tps=%.1f stream_id=%s",
                    seq_id, elapsed, seq_id / max(elapsed, 0.001), self.stream_id,
                )
            else:
                # ── Finite mode: emit body tokens then sentinel pair ─────────
                # body_count = total_tokens - 1 (<think>) - 1 (</think>) - 1 (answer)
                # Clamp to 0 for very small budgets.
                body_count = max(self.total_tokens - 3, 0)

                while seq_id <= body_count and loop.time() < deadline:
                    yield _chunk(f"mock_msg_{self.thread_id}_{seq_id} ")
                    if seq_id % log_interval == 0:
                        elapsed = time.perf_counter() - t_start
                        logger.debug(
                            "[mock_llm] finite seq_id=%d/%d tps=%.1f stream_id=%s",
                            seq_id, body_count,
                            seq_id / max(elapsed, 0.001), self.stream_id,
                        )
                    seq_id += 1
                    await asyncio.sleep(0)

                if loop.time() < deadline:
                    # Emit </think> only when there is room for it (total_tokens >= 3)
                    if self.total_tokens >= 3:
                        yield _chunk("</think>")
                        await asyncio.sleep(0)
                    yield _chunk(f"mock_answer_{self.thread_id}")
                    elapsed = time.perf_counter() - t_start
                    logger.info(
                        "[mock_llm] finite done total=%d elapsed=%.2fs stream_id=%s",
                        self.total_tokens, elapsed, self.stream_id,
                    )
                else:
                    elapsed = time.perf_counter() - t_start
                    logger.info(
                        "[mock_llm] finite timeout body_emitted=%d elapsed=%.1fs stream_id=%s",
                        seq_id - 1, elapsed, self.stream_id,
                    )

        except (asyncio.CancelledError, GeneratorExit):
            elapsed = time.perf_counter() - t_start
            logger.debug(
                "[mock_llm] stream cancelled tokens_yielded=%d elapsed=%.3fs stream_id=%s",
                seq_id, elapsed, self.stream_id,
            )
            raise


def get_mock_llm(
    thread_id: str,
    timeout_secs: float,
    total_tokens: Optional[int] = None,
    stream_id: str = "",
) -> MockChatModel:
    """Return a configured :class:`MockChatModel` for *stream_id* / *thread_id*.

    Args:
        thread_id:    LangGraph thread UUID (used in token content).
        timeout_secs: Hard stream lifetime in seconds.
        total_tokens: Optional finite token budget.  When supplied the model
                      emits exactly this many tokens then stops.
        stream_id:    Celery ingest run UUID embedded in log messages.

    Returns:
        A ready-to-use :class:`MockChatModel` instance.
    """
    return MockChatModel(
        thread_id=thread_id,
        stream_id=stream_id,
        timeout_secs=timeout_secs,
        total_tokens=total_tokens,
    )
