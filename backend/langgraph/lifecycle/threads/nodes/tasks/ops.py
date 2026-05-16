"""Public API for task-level lifecycle operations."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from backend.db.postgres import raw_conn
from backend.langgraph.lifecycle.errors import (
    LIFECYCLE_DB_ERROR,
)
from backend.langgraph.lifecycle.threads.manager import get_thread_registry
from backend.langgraph.lifecycle.threads.nodes.tasks.sql import (
    _CANCEL_TASK,
    _CLEANUP_ZOMBIE_TASKS,
    _INSERT_TASK,
    _INSERT_TASK_EXECUTION,
    _UPDATE_TASK_COMPLETED,
    _UPDATE_TASK_EXECUTION_OUTPUT,
)
from backend.langgraph.lifecycle.threads.nodes.tasks.sse import emit_task_sse

logger = logging.getLogger(__name__)


async def create_task(
    thread_id: str,
    node_id: str,
    node_name: str,
    task_id: str,
    task_name: str,
    input_data: dict[str, Any],
) -> None:
    """Persist a new task row and emit a ``task_status: running`` SSE event.

    Writes task metadata to ``fin_agents.tasks`` and execution payload to
    ``fin_agents.task_executions`` in the same connection. Then calls
    ``append_node_task_id`` to record the task_id on the node row.

    Args:
        thread_id:  LangGraph thread UUID.
        node_id:    UUID5-derived owning node ID.
        node_name:  Human-readable node name.
        task_id:    Unique task UUID (from ``make_task_id``).
        task_name:  Handler key (e.g. ``"analyze_query"``).
        input_data: Serialisable input payload for the task.
    """
    from backend.langgraph.lifecycle.threads.nodes.ops import append_node_task_id
    from backend.main_thread.context import get_fencing_token

    fencing_token = get_fencing_token()
    t0 = time.monotonic()
    try:
        async with raw_conn() as conn:
            await conn.execute(
                _INSERT_TASK,
                (task_id, thread_id, node_id, node_name, task_name, fencing_token),
            )
            await conn.execute(
                _INSERT_TASK_EXECUTION,
                (task_id, json.dumps(input_data)),
            )
        await append_node_task_id(thread_id, node_id, task_id)
    except Exception as exc:
        logger.error(
            "[%s] create_task DB error task_id=%s thread_id=%s: %s",
            LIFECYCLE_DB_ERROR, task_id, thread_id, exc,
        )
        raise

    logger.debug(
        "[lifecycle:task] created task_id=%s task_name=%s node_name=%s db_ms=%.0f",
        task_id, task_name, node_name, (time.monotonic() - t0) * 1000,
    )
    t_sse = time.monotonic()
    await emit_task_sse(
        thread_id, task_id, task_name, node_id, node_name,
        status="running",
        payload={"input": input_data},
    )
    logger.debug(
        "[lifecycle:task] running SSE done task_id=%s sse_ms=%.0f",
        task_id, (time.monotonic() - t_sse) * 1000,
    )


async def complete_task(
    thread_id: str,
    node_id: str,
    node_name: str,
    task_id: str,
    task_name: str,
    output_data: dict[str, Any] | None = None,
    *,
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
        output_data: Result payload (ignored when *failed* is ``True``).
        failed:      ``True`` to mark as failed instead of completed.
        error:       Error message stored in output when *failed* is ``True``.
    """
    status = "failed" if failed else "completed"
    out: dict[str, Any] = {}
    if failed:
        out = {"error": error or "unknown error"}
    elif output_data:
        out = output_data

    t0 = time.monotonic()
    async with raw_conn() as conn:
        cur = await conn.execute(
            _UPDATE_TASK_COMPLETED,
            (status, task_id, thread_id),
        )
        updated = cur.rowcount
        if updated > 0:
            await conn.execute(
                _UPDATE_TASK_EXECUTION_OUTPUT,
                (json.dumps(out), task_id),
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
        output_data: Result payload (ignored when *failed* is ``True``).
        failed:      ``True`` to mark as failed instead of completed.
        error:       Error message stored in output when *failed* is ``True``.

    Returns:
        ``True`` if the row was updated (was in a non-terminal state);
        ``False`` if already terminal (idempotent no-op).
    """
    status = "failed" if failed else "completed"
    out: dict[str, Any] = {}
    if failed:
        out = {"error": error or "unknown error"}
    elif output_data:
        out = output_data

    t0 = time.monotonic()
    async with raw_conn() as conn:
        cur = await conn.execute(
            _UPDATE_TASK_COMPLETED,
            (status, task_id, thread_id),
        )
        updated = cur.rowcount
        if updated > 0:
            await conn.execute(
                _UPDATE_TASK_EXECUTION_OUTPUT,
                (json.dumps(out), task_id),
            )

    get_thread_registry().discard_celery_result(task_id)

    logger.debug(
        "[lifecycle:task] persist_task_result %s task_id=%s task_name=%s node_name=%s updated=%s db_ms=%.0f",
        status, task_id, task_name, node_name, updated, (time.monotonic() - t0) * 1000,
    )
    return updated > 0


async def cancel_task(
    thread_id: str,
    task_id: str,
    *,
    reason: str = "user",
) -> bool:
    """Cancel a single task: revoke its Celery job, persist, emit SSE.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task UUID to cancel.
        reason:    Human-readable cancellation reason (for logging).

    Returns:
        ``True`` if the task was in a non-terminal state and was cancelled;
        ``False`` if it was already terminal (no-op).
    """
    get_thread_registry().revoke_celery_task(task_id)

    async with raw_conn() as conn:
        cur = await conn.execute(_CANCEL_TASK, (task_id, thread_id))
        rows = await cur.fetchall()

    if not rows:
        return False

    row = rows[0]
    await emit_task_sse(
        thread_id,
        task_id,
        task_name=row["task_name"] or "",
        node_id=row["node_id"] or "",
        node_name=row["node_name"] or "",
        status="cancelled",
        payload={"reason": reason},
    )
    return True


async def cleanup_zombie_tasks(thread_id: str, fencing_token: int) -> None:
    """Mark all running tasks from a zombie graph run as 'wrong'.

    Called from the ``finally`` block of ``_run_graph`` when
    ``lock_lost_event`` is set.  Identifies the zombie's tasks by their
    ``fencing_token`` and transitions them to ``'wrong'`` so they do not
    remain ``'running'`` indefinitely.

    The ``'wrong'`` terminal status prevents Celery's ``persist_task_result``
    from later overwriting these rows (the update guard rejects writes to
    terminal rows).

    Args:
        thread_id:     LangGraph thread UUID.
        fencing_token: The zombie run's fencing token — only rows with this
                       exact token are updated.
    """
    try:
        async with raw_conn() as conn:
            cur = await conn.execute(_CLEANUP_ZOMBIE_TASKS, (thread_id, fencing_token))
            rows = await cur.fetchall()
        cleaned = len(rows)
        if cleaned:
            logger.error(
                "[lifecycle:task] cleanup_zombie_tasks marked %d task(s) as wrong "
                "thread_id=%s fencing_token=%d",
                cleaned, thread_id, fencing_token,
            )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[%s] cleanup_zombie_tasks failed thread_id=%s fencing_token=%d: %s",
            LIFECYCLE_DB_ERROR, thread_id, fencing_token, exc,
        )


__all__ = ["create_task", "complete_task", "persist_task_result", "cancel_task", "cleanup_zombie_tasks"]
