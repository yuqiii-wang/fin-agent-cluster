"""Streaming lifecycle SSE notifications.

Emits lifecycle events after each phase transition via Redis Pub/Sub.
These are separate from the generic task lifecycle path because streaming
metrics are not stored in ``fin_agents.tasks``.
"""

from __future__ import annotations

import logging

from backend.sse_notifications.channel import publish_lifecycle

logger = logging.getLogger(__name__)


async def emit_ingest_complete(
    thread_id: str,
    stream_id: str,
    node_id: str,
    produced: int,
    stop_reason: str,
    ingest_ms: int,
) -> None:
    """Emit an ``ingest_complete`` event when the ingest phase finishes.

    Governance hierarchy: ``thread_id`` → ``node_id`` → ``stream_id``.
    Cancelling at a higher scope (thread or node) terminates all child streams.

    Args:
        thread_id:   LangGraph thread UUID (top-level governance scope).
        stream_id:   Streaming session UUID (leaf-level — this specific ingest run).
        node_id:     Sub-graph node execution UUID (mid-level governance scope).
        produced:    Tokens written to the Redis stream.
        stop_reason: ``"completed"``, ``"stable"``, or ``"timeout"``.
        ingest_ms:   Wall-clock milliseconds for the ingest phase.
    """
    await publish_lifecycle(
        thread_id,
        {
            "event": "ingest_complete",
            "stream_id": stream_id,
            "node_id": node_id,
            "produced": produced,
            "stop_reason": stop_reason,
            "ingest_ms": ingest_ms,
        },
    )
    logger.info(
        "[streamer] ingest_complete stream_id=%s node_id=%s produced=%d stop_reason=%s ingest_ms=%d thread_id=%s",
        stream_id, node_id, produced, stop_reason, ingest_ms, thread_id,
    )


async def emit_stream_stopped(
    thread_id: str,
    stream_id: str,
    node_id: str,
    duration_secs: int,
    total_published: int = 0,
    ingest_ms: int = 0,
) -> None:
    """Emit a ``stream_stopped`` event when the hard timeout fires.

    Governance hierarchy: ``thread_id`` → ``node_id`` → ``stream_id``.

    Args:
        thread_id:       LangGraph thread UUID (top-level governance scope).
        stream_id:       Streaming session UUID (leaf-level).
        node_id:         Sub-graph node execution UUID (mid-level governance scope).
        duration_secs:   Configured duration in seconds.
        total_published: Actual tokens published before timeout.
        ingest_ms:       Wall-clock milliseconds for the ingest phase.
    """
    await publish_lifecycle(
        thread_id,
        {
            "event": "stream_stopped",
            "stream_id": stream_id,
            "node_id": node_id,
            "duration_secs": duration_secs,
            "total_published": total_published,
            "ingest_ms": ingest_ms,
        },
    )
    logger.info(
        "[streamer] stream_stopped stream_id=%s node_id=%s duration_secs=%d total_published=%d ingest_ms=%d thread_id=%s",
        stream_id, node_id, duration_secs, total_published, ingest_ms, thread_id,
    )


async def emit_stream_complete(
    thread_id: str,
    stream_id: str,
    node_id: str,
    total_tokens: int,
    tps: float,
    ingest_ms: int = 0,
) -> None:
    """Emit a ``stream_complete`` event when all tokens are streamed.

    Governance hierarchy: ``thread_id`` → ``node_id`` → ``stream_id``.

    Args:
        thread_id:    LangGraph thread UUID (top-level governance scope).
        stream_id:    Streaming session UUID (leaf-level).
        node_id:      Sub-graph node execution UUID (mid-level governance scope).
        total_tokens: Number of tokens published.
        tps:          Tokens per second throughput.
        ingest_ms:    Wall-clock milliseconds for the ingest phase.
    """
    await publish_lifecycle(
        thread_id,
        {
            "event": "stream_complete",
            "stream_id": stream_id,
            "node_id": node_id,
            "total_tokens": total_tokens,
            "tps": tps,
            "ingest_ms": ingest_ms,
        },
    )
    logger.info(
        "[streamer] stream_complete stream_id=%s node_id=%s total_tokens=%d tps=%.2f ingest_ms=%d thread_id=%s",
        stream_id, node_id, total_tokens, tps, ingest_ms, thread_id,
    )
