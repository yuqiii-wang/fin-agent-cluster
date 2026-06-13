"""Public API for thread-level lifecycle operations."""

from __future__ import annotations

import asyncio
import logging
import time

from backend.db.postgres import raw_conn
from backend.langgraph.lifecycle.errors import (
    LIFECYCLE_CANCEL_FAILED,
    LIFECYCLE_DB_ERROR,
)
from backend.langgraph.lifecycle.threads.manager import (
    get_thread_registry,
)
from backend.langgraph.lifecycle.threads.sql import (
    _CANCEL_ACTIVE_NODES,
    _CANCEL_ACTIVE_TASKS_BY_THREAD,
    _FAIL_ACTIVE_NODES,
    _LATEST_TERMINAL_LEAF_STATUS,
    _LIST_ACTIVE_THREAD_IDS,
    _UPDATE_THREAD_COMPLETED,
    _UPDATE_THREAD_STATUS,
)
from backend.langgraph.lifecycle.threads.sse import (
    emit_node_failed_sse,
    emit_node_sse,
    emit_task_cancelled_sse,
    emit_thread_sse,
)

logger = logging.getLogger(__name__)


def register_thread(thread_id: str) -> asyncio.Event:
    """Register *thread_id* in the process-local cancel registry.

    Must be called once per thread before the LangGraph graph starts executing
    so that ``get_cancel_token`` and ``is_thread_cancelled`` work correctly
    inside task delegation.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        The cancel token (``asyncio.Event``) for this thread.
    """
    return get_thread_registry().register_thread(thread_id)


def get_cancel_token(thread_id: str) -> asyncio.Event | None:
    """Return the cancel token for *thread_id*, or ``None`` if not registered."""
    return get_thread_registry().get_cancel_token(thread_id)


def is_thread_cancelled(thread_id: str) -> bool:
    """Return ``True`` if the thread's cancel token has been set."""
    return get_thread_registry().is_cancelled(thread_id)


async def complete_thread(
    thread_id: str,
    answer: str | None = None,
    *,
    failed: bool = False,
    error: str | None = None,
) -> None:
    """Mark the thread as completed (or failed) and emit the SSE done event.

    Persists to ``fin_agents.user_queries`` before emitting SSE.  Idempotent
    on already-terminal threads.

    On normal completion (``failed=False``) the thread status is aligned to the
    terminal status of the last end-of-lifecycle node (the leaf node with no
    successors) in the **latest version** -- so a thread whose final node ended
    ``failed`` / ``cancelled`` / ``wrong`` is reflected accurately instead of
    being reported as ``completed``.

    Args:
        thread_id: LangGraph thread UUID.
        answer:    Final answer text (for completed threads).
        failed:    ``True`` to mark as failed.
        error:     Error message stored in ``user_queries.error``.
    """
    if failed:
        status = "failed"
    else:
        # Align thread status with the latest version's last end-of-lifecycle
        # node.  Defaults to 'completed' when no terminal leaf node is found.
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(_LATEST_TERMINAL_LEAF_STATUS, (thread_id,))
            leaf_row = await cur.fetchone()
        status = leaf_row["status"] if leaf_row else "completed"

    async with raw_conn() as conn:
        cur = await conn.execute(
            _UPDATE_THREAD_COMPLETED,
            (status, answer, error, thread_id),
        )
        rows = await cur.fetchall()

    if not rows:
        return  # Already terminal.

    get_thread_registry().cleanup_thread(thread_id)

    if failed:
        # Sweep any nodes still active -- complete_node may have been skipped
        # (e.g. fencing-token mismatch). Leaving them as 'running' creates a
        # permanently stuck state visible to the user.
        async with raw_conn() as conn:
            cur = await conn.execute(_FAIL_ACTIVE_NODES, (thread_id,))
            orphaned_nodes = await cur.fetchall()
        for row in orphaned_nodes:
            logger.error(
                "[lifecycle:thread] orphaned node force-failed thread_id=%s node_id=%s node_name=%s",
                thread_id, row["node_id"], row["node_name"],
            )
            await emit_node_failed_sse(thread_id, row["node_id"], row["node_name"], error)

    event = "done" if not failed else "thread_failed"
    logger.debug(
        "[lifecycle:thread] %s thread_id=%s -- emitting SSE event=%s",
        status, thread_id, event,
    )
    t_sse = time.monotonic()
    await emit_thread_sse(
        thread_id,
        event=event,
        payload={"status": status, "error": error} if failed else {"status": status},
    )
    logger.debug(
        "[lifecycle:thread] %s SSE done thread_id=%s sse_ms=%.0f",
        status, thread_id, (time.monotonic() - t_sse) * 1000,
    )


async def cancel_thread(
    thread_id: str,
    *,
    reason: str = "user",
) -> bool:
    """Cancel a thread and cascade to all its active nodes and tasks.

    Cascade order
    -------------
    0. Set Redis cancel flag so ``_await_result`` polling loops exit within
       0.5 s, regardless of the DB status check result below.  Done first so
       that Celery delegation unblocks even for threads whose DB status is
       already terminal (e.g. a completed thread whose task is being retried).
    1. Revoke all in-flight Celery tasks tracked for this thread.
    2. Batch-UPDATE active tasks to ``cancelled`` (RETURNING task_ids).
    3. Batch-UPDATE active nodes to ``cancelled`` (RETURNING node rows).
    4. UPDATE the thread itself to ``cancelled``.
    5. Set the process-local cancel token so polling delegation loops exit.
    6. Emit SSE: task cancelled -> node cancelled -> thread cancelled.

    All DB writes precede the corresponding SSE events.

    Args:
        thread_id: LangGraph thread UUID.
        reason:    Human-readable reason (``"user"``, ``"shutdown"``, ...).

    Returns:
        ``True`` if the thread was active and has been cancelled;
        ``False`` if it was already terminal.
    """
    # ------------------------------------------------------------------
    # 0. Set Redis cancel flag immediately -- unblocks _await_result within
    #    one poll cycle (0.5 s) regardless of the DB status below.
    # ------------------------------------------------------------------
    try:
        from backend.langgraph.lifecycle.cancel_flag import set_cancel_flag
        await set_cancel_flag(thread_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[%s] cancel_thread set_cancel_flag failed thread_id=%s: %s",
            LIFECYCLE_CANCEL_FAILED, thread_id, exc,
        )

    # ------------------------------------------------------------------
    # 1. Revoke all in-flight Celery tasks before touching DB.
    # ------------------------------------------------------------------
    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(
                "SELECT task_id FROM fin_agents.tasks "
                "WHERE thread_id = %s "
                "AND status NOT IN ('completed','failed','cancelled','wrong')",
                (thread_id,),
            )
            active_task_ids = [r["task_id"] for r in await cur.fetchall()]

        registry = get_thread_registry()
        for tid in active_task_ids:
            registry.revoke_celery_task(tid)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[%s] cancel_thread revoke failed thread_id=%s: %s",
            LIFECYCLE_CANCEL_FAILED, thread_id, exc,
        )

    # ------------------------------------------------------------------
    # 2-4. Batch DB updates within a single connection for atomicity.
    # ------------------------------------------------------------------
    cancelled_task_ids: list[str] = []
    cancelled_nodes: list[tuple[str, str]] = []  # (node_id, node_name)
    thread_cancelled = False

    try:
        async with raw_conn() as conn:
            cur = await conn.execute(_CANCEL_ACTIVE_TASKS_BY_THREAD, (thread_id,))
            cancelled_task_ids = [r["task_id"] for r in await cur.fetchall()]

            cur2 = await conn.execute(_CANCEL_ACTIVE_NODES, (thread_id,))
            cancelled_nodes = [(r["node_id"], r["node_name"]) for r in await cur2.fetchall()]

            cur3 = await conn.execute(_UPDATE_THREAD_STATUS, ("cancelled", thread_id))
            thread_rows = await cur3.fetchall()
            thread_cancelled = bool(thread_rows)
    except Exception as exc:
        logger.error(
            "[%s] cancel_thread DB error thread_id=%s: %s",
            LIFECYCLE_DB_ERROR, thread_id, exc,
        )
        raise

    if not thread_cancelled:
        return False  # Already terminal.

    # ------------------------------------------------------------------
    # 5. Set cancel token so delegation loops exit on next poll.
    # ------------------------------------------------------------------
    registry = get_thread_registry()
    registry.set_cancelled(thread_id)
    registry.cleanup_thread(thread_id)

    # ------------------------------------------------------------------
    # 6. SSE -- tasks -> nodes -> thread.
    # ------------------------------------------------------------------
    for task_id in cancelled_task_ids:
        await emit_task_cancelled_sse(thread_id, task_id, reason)

    for node_id, node_name in cancelled_nodes:
        await emit_node_sse(thread_id, node_id, node_name, reason)

    await emit_thread_sse(
        thread_id,
        event="thread_status",
        payload={"status": "cancelled", "reason": reason},
    )
    return True


async def cancel_all_running_threads(*, reason: str = "shutdown") -> None:
    """Cancel every thread currently tracked in the process registry.

    Intended to be called from the FastAPI ``lifespan`` shutdown handler.
    After signalling all registered threads, performs a best-effort bulk DB
    update for any threads still marked running in the DB (e.g. orphaned by a
    previous unclean shutdown).

    Errors are logged but never raised -- shutdown must proceed regardless.

    Args:
        reason: Cancellation reason label (default ``"shutdown"``).
    """
    registry = get_thread_registry()

    # ------------------------------------------------------------------
    # 1. Signal all locally-tracked threads.
    # ------------------------------------------------------------------
    local_thread_ids = registry.active_thread_ids()
    for thread_id in local_thread_ids:
        try:
            await cancel_thread(thread_id, reason=reason)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[%s] shutdown cancel failed thread_id=%s: %s",
                LIFECYCLE_CANCEL_FAILED, thread_id, exc,
            )

    # ------------------------------------------------------------------
    # 2. Revoke any remaining Celery tasks (safety net).
    # ------------------------------------------------------------------
    registry.revoke_all_celery_tasks()

    # ------------------------------------------------------------------
    # 3. Bulk-update any orphaned active threads in DB.
    # ------------------------------------------------------------------
    try:
        async with raw_conn() as conn:
            cur = await conn.execute(_LIST_ACTIVE_THREAD_IDS)
            orphan_ids = [r["thread_id"] for r in await cur.fetchall()]

        for thread_id in orphan_ids:
            if thread_id in local_thread_ids:
                continue  # Already handled above.
            try:
                async with raw_conn() as conn:
                    await conn.execute(
                        _CANCEL_ACTIVE_TASKS_BY_THREAD, (thread_id,)
                    )
                    await conn.execute(_CANCEL_ACTIVE_NODES, (thread_id,))
                    await conn.execute(
                        _UPDATE_THREAD_STATUS, ("cancelled", thread_id)
                    )
                logger.warning(
                    "[lifecycle] shutdown: orphaned thread_id=%s marked cancelled",
                    thread_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[%s] shutdown orphan cancel failed thread_id=%s: %s",
                    LIFECYCLE_DB_ERROR, thread_id, exc,
                )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[%s] shutdown orphan query failed: %s",
            LIFECYCLE_DB_ERROR, exc,
        )


__all__ = [
    "register_thread",
    "get_cancel_token",
    "is_thread_cancelled",
    "complete_thread",
    "cancel_thread",
    "cancel_all_running_threads",
    "pause_all_running_tasks_on_shutdown",
]


async def pause_all_running_tasks_on_shutdown() -> None:
    """Pause all running tasks on graceful shutdown instead of cancelling.

    Intentionally leaves node status as ``'running'`` so
    :func:`~backend.langgraph.lifecycle.startup.recover_running_threads` will
    re-dispatch those threads on the next startup.  Inside each node,
    :meth:`~backend.langgraph.models.node.BaseNode.run_task` detects the paused
    task via :func:`~backend.langgraph.lifecycle.threads.nodes.tasks.get_paused_task_for_node`
    and reuses the saved snapshot, causing
    :func:`~backend.celery_task.workers.task_delegation.delegate_stream` to
    dispatch ``run_stream_compact_continue`` automatically.

    Errors are logged but never raised -- shutdown must proceed regardless.
    """
    from backend.langgraph.lifecycle.pause_flag import set_task_pause_flag

    registry = get_thread_registry()

    # 1. Find all running tasks in the DB.
    try:
        async with raw_conn() as conn:
            cur = await conn.execute(
                "SELECT task_id, thread_id FROM fin_agents.tasks WHERE status = 'running'"
            )
            running_tasks = await cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.error("[lifecycle] pause_all shutdown: DB query failed: %s", exc)
        running_tasks = []

    # 2. Set task-level pause flags in Redis so stream workers stop gracefully.
    for row in running_tasks:
        try:
            await set_task_pause_flag(row["task_id"])
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[lifecycle] pause_all: set_pause_flag task_id=%s: %s",
                row["task_id"], exc,
            )

    # 3. Bulk-update running tasks -> 'paused' in DB (nodes intentionally stay 'running').
    try:
        from backend.langgraph.lifecycle.threads.nodes.tasks.sql import (  # noqa: PLC0415
            _BULK_PAUSE_RUNNING_TASKS,
        )
        async with raw_conn() as conn:
            await conn.execute(_BULK_PAUSE_RUNNING_TASKS)
    except Exception as exc:  # noqa: BLE001
        logger.error("[lifecycle] pause_all: bulk task DB update failed: %s", exc)

    # 4. Bulk-update running nodes -> 'paused' with is_last_paused_by_server=TRUE.
    # This is done before revoking Celery tasks so the node status is correct
    # even if the event loop shuts down before the graph's except handlers run.
    try:
        async with raw_conn() as conn:
            await conn.execute(
                """
                UPDATE fin_agents.nodes
                SET status                   = 'paused',
                    is_last_paused_by_server = TRUE,
                    updated_at               = NOW()
                WHERE status = 'running'
                """
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("[lifecycle] pause_all: bulk node DB update failed: %s", exc)

    # 5. Revoke Celery tasks -- triggers TaskPausedError inside _await_result.
    registry.revoke_all_celery_tasks()

    if running_tasks:
        logger.error(
            "[lifecycle] pause_all_running_tasks_on_shutdown: paused %d task(s)",
            len(running_tasks),
        )
