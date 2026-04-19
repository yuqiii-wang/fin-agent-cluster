"""Token streaming — Redis Streams token publishing for live LLM output.

These helpers consume async iterables of LLM tokens or text chunks and
publish each non-empty token to Redis Streams (``XADD tokens:<thread_id>``).
They do **not** write to the database — token events are intentionally
ephemeral and high-frequency.

Lifecycle events (started / completed / failed / cancelled / done) are handled
by :mod:`backend.sse_notifications.agent_tasks.lifecycle`.

Control signals (cancel / pass) are checked before each token via
:func:`backend.sse_notifications.agent_tasks.control._check_signal`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterable

from langchain_core.messages import AIMessageChunk

from backend.db.redis.publisher import stream_token
from backend.sse_notifications.agent_tasks.control import (
    TaskCancelledSignal,
    TaskPassSignal,
    _check_signal,
    _task_signals,
)

logger = logging.getLogger(__name__)


def _node_name(task_key: str) -> str:
    """Extract the agent node name from a dot-separated task key.

    Args:
        task_key: Full task key, e.g. ``"market_data_collector.ohlcv.15min"``.

    Returns:
        First dot-separated segment.
    """
    return task_key.split(".")[0]


async def stream_llm_task(
    thread_id: str,
    task_id: int,
    task_key: str,
    chunks: AsyncIterable[AIMessageChunk],
) -> str:
    """Consume an LLM async-stream, publish ``token`` events, return full text.

    Each non-empty token in *chunks* is forwarded via Redis Streams without a
    DB write for maximum throughput.  Only the final :func:`complete_task`
    call persists text.

    On ``asyncio.CancelledError`` the upstream async generator is explicitly
    closed so the HTTP connection to Ollama is torn down immediately, freeing
    the GPU slot before re-raising.

    On :class:`~backend.sse_notifications.agent_tasks.control.TaskCancelledSignal`
    or :class:`~backend.sse_notifications.agent_tasks.control.TaskPassSignal` the
    loop exits early and re-raises so the caller can mark the task status.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key of the running task.
        task_key:  Full dot-separated task key.
        chunks:    Async iterable of LangChain ``AIMessageChunk`` objects.

    Returns:
        Fully assembled response text.
    """
    parts: list[str] = []
    aiter = chunks.__aiter__()
    try:
        while True:
            _check_signal(task_id, parts)
            try:
                chunk = await aiter.__anext__()
            except StopAsyncIteration:
                break
            token: str = chunk.content  # type: ignore[assignment]
            if token:
                parts.append(token)
                await stream_token(
                    thread_id,
                    {
                        "event": "token",
                        "task_id": task_id,
                        "node_name": _node_name(task_key),
                        "task_key": task_key,
                        "data": token,
                    },
                )
    finally:
        _task_signals.pop(task_id, None)
        aclose = getattr(aiter, "aclose", None)
        if aclose is not None:
            try:
                await asyncio.shield(aclose())
            except Exception:  # noqa: BLE001
                pass
    return "".join(parts)


async def stream_text_task(
    thread_id: str,
    task_id: int,
    task_key: str,
    chunks: AsyncIterable[str],
) -> str:
    """Consume a plain-text async-stream, publish ``token`` events, return full text.

    Identical to :func:`stream_llm_task` but accepts ``str`` chunks (e.g.
    from a chain that includes ``StrOutputParser``).

    On ``asyncio.CancelledError`` the upstream async generator is explicitly
    closed so the HTTP connection to Ollama is torn down immediately, freeing
    the GPU slot before re-raising.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key of the running task.
        task_key:  Full dot-separated task key.
        chunks:    Async iterable of plain string tokens.

    Returns:
        Fully assembled response text.
    """
    parts: list[str] = []
    aiter = chunks.__aiter__()
    tokens_published = 0
    total_publish_ms = 0.0
    t_start = time.perf_counter()
    try:
        while True:
            _check_signal(task_id, parts)
            try:
                token = await aiter.__anext__()
            except StopAsyncIteration:
                break
            if token:
                parts.append(token)
                t_pub = time.perf_counter()
                await stream_token(
                    thread_id,
                    {
                        "event": "token",
                        "task_id": task_id,
                        "node_name": _node_name(task_key),
                        "task_key": task_key,
                        "data": token,
                    },
                )
                pub_ms = (time.perf_counter() - t_pub) * 1000
                tokens_published += 1
                total_publish_ms += pub_ms
                if pub_ms > 20:
                    logger.warning(
                        "[token_stream] slow_publish pub_ms=%.1f token#=%d "
                        "task_key=%s thread_id=%s",
                        pub_ms,
                        tokens_published,
                        task_key,
                        thread_id,
                    )
    finally:
        _task_signals.pop(task_id, None)
        aclose = getattr(aiter, "aclose", None)
        if aclose is not None:
            try:
                await asyncio.shield(aclose())
            except Exception:  # noqa: BLE001
                pass
    if tokens_published:
        elapsed = time.perf_counter() - t_start
        logger.info(
            "[token_stream] stream_finished tokens=%d avg_pub_ms=%.2f "
            "tps=%.1f task_key=%s thread_id=%s",
            tokens_published,
            total_publish_ms / tokens_published,
            tokens_published / max(elapsed, 0.001),
            task_key,
            thread_id,
        )
    return "".join(parts)


async def stream_perf_text_task(
    thread_id: str,
    task_id: int,
    task_key: str,
    chunks: AsyncIterable[str],
) -> int:
    """Consume a token stream and emit ``perf_token`` events for silent metric aggregation.

    Unlike :func:`stream_text_task`, events emitted here use the ``perf_token``
    SSE type.  The backend SSE gateway forwards ``perf_token`` events without
    consulting the ``_watch_registry``, so they always reach the frontend regardless
    of whether the TaskDrawer is open.  The frontend metrics panel counts them
    without displaying them as task output text.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key of the running task.
        task_key:  Full dot-separated task key.
        chunks:    Async iterable of plain token strings.

    Returns:
        Total number of tokens received.
    """
    received = 0
    t_start = time.perf_counter()
    aiter = chunks.__aiter__()
    try:
        while True:
            _check_signal(task_id, [])
            try:
                token = await aiter.__anext__()
            except StopAsyncIteration:
                break
            if token:
                received += 1
                await stream_token(
                    thread_id,
                    {
                        "event": "perf_token",
                        "task_id": task_id,
                        "node_name": _node_name(task_key),
                        "task_key": task_key,
                        "data": token,
                    },
                )
    finally:
        _task_signals.pop(task_id, None)
        aclose = getattr(aiter, "aclose", None)
        if aclose is not None:
            try:
                await asyncio.shield(aclose())
            except Exception:  # noqa: BLE001
                pass

    elapsed = time.perf_counter() - t_start
    logger.info(
        "[token_stream] perf_stream_finished received=%d tps=%.1f task_key=%s thread_id=%s",
        received,
        received / max(elapsed, 0.001),
        task_key,
        thread_id,
    )
    return received


__all__ = [
    "stream_llm_task",
    "stream_text_task",
    "stream_perf_text_task",
]
