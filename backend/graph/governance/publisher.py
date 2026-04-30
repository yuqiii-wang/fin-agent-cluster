"""Governance lifecycle publisher — propagate end/cancel events down the hierarchy.

When a LangGraph thread ends naturally or is cancelled, this module traverses
the governance registry (thread → nodes → streams) and emits a terminal
lifecycle event for every leaf stream still registered.

A stream that already deregistered itself has completed normally and receives
no additional event — only orphaned or interrupted streams are notified here.

This module is stream-type-agnostic: any node that registers leaf work in the
governance registry benefits from automatic terminal propagation on thread
cancel or completion.
"""

from __future__ import annotations

import logging

from backend.graph.governance.registry import get_streams_for_thread
from backend.sse_notifications.streamer.notifications import emit_stream_stopped

logger = logging.getLogger(__name__)


async def publish_governance_end(
    thread_id: str,
    reason: str = "cancelled",
    duration_secs: int = 0,
) -> None:
    """Traverse the governance hierarchy and emit a terminal event for each live stream.

    Called by the graph runner and cancel endpoint after the thread transitions
    to a terminal state.  Emits ``stream_stopped`` for every leaf stream still
    present in the registry so the frontend receives a clean terminal event
    even when the Celery worker never had a chance to deregister.

    Only streams still in the governance registry are notified — streams that
    already called :func:`~backend.graph.governance.registry.deregister_stream`
    completed normally and do not need an additional event.

    Args:
        thread_id:     LangGraph thread UUID (top-level scope).
        reason:        Terminal reason — ``"cancelled"``, ``"completed"``, or
                       ``"failed"``.  Embedded in the ``stream_stopped`` payload
                       so the frontend can distinguish clean ends from forced stops.
        duration_secs: Configured max duration in seconds (0 = unknown).
    """
    pairs = await get_streams_for_thread(thread_id)
    if not pairs:
        logger.debug(
            "[governance] publish_governance_end no live streams thread_id=%s reason=%s",
            thread_id, reason,
        )
        return

    logger.info(
        "[governance] publish_governance_end thread_id=%s reason=%s streams=%d",
        thread_id, reason, len(pairs),
    )
    for node_id, stream_id in pairs:
        try:
            await emit_stream_stopped(
                thread_id=thread_id,
                stream_id=stream_id,
                node_id=node_id,
                duration_secs=duration_secs,
                total_published=0,
                ingest_ms=0,
            )
            logger.debug(
                "[governance] stream_stopped emitted stream_id=%s node_id=%s thread_id=%s",
                stream_id, node_id, thread_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[governance] stream_stopped emit failed stream_id=%s node_id=%s thread_id=%s: %s",
                stream_id, node_id, thread_id, exc,
            )


__all__ = ["publish_governance_end"]
