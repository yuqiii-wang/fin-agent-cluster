"""backend.sse_notifications.thread.node.task.stream — stream-complete SSE emitter.

Called by :mod:`backend.centrifugo_mq.rpc_proxy` once all token-batch ACKs
have been received, to publish the terminal ``stream_complete`` event to the
frontend via Centrifugo.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.centrifugo_mq.client import publish_task_event

logger = logging.getLogger(__name__)


async def emit_stream_complete(
    *,
    thread_id: str,
    stream_id: str,
    node_id: str,
    task_id: str,
    total_tokens: int,
    tps: float,
    total_batches: int,
    ingest_ms: int = 0,
) -> None:
    """Publish a ``stream_complete`` event for a finished token stream.

    Called exactly once per stream (enforced by the emit-slot mechanism in
    :mod:`backend.db.redis.session.stream_batch_ack_store`).

    Args:
        thread_id:     LangGraph thread UUID.
        stream_id:     Celery ingest run UUID.
        node_id:       Owning node UUID.
        task_id:       Task governance UUID.
        total_tokens:  Total tokens emitted by the stream.
        tps:           Tokens-per-second throughput measured by the worker.
        total_batches: Number of token batches published.
        ingest_ms:     Total ingest duration in milliseconds.
    """
    payload: dict[str, Any] = {
        "event": "stream_complete",
        "stream_id": stream_id,
        "node_id": node_id,
        "task_id": task_id,
        "total_tokens": total_tokens,
        "tps": tps,
        "total_batches": total_batches,
        "ingest_ms": ingest_ms,
    }
    try:
        await publish_task_event(thread_id, payload)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[sse_notifications] emit_stream_complete failed thread_id=%s stream_id=%s: %s",
            thread_id, stream_id, exc,
        )


__all__ = ["emit_stream_complete"]
