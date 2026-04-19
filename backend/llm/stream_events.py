"""LLM completion event publisher for Redis Streams.

Provides a fire-and-forget coroutine that publishes token usage and latency
records to ``fin:llm:completions`` after each LLM invocation.  The publish
is non-fatal: if Redis is unavailable the error is logged and silently swallowed
so the main inference path is never blocked.

Usage
-----
Call :func:`publish_completion` from any agent node that invokes the LLM,
or attach :class:`LLMStreamCallbackHandler` to a ``BaseChatModel`` via
``model.with_config(callbacks=[handler])``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from backend.streaming.schemas import LLMCompletionMessage
from backend.streaming.streams import STREAM_LLM_COMPLETIONS, xadd

logger = logging.getLogger(__name__)


async def publish_completion(
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_ms: int = 0,
    thread_id: Optional[str] = None,
    task_key: Optional[str] = None,
    node_name: Optional[str] = None,
) -> None:
    """Publish a single LLM completion record to ``fin:llm:completions``.

    Best-effort — never raises.  Callers should fire-and-forget with
    ``asyncio.ensure_future(publish_completion(...))``.

    Args:
        provider:          LLM provider name (e.g. ``'ollama'``, ``'ark'``).
        model:             Model identifier (e.g. ``'qwen3.5-27b'``).
        prompt_tokens:     Input token count from the completion metadata.
        completion_tokens: Output token count.
        latency_ms:        Wall-clock latency from request to response.
        thread_id:         Originating LangGraph thread UUID.
        task_key:          Agent sub-task key.
        node_name:         Agent node name.
    """
    msg = LLMCompletionMessage(
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        latency_ms=latency_ms,
        thread_id=thread_id,
        task_key=task_key,
        node_name=node_name,
    )
    try:
        await xadd(STREAM_LLM_COMPLETIONS, msg.model_dump())
    except Exception as exc:
        logger.debug("[llm.stream_events] publish failed: %s", exc)


class LLMStreamCallbackHandler(AsyncCallbackHandler):
    """LangChain async callback that publishes completion metrics to Redis Streams.

    Attach to any ``BaseChatModel`` instance::

        from backend.llm.stream_events import LLMStreamCallbackHandler

        handler = LLMStreamCallbackHandler(
            provider="ollama",
            model="qwen3.5-27b",
            thread_id=thread_id,
            node_name="decision_maker",
        )
        result = await llm.with_config(callbacks=[handler]).ainvoke(messages)

    The callback records the wall-clock start time on ``on_llm_start`` and
    computes latency on ``on_llm_end`` before publishing.

    Attributes:
        provider:   LLM provider name.
        model:      Model identifier.
        thread_id:  Originating LangGraph thread.
        node_name:  Agent node attaching this handler.
        task_key:   Agent sub-task key (optional).
    """

    def __init__(
        self,
        provider: str,
        model: str,
        thread_id: Optional[str] = None,
        node_name: Optional[str] = None,
        task_key: Optional[str] = None,
    ) -> None:
        """Initialise the handler with context metadata.

        Args:
            provider:   LLM provider name.
            model:      Model identifier.
            thread_id:  Originating LangGraph thread UUID string.
            node_name:  Agent node name.
            task_key:   Agent sub-task key.
        """
        super().__init__()
        self._provider = provider
        self._model = model
        self._thread_id = thread_id
        self._node_name = node_name
        self._task_key = task_key
        self._start_ns: int = 0

    async def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Record the start timestamp for latency computation.

        Args:
            serialized: Serialized LLM config (unused).
            prompts:    Input prompt strings (unused).
            run_id:     LangChain run UUID (unused).
        """
        self._start_ns = time.monotonic_ns()

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Publish completion metrics when the LLM finishes.

        Extracts token usage from ``response.llm_output`` if available
        (OpenAI / Ollama return ``usage`` metadata there).

        Args:
            response: LangChain :class:`~langchain_core.outputs.LLMResult`.
            run_id:   LangChain run UUID (unused).
        """
        latency_ms = (time.monotonic_ns() - self._start_ns) // 1_000_000

        prompt_tokens = 0
        completion_tokens = 0
        llm_output: dict[str, Any] = response.llm_output or {}
        usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))

        await publish_completion(
            provider=self._provider,
            model=self._model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            thread_id=self._thread_id,
            task_key=self._task_key,
            node_name=self._node_name,
        )
