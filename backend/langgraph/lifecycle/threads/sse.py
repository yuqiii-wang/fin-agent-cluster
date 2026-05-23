"""Internal SSE helpers for thread-level lifecycle events."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def emit_thread_sse(
    thread_id: str,
    event: str,
    payload: dict[str, Any],
) -> None:
    """Publish a thread-scoped SSE event (fire-and-forget on error)."""
    try:
        from backend.centrifugo_mq.sse_notification.thread import notify
        from backend.langgraph.models import BaseThreadSseNotification
        notif = BaseThreadSseNotification(
            thread_id=thread_id,
            event=event,
            status=payload.get("status", ""),
            content={k: v for k, v in payload.items() if k != "status"},
        )
        logger.debug(
            "[lifecycle:thread] emitting thread SSE thread_id=%s event=%s",
            thread_id, event,
        )
        acked = await notify(
            thread_id=thread_id,
            event=notif.event,
            payload=notif.to_notify_payload(),
            dedup_key=f"thread:{event}:{notif.status}",
        )
        if not acked:
            logger.error(
                "[lifecycle:thread] thread SSE not acked thread_id=%s event=%s",
                thread_id, event,
            )
        else:
            logger.debug(
                "[lifecycle:thread] thread SSE acked thread_id=%s event=%s",
                thread_id, event,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[LC007] thread SSE publish failed thread_id=%s event=%s: %s",
            thread_id, event, exc,
        )


async def emit_node_sse(
    thread_id: str,
    node_id: str,
    node_name: str,
    reason: str,
) -> None:
    """Publish a ``node_status: cancelled`` SSE event (fire-and-forget)."""
    try:
        from backend.centrifugo_mq.sse_notification.thread.node import notify
        from backend.langgraph.models import BaseNodeSseNotification
        notif = BaseNodeSseNotification(
            thread_id=thread_id,
            node_id=node_id,
            node_name=node_name,
            event="node_status",
            status="cancelled",
            content={"reason": reason},
        )
        logger.debug(
            "[lifecycle:thread] emitting node cancelled SSE thread_id=%s node_id=%s",
            thread_id, node_id,
        )
        acked = await notify(
            thread_id=thread_id,
            node_id=node_id,
            event=notif.event,
            payload=notif.to_notify_payload(),
            dedup_key=f"node:{node_id}:cancelled",
        )
        if not acked:
            logger.error(
                "[lifecycle:thread] node cancelled SSE not acked thread_id=%s node_id=%s",
                thread_id, node_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[LC007] node SSE publish failed node_id=%s: %s",
            node_id, exc,
        )


async def emit_node_failed_sse(
    thread_id: str,
    node_id: str,
    node_name: str,
    error: str | None,
) -> None:
    """Publish a ``node_status: failed`` SSE event for an orphaned node (fire-and-forget)."""
    try:
        from backend.centrifugo_mq.sse_notification.thread.node import notify
        from backend.langgraph.models import BaseNodeSseNotification
        notif = BaseNodeSseNotification(
            thread_id=thread_id,
            node_id=node_id,
            node_name=node_name,
            event="node_status",
            status="failed",
            content={"error": error} if error else {},
        )
        acked = await notify(
            thread_id=thread_id,
            node_id=node_id,
            event=notif.event,
            payload=notif.to_notify_payload(),
            dedup_key=f"node:{node_id}:failed",
        )
        if not acked:
            logger.error(
                "[lifecycle:thread] node failed SSE not acked thread_id=%s node_id=%s",
                thread_id, node_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[LC007] node failed SSE publish failed node_id=%s: %s",
            node_id, exc,
        )


async def emit_task_cancelled_sse(
    thread_id: str,
    task_id: str,
    reason: str,
) -> None:
    """Publish a ``task_status: cancelled`` SSE event (fire-and-forget)."""
    try:
        from backend.centrifugo_mq.sse_notification.thread.node.task import notify
        from backend.langgraph.models import BaseTaskSseNotification
        notif = BaseTaskSseNotification(
            thread_id=thread_id,
            task_id=task_id,
            event="task_status",
            status="cancelled",
            content={"reason": reason},
        )
        logger.debug(
            "[lifecycle:thread] emitting task cancelled SSE thread_id=%s task_id=%s",
            thread_id, task_id,
        )
        acked = await notify(
            thread_id=thread_id,
            task_id=task_id,
            event=notif.event,
            payload=notif.to_notify_payload(),
            dedup_key=f"task:{task_id}:cancelled",
        )
        if not acked:
            logger.error(
                "[lifecycle:thread] task cancelled SSE not acked thread_id=%s task_id=%s",
                thread_id, task_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[LC007] task cancelled SSE failed task_id=%s: %s",
            task_id, exc,
        )


__all__ = ["emit_thread_sse", "emit_node_sse", "emit_task_cancelled_sse"]
