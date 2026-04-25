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
from collections import deque
from collections.abc import AsyncIterable

from langchain_core.messages import AIMessageChunk

from backend.db.redis.streams.publisher import stream_token
from backend.sse_notifications.agent_tasks.control import (
    TaskCancelledSignal,
    TaskPassSignal,
    _check_signal,
    _task_signals,
)
from backend.streaming.transmission_qos import transmission_qos

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


# Maximum tokens accumulated before emitting a ``perf_token_batch`` SSE event.
# The actual flush threshold grows exponentially (1 → 2 → 4 → … → _PERF_BATCH_SIZE)
# per stream so early tokens are flushed immediately and later batches are large.
_PERF_BATCH_SIZE: int = 1024


async def stream_perf_text_task(
    thread_id: str,
    task_id: int,
    task_key: str,
    chunks: AsyncIterable[str],
) -> int:
    """Consume a token stream and emit ``perf_token_batch`` events for silent metric aggregation.

    Tokens are accumulated in batches of :data:`_PERF_BATCH_SIZE` and flushed
    as a single ``perf_token_batch`` SSE event carrying a ``count`` field.  This
    reduces Redis XADD calls, SSE frames, and React state updates by
    ``_PERF_BATCH_SIZE``-fold compared to emitting one event per token.

    **First-token priority**: the very first token is always flushed immediately
    (batch_count == 1) so the client receives a signal as soon as data starts
    flowing, regardless of :data:`_PERF_BATCH_SIZE`.

    **Transmission QoS integration**: a :class:`~backend.streaming.transmission_qos.TransmissionQoS`
    flush event is monitored inside the accumulation loop.  If the QoS auditor
    detects that this stream has been running for ≥ 3 s without emitting a first
    token it sets the event, causing an immediate partial-batch flush.

    The backend SSE gateway always forwards ``perf_token_batch`` events (not
    filtered by the watch registry) so the frontend metrics panel counts them
    regardless of TaskDrawer state.

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
    batch_count = 0
    node = _node_name(task_key)
    first_token_marked = False

    # Exponential flush threshold: starts at 1 (first token flushed immediately),
    # then doubles after each flush — 1, 2, 4, 8, 16, … capped at _PERF_BATCH_SIZE.
    # This minimises first-token latency while amortising XADD overhead for later
    # tokens once the stream is flowing.
    flush_threshold: int = 1

    # Register with QoS registry; returns the flush-request event.
    flush_event = transmission_qos.register(thread_id)
    # Rolling window of the last 10 token strings across the full stream.
    # Snapshotted into ``recent_tokens`` on each batch flush so the browser
    # can display the most recently seen tokens without storing every token.
    token_window: deque[str] = deque(maxlen=10)

    try:
        while True:
            _check_signal(task_id, [])
            try:
                token = await aiter.__anext__()
            except StopAsyncIteration:
                break
            if token:
                token_window.append(token.strip())
                batch_count += 1
                received += 1

                # Flush when:
                #   1. Exponential threshold reached (covers first-token case when threshold=1).
                #   2. QoS auditor flagged this stream as stalled — flush partial immediately.
                should_flush = batch_count >= flush_threshold or flush_event.is_set()

                if should_flush:
                    await stream_token(
                        thread_id,
                        {
                            "event": "perf_token_batch",
                            "task_id": task_id,
                            "node_name": node,
                            "task_key": task_key,
                            "count": batch_count,
                            "recent_tokens": list(token_window),
                        },
                    )
                    batch_count = 0
                    flush_event.clear()
                    # Double the threshold after each flush, capped at _PERF_BATCH_SIZE.
                    flush_threshold = min(flush_threshold * 2, _PERF_BATCH_SIZE)
                    if not first_token_marked:
                        first_token_marked = True
                        transmission_qos.mark_first_token(thread_id)

        # Flush any remaining partial batch on normal completion.
        if batch_count > 0:
            await stream_token(
                thread_id,
                {
                    "event": "perf_token_batch",
                    "task_id": task_id,
                    "node_name": node,
                    "task_key": task_key,
                    "count": batch_count,
                    "recent_tokens": list(token_window),
                },
            )
    finally:
        transmission_qos.unregister(thread_id)
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
