"""Internal SSE helper for task-level lifecycle events."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def emit_task_sse(
    thread_id: str,
    task_id: str,
    task_name: str,
    node_id: str,
    node_name: str,
    status: str,
    payload: dict[str, Any],
    view_type: str = "ToolCall",
    stats_views: list[str] | None = None,
) -> None:
    """Publish a ``task_status`` SSE event (fire-and-forget on error)."""
    try:
        from backend.centrifugo_mq.sse_notification.thread.node.task import notify
        from backend.langgraph.models import BaseTaskSseNotification
        notif = BaseTaskSseNotification(
            thread_id=thread_id,
            task_id=task_id,
            task_name=task_name,
            view_type=view_type,
            stats_views=stats_views or [],
            node_id=node_id,
            node_name=node_name,
            event="task_status",
            status=status,
            content=payload,
        )
        await notify(
            thread_id=thread_id,
            task_id=task_id,
            event=notif.event,
            payload=notif.to_notify_payload(),
            dedup_key=f"task:{task_id}:{status}",
            # All task lifecycle events are informational -- do not block the graph
            # waiting for ack.  Blocking here caused 30s delays between tasks when
            # the frontend failed to ack (CENTRIFUGO_003 exhausted).
            require_ack=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[%s] task SSE publish failed task_id=%s status=%s: %s",
            "LC007", task_id, status, exc,
        )


__all__ = ["emit_task_sse"]
