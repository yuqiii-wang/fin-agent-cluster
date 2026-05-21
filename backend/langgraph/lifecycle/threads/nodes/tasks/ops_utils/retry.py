"""Task retry lifecycle operation."""

from __future__ import annotations

import logging
import time
from typing import Any

from backend.db.postgres import raw_conn
from backend.langgraph.lifecycle.threads.nodes.tasks.sql import (
    _INSERT_RETRY_TASK_EXECUTION,
    _RESET_TASK_FOR_RETRY,
)
from backend.langgraph.lifecycle.threads.nodes.tasks.sse import emit_task_sse

logger = logging.getLogger(__name__)


async def reset_task_for_retry(
    thread_id: str,
    task_id: str,
) -> dict[str, Any] | None:
    """Reset a terminal task to 'running' in preparation for retry.

    Transitions completed / failed / cancelled → running.  Clears the
    previous output from ``task_executions`` so the retry starts clean.
    Emits a ``task_status: running`` SSE event on success.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task UUID to reset.

    Returns:
        Dict with ``task_id``, ``task_name``, ``node_id``, ``node_name``,
        ``view_type``, ``stats_views`` from the DB row, or ``None`` when the
        task was not found or was already in a non-terminal state.
    """
    t0 = time.monotonic()
    async with raw_conn() as conn:
        cur = await conn.execute(_RESET_TASK_FOR_RETRY, (task_id, thread_id))
        row = await cur.fetchone()
        if row:
            await conn.execute(_INSERT_RETRY_TASK_EXECUTION, (task_id,))

    if row is None:
        return None

    result: dict[str, Any] = dict(row)
    stats_views: list[str] = list(row["stats_views"] or [])
    view_type: str = row["view_type"] or "ToolCall"

    logger.debug(
        "[lifecycle:task] reset_task_for_retry task_id=%s task_name=%s db_ms=%.0f",
        task_id, row["task_name"], (time.monotonic() - t0) * 1000,
    )
    await emit_task_sse(
        thread_id, task_id, row["task_name"], row["node_id"] or "", row["node_name"] or "",
        status="running",
        payload={},
        view_type=view_type,
        stats_views=stats_views,
    )
    return result


__all__ = ["reset_task_for_retry"]
