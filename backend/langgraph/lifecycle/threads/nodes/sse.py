"""Internal SSE helpers for node-level lifecycle events."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def emit_node_sse(
    thread_id: str,
    node_id: str,
    node_name: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    """Publish a ``node_status`` SSE event (fire-and-forget on error)."""
    try:
        from backend.centrifugo_mq.sse_notification.thread.node import notify
        from backend.langgraph.models import BaseNodeSseNotification
        notif = BaseNodeSseNotification(
            thread_id=thread_id,
            node_id=node_id,
            node_name=node_name,
            event="node_status",
            status=status,
            content=payload,
        )
        await notify(
            thread_id=thread_id,
            node_id=node_id,
            event=notif.event,
            payload=notif.to_notify_payload(),
            dedup_key=f"node:{node_id}:{status}",
            # All node lifecycle events are informational — do not block the graph
            # waiting for ack.  Blocking caused delays when frontend failed to ack.
            require_ack=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[%s] node SSE publish failed node_id=%s status=%s: %s",
            "LC007", node_id, status, exc,
        )


async def emit_task_cancelled_sse(
    thread_id: str,
    task_id: str,
    task_name: str,
    node_name: str,
    reason: str,
) -> None:
    """Publish a ``task_status: cancelled`` SSE event (fire-and-forget)."""
    try:
        from backend.centrifugo_mq.sse_notification.thread.node.task import notify
        from backend.langgraph.models import BaseTaskSseNotification
        notif = BaseTaskSseNotification(
            thread_id=thread_id,
            task_id=task_id,
            task_name=task_name,
            node_name=node_name,
            event="task_status",
            status="cancelled",
            content={"reason": reason},
        )
        await notify(
            thread_id=thread_id,
            task_id=task_id,
            event=notif.event,
            payload=notif.to_notify_payload(),
            dedup_key=f"task:{task_id}:cancelled",
            require_ack=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[%s] task cancelled SSE failed task_id=%s: %s",
            "LC007", task_id, exc,
        )


__all__ = ["emit_node_sse", "emit_task_cancelled_sse"]
