"""Stream-level lifecycle SSE notifications.

Covers ephemeral streaming events at the leaf level of the scope hierarchy
(thread → node → task → stream).  These events are NOT persisted in PG DB;
timestamps are wall-clock values from the streaming worker.

All events carry the full 4-level governance hierarchy:
    thread_id → node_id → task_id → stream_id

Emitted events
--------------
``ingest_complete``  — ingest phase finished writing tokens to the Redis stream.
``stream_stopped``   — hard timeout fired before all tokens were streamed.
``stream_complete``  — all requested tokens were successfully streamed.
"""

from __future__ import annotations

import logging

from backend.sse_notifications.channel import publish_stream_lifecycle

logger = logging.getLogger(__name__)


async def emit_ingest_complete(
    thread_id: str,
    stream_id: str,
    node_id: str,
    task_id: str,
    produced: int,
    stop_reason: str,
    ingest_ms: int,
) -> None:
    """Emit an ``ingest_complete`` event when the ingest phase finishes.

    Governance hierarchy: ``thread_id`` → ``node_id`` → ``task_id`` → ``stream_id``.

    Args:
        thread_id:   LangGraph thread UUID (top-level governance scope).
        stream_id:   Streaming session UUID (leaf-level — this specific ingest run).
        node_id:     Node execution UUID.
        task_id:     Task invocation UUID (task-level governance scope).
        produced:    Tokens written to the Redis stream.
        stop_reason: ``"completed"``, ``"stable"``, or ``"timeout"``.
        ingest_ms:   Wall-clock milliseconds for the ingest phase.
    """
    await publish_stream_lifecycle(
        thread_id,
        {
            "event": "ingest_complete",
            "stream_id": stream_id,
            "node_id": node_id,
            "task_id": task_id,
            "produced": produced,
            "stop_reason": stop_reason,
            "ingest_ms": ingest_ms,
        },
    )
    logger.info(
        "[stream] ingest_complete stream_id=%s task_id=%s node_id=%s"
        " produced=%d stop_reason=%s ingest_ms=%d thread_id=%s",
        stream_id, task_id, node_id, produced, stop_reason, ingest_ms, thread_id,
    )


async def emit_stream_stopped(
    thread_id: str,
    stream_id: str,
    node_id: str,
    task_id: str,
    duration_secs: int,
    total_published: int = 0,
    ingest_ms: int = 0,
) -> None:
    """Emit a ``stream_stopped`` event when the hard timeout fires.

    Governance hierarchy: ``thread_id`` → ``node_id`` → ``task_id`` → ``stream_id``.

    Args:
        thread_id:       LangGraph thread UUID (top-level governance scope).
        stream_id:       Streaming session UUID (leaf-level).
        node_id:         Node execution UUID.
        task_id:         Task invocation UUID (task-level governance scope).
        duration_secs:   Configured duration in seconds.
        total_published: Actual tokens published before timeout.
        ingest_ms:       Wall-clock milliseconds for the ingest phase.
    """
    await publish_stream_lifecycle(
        thread_id,
        {
            "event": "stream_stopped",
            "stream_id": stream_id,
            "node_id": node_id,
            "task_id": task_id,
            "duration_secs": duration_secs,
            "total_published": total_published,
            "ingest_ms": ingest_ms,
        },
    )
    logger.info(
        "[stream] stream_stopped stream_id=%s task_id=%s node_id=%s"
        " duration_secs=%d total_published=%d ingest_ms=%d thread_id=%s",
        stream_id, task_id, node_id, duration_secs, total_published, ingest_ms, thread_id,
    )


async def emit_stream_complete(
    thread_id: str,
    stream_id: str,
    node_id: str,
    task_id: str,
    total_tokens: int,
    tps: float,
    ingest_ms: int = 0,
) -> None:
    """Emit a ``stream_complete`` event when all tokens are streamed.

    Governance hierarchy: ``thread_id`` → ``node_id`` → ``task_id`` → ``stream_id``.

    Args:
        thread_id:    LangGraph thread UUID (top-level governance scope).
        stream_id:    Streaming session UUID (leaf-level).
        node_id:      Node execution UUID.
        task_id:      Task invocation UUID (task-level governance scope).
        total_tokens: Total tokens delivered.
        tps:          Observed tokens-per-second.
        ingest_ms:    Wall-clock milliseconds for the ingest phase.
    """
    await publish_stream_lifecycle(
        thread_id,
        {
            "event": "stream_complete",
            "stream_id": stream_id,
            "node_id": node_id,
            "task_id": task_id,
            "total_tokens": total_tokens,
            "tps": round(tps, 2),
            "ingest_ms": ingest_ms,
        },
    )
    logger.info(
        "[stream] stream_complete stream_id=%s task_id=%s node_id=%s"
        " total_tokens=%d tps=%.2f ingest_ms=%d thread_id=%s",
        stream_id, task_id, node_id, total_tokens, tps, ingest_ms, thread_id,
    )


__all__ = [
    "emit_ingest_complete",
    "emit_stream_stopped",
    "emit_stream_complete",
]
