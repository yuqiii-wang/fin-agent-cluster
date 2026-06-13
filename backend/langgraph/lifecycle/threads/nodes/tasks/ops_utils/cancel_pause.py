"""Task cancel, pause, and zombie-cleanup lifecycle operations."""

from __future__ import annotations

import logging
from typing import Any

from backend.db.postgres import raw_conn
from backend.langgraph.lifecycle.errors import LIFECYCLE_DB_ERROR
from backend.langgraph.lifecycle.threads.manager import get_thread_registry
from backend.langgraph.lifecycle.threads.nodes.tasks.sql import (
    _CANCEL_TASK,
    _CLEANUP_ZOMBIE_TASKS,
    _PAUSE_TASK,
)
from backend.langgraph.lifecycle.threads.nodes.tasks.sse import emit_task_sse

logger = logging.getLogger(__name__)


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


async def pause_task(
    thread_id: str,
    task_id: str,
    *,
    reason: str = "user",
) -> bool:
    """Pause a single task: mark DB as 'pause' and emit SSE.

    Unlike :func:`cancel_task`, pausing does **not** cascade to the owning
    node -- the node stays ``running`` and the task can be retried later.
    For streaming tasks the Celery worker is also signalled via a Redis
    pause flag (set by the caller before invoking this function) so it can
    save its partial thinking content gracefully before exiting.  The
    caller (:func:`~backend.users.queries.lifecycle.pause_task_by_uuid`) is
    responsible for revoking the Celery task when needed (completion tasks
    only) -- this function only updates the DB and emits the SSE.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task UUID to pause.
        reason:    Human-readable pause reason (for logging).

    Returns:
        ``True`` if the task transitioned to ``pause``;
        ``False`` if already terminal (idempotent no-op).
    """
    async with raw_conn() as conn:
        cur = await conn.execute(_PAUSE_TASK, (task_id, thread_id))
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
        status="paused",
        payload={"reason": reason},
    )

    # Check whether this was a user-initiated pause (not server shutdown).
    # When reason != "server_shutdown", we mark the node as user-paused so that
    # the startup recovery won't auto-resume it -- the user must click Continue.
    # We do NOT call pause_node here directly; that happens when TaskPausedError
    # propagates to node.__call__ or _run_as_child after the stream worker stops.
    # However, we do mark the node's is_last_paused_by_server=FALSE now so that
    # the flag is correct even if the node update from __call__ races with this.
    if reason != "server_shutdown" and row["node_id"]:
        from backend.langgraph.lifecycle.threads.nodes.ops import pause_node  # noqa: PLC0415
        node_id: str = row["node_id"]
        node_name: str = row["node_name"] or ""
        await pause_node(
            thread_id, node_id, node_name,
            is_last_paused_by_server=False,
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
        fencing_token: The zombie run's fencing token -- only rows with this
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


__all__ = ["cancel_task", "pause_task", "cleanup_zombie_tasks"]
