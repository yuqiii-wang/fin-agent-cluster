"""Task completion lifecycle operations."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from backend.db.postgres import raw_conn
from backend.langgraph.lifecycle.threads.manager import get_thread_registry
from backend.langgraph.lifecycle.threads.nodes.tasks.sql import (
    _UPDATE_TASK_COMPLETED,
    _UPDATE_TASK_EXECUTION_OUTPUT,
)
from backend.langgraph.lifecycle.threads.nodes.tasks.sse import emit_task_sse
from backend.langgraph.models.task import get_task_cache_ttl

logger = logging.getLogger(__name__)


async def complete_task(
    thread_id: str,
    node_id: str,
    node_name: str,
    task_id: str,
    task_name: str,
    output_data: dict[str, Any] | None = None,
    *,
    view_type: str = "ToolCall",
    failed: bool = False,
    error: str | None = None,
) -> None:
    """Mark a task as completed (or failed) and emit the SSE event.

    Updates status in ``fin_agents.tasks`` and writes output payload to
    ``fin_agents.task_executions``.

    This function is **idempotent**: if the task is already in a terminal
    state (e.g. cancelled by the thread-cancel API), the UPDATE affects 0 rows
    and no SSE is emitted.

    Node completion is NOT triggered here.  The graph runner node function is
    responsible for calling ``complete_node`` once all its tasks have resolved.

    Args:
        thread_id:   LangGraph thread UUID.
        node_id:     Owning node ID.
        node_name:   Human-readable node name.
        task_id:     Task UUID to update.
        task_name:   Handler key for SSE payload.
        output_data: Extra fields merged into the error dict when *failed* is ``True``;
                     used as the result payload otherwise.
        view_type:   ``fin_agents.task_view_types`` value.
        failed:      ``True`` to mark as failed instead of completed.
        error:       Error message stored in output when *failed* is ``True``.
    """
    status = "failed" if failed else "completed"
    # Set cache TTL only on healthy completion so failed tasks are never cached.
    ttl = get_task_cache_ttl(task_name) if not failed else 0
    out: dict[str, Any] = {}
    if failed:
        out = {**(output_data or {}), "error": error or "unknown error"}
    elif output_data:
        out = output_data

    t0 = time.monotonic()
    async with raw_conn() as conn:
        cur = await conn.execute(
            _UPDATE_TASK_COMPLETED,
            (status, ttl, task_id, thread_id),
        )
        updated = cur.rowcount
        if updated > 0:
            await conn.execute(
                _UPDATE_TASK_EXECUTION_OUTPUT,
                (json.dumps(out), task_id, task_id),
            )

    get_thread_registry().discard_celery_result(task_id)

    if updated == 0:
        logger.debug(
            "[lifecycle:task] %s skipped task_id=%s task_name=%s — task already terminal",
            status, task_id, task_name,
        )
        return

    logger.debug(
        "[lifecycle:task] %s task_id=%s task_name=%s db_ms=%.0f — emitting SSE",
        status, task_id, task_name, (time.monotonic() - t0) * 1000,
    )
    t_sse = time.monotonic()
    await emit_task_sse(
        thread_id, task_id, task_name, node_id, node_name,
        status=status,
        payload={"output": out},
        view_type=view_type,
    )
    logger.debug(
        "[lifecycle:task] %s SSE done task_id=%s sse_ms=%.0f total_ms=%.0f",
        status, task_id, (time.monotonic() - t_sse) * 1000, (time.monotonic() - t0) * 1000,
    )


async def persist_task_result(
    thread_id: str,
    node_id: str,
    node_name: str,
    task_id: str,
    task_name: str,
    output_data: dict[str, Any] | None = None,
    *,
    failed: bool = False,
    error: str | None = None,
) -> bool:
    """Write the task terminal state to DB without emitting SSE.

    Called from the Celery worker for durability: the DB row reflects the
    terminal state even if the graph runner is interrupted before it can
    call the SSE path.  SSE is emitted by the graph runner after
    ``delegate_completion`` returns.

    Writes status to ``fin_agents.tasks`` and output to ``fin_agents.task_executions``.

    Args:
        thread_id:   LangGraph thread UUID.
        node_id:     Owning node ID.
        node_name:   Human-readable node name.
        task_id:     Task UUID to update.
        task_name:   Handler key (for logging only).
        output_data: Extra fields merged into the error dict when *failed* is ``True``;
                     used as the result payload otherwise.
        failed:      ``True`` to mark as failed instead of completed.
        error:       Error message stored in output when *failed* is ``True``.

    Returns:
        ``True`` if the row was updated (was in a non-terminal state);
        ``False`` if already terminal (idempotent no-op).
    """
    status = "failed" if failed else "completed"
    ttl = get_task_cache_ttl(task_name) if not failed else 0
    out: dict[str, Any] = {}
    if failed:
        out = {**(output_data or {}), "error": error or "unknown error"}
    elif output_data:
        out = output_data

    t0 = time.monotonic()
    async with raw_conn() as conn:
        cur = await conn.execute(
            _UPDATE_TASK_COMPLETED,
            (status, ttl, task_id, thread_id),
        )
        updated = cur.rowcount
        if updated > 0:
            await conn.execute(
                _UPDATE_TASK_EXECUTION_OUTPUT,
                (json.dumps(out), task_id, task_id),
            )

    get_thread_registry().discard_celery_result(task_id)

    logger.debug(
        "[lifecycle:task] persist_task_result %s task_id=%s task_name=%s node_name=%s updated=%s db_ms=%.0f",
        status, task_id, task_name, node_name, updated, (time.monotonic() - t0) * 1000,
    )
    return updated > 0


__all__ = ["complete_task", "persist_task_result"]
