"""backend.langgraph.lifecycle.threads.nodes.tasks — task-level lifecycle.

Public API
----------
:func:`create_task`   — INSERT a task row (status=running); emit SSE.
:func:`complete_task` — UPDATE to completed/failed; emit SSE.
:func:`cancel_task`   — UPDATE to cancelled; revoke Celery job; emit SSE.

Every state transition persists to ``fin_agents.tasks`` **before** the
corresponding SSE event is published.  Callers on already-terminal tasks
receive a silent no-op (the conditional UPDATE affects 0 rows).

Node completion
---------------
Node-level DB writes are NOT performed here.  Once all tasks under a node
return in the graph runner's asyncio loop, the node function calls
``complete_node`` directly.  This eliminates the cross-process DB write that
caused the 30-second node-update lag.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from backend.db.postgres import raw_conn
from backend.langgraph.lifecycle.errors import (
    LIFECYCLE_CANCEL_FAILED,
    LIFECYCLE_DB_ERROR,
    ThreadCancelledError,
)
from backend.langgraph.lifecycle.threads.manager import get_thread_registry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL — all writes are conditional on non-terminal status to ensure
# idempotency when a cancel and a completion race each other.
# ---------------------------------------------------------------------------

_INSERT_TASK = """
    INSERT INTO fin_agents.tasks
        (task_id, thread_id, node_id, node_name, task_name, status, input,
         created_at, updated_at)
    VALUES (%s, %s, %s, %s, %s, 'running', %s::jsonb, NOW(), NOW())
    ON CONFLICT (task_id) DO NOTHING
"""

_UPDATE_TASK_COMPLETED = """
    UPDATE fin_agents.tasks
    SET status = %s,
        output = %s::jsonb,
        updated_at = NOW()
    WHERE task_id = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
"""

_CANCEL_TASK = """
    UPDATE fin_agents.tasks
    SET status = 'cancelled',
        updated_at = NOW()
    WHERE task_id = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING task_id
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_task(
    thread_id: str,
    node_id: str,
    node_name: str,
    task_id: str,
    task_name: str,
    input_data: dict[str, Any],
) -> None:
    """Persist a new task row and emit a ``task_status: running`` SSE event.

    Args:
        thread_id:  LangGraph thread UUID.
        node_id:    Owning node ID (from ``make_node_id``).
        node_name:  Human-readable node name.
        task_id:    Unique task UUID (from ``make_task_id``).
        task_name:  Handler key (e.g. ``"analyze_query"``).
        input_data: Serialisable input payload for the task.
    """
    t0 = time.monotonic()
    try:
        async with raw_conn() as conn:
            await conn.execute(
                _INSERT_TASK,
                (task_id, thread_id, node_id, node_name, task_name,
                 json.dumps(input_data)),
            )
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
    # SSE: persist first, then notify.
    t_sse = time.monotonic()
    await _emit_task_sse(
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
            (status, json.dumps(out), task_id, thread_id),
        )
        updated = cur.rowcount

    # Discard Celery result from registry (task is now terminal).
    get_thread_registry().discard_celery_result(task_id)

    if updated == 0:
        # Already terminal — skip SSE. Log as error: indicates a race or
        # double-processing (e.g. Celery worker + graph runner racing).
        logger.error(
            "[lifecycle:task] %s skipped task_id=%s task_name=%s — task already terminal",
            status, task_id, task_name,
        )
        return

    logger.debug(
        "[lifecycle:task] %s task_id=%s task_name=%s db_ms=%.0f — emitting SSE",
        status, task_id, task_name, (time.monotonic() - t0) * 1000,
    )
    t_sse = time.monotonic()
    await _emit_task_sse(
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
            (status, json.dumps(out), task_id, thread_id),
        )
        updated = cur.rowcount

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
    # Revoke the Celery job before writing to DB so that a worker that checks
    # the DB for a 'cancelled' flag will see the right state even if the
    # revoke signal races with its DB check.
    get_thread_registry().revoke_celery_task(task_id)

    async with raw_conn() as conn:
        cur = await conn.execute(_CANCEL_TASK, (task_id, thread_id))
        rows = await cur.fetchall()

    if not rows:
        # Already terminal.
        return False

    await _emit_task_sse(
        thread_id, task_id, task_name="",
        node_id="", node_name="",
        status="cancelled",
        payload={"reason": reason},
    )
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _emit_task_sse(
    thread_id: str,
    task_id: str,
    task_name: str,
    node_id: str,
    node_name: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    """Publish a ``task_status`` SSE event (fire-and-forget on error)."""
    try:
        from backend.centrifugo_mq.sse_notification.thread.node.task import notify
        await notify(
            thread_id=thread_id,
            task_id=task_id,
            event="task_status",
            payload={
                "status": status,
                "task_name": task_name,
                "node_id": node_id,
                "node_name": node_name,
                **payload,
            },
            dedup_key=f"task:{task_id}:{status}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[%s] task SSE publish failed task_id=%s status=%s: %s",
            "LC007", task_id, status, exc,
        )


__all__ = ["create_task", "complete_task", "persist_task_result", "cancel_task"]
