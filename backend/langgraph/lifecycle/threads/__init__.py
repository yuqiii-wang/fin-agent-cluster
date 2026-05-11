"""backend.langgraph.lifecycle.threads — thread-level lifecycle.

Public API
----------
:func:`register_thread`           — register a new cancel token for the thread.
:func:`cancel_thread`             — cascade cancel to all active nodes/tasks;
                                    persist DB; emit SSE.
:func:`complete_thread`           — mark thread completed/failed; persist; emit SSE.
:func:`cancel_all_running_threads` — shutdown handler; cancels everything in
                                    the process registry + orphaned DB rows.
:func:`is_thread_cancelled`       — check the in-process cancel token.
:func:`get_cancel_token`          — retrieve the ``asyncio.Event`` for polling.

All state transitions write to DB **before** emitting SSE.  Cascade order:
  Thread → active Nodes → active Tasks (via bulk UPDATE RETURNING).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from backend.db.postgres import raw_conn
from backend.langgraph.lifecycle.errors import (
    LIFECYCLE_CANCEL_FAILED,
    LIFECYCLE_DB_ERROR,
)
from backend.langgraph.lifecycle.threads.manager import (
    TERMINAL_QUERY_STATUSES,
    get_thread_registry,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_UPDATE_THREAD_STATUS = """
    UPDATE fin_agents.user_queries
    SET status = %s
    WHERE thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled')
    RETURNING thread_id
"""

_UPDATE_THREAD_COMPLETED = """
    UPDATE fin_agents.user_queries
    SET status       = %s,
        answer       = %s,
        completed_at = NOW(),
        error        = %s
    WHERE thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled')
    RETURNING thread_id
"""

# Bulk-cancel all active nodes for the thread (RETURNING for SSE).
_CANCEL_ACTIVE_NODES = """
    UPDATE fin_agents.nodes
    SET status     = 'cancelled',
        updated_at = NOW()
    WHERE thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING node_id, node_name
"""

# Bulk-cancel all active tasks for the thread (RETURNING task_ids for SSE
# and Celery revocation).
_CANCEL_ACTIVE_TASKS_BY_THREAD = """
    UPDATE fin_agents.tasks
    SET status     = 'cancelled',
        updated_at = NOW()
    WHERE thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING task_id
"""

# Fetch thread IDs whose status is not terminal — used during shutdown.
_LIST_ACTIVE_THREAD_IDS = """
    SELECT thread_id
    FROM fin_agents.user_queries
    WHERE status NOT IN ('completed', 'failed', 'cancelled')
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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

    Args:
        thread_id: LangGraph thread UUID.
        answer:    Final answer text (for completed threads).
        failed:    ``True`` to mark as failed.
        error:     Error message stored in ``user_queries.error``.
    """
    status = "failed" if failed else "completed"

    async with raw_conn() as conn:
        cur = await conn.execute(
            _UPDATE_THREAD_COMPLETED,
            (status, answer, error, thread_id),
        )
        rows = await cur.fetchall()

    if not rows:
        return  # Already terminal.

    get_thread_registry().cleanup_thread(thread_id)

    event = "done" if not failed else "thread_failed"
    logger.debug(
        "[lifecycle:thread] %s thread_id=%s — emitting SSE event=%s",
        status, thread_id, event,
    )
    t_sse = time.monotonic()
    # SSE: thread-level done / failed event.
    await _emit_thread_sse(
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
    1. Revoke all in-flight Celery tasks tracked for this thread.
    2. Batch-UPDATE active tasks to ``cancelled`` (RETURNING task_ids).
    3. Batch-UPDATE active nodes to ``cancelled`` (RETURNING node rows).
    4. UPDATE the thread itself to ``cancelled``.
    5. Set the process-local cancel token so polling delegation loops exit.
    6. Emit SSE: task cancelled → node cancelled → thread cancelled.

    All DB writes precede the corresponding SSE events.

    Args:
        thread_id: LangGraph thread UUID.
        reason:    Human-readable reason (``"user"``, ``"shutdown"``, …).

    Returns:
        ``True`` if the thread was active and has been cancelled;
        ``False`` if it was already terminal.
    """
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
    # 6. SSE — tasks → nodes → thread.
    # ------------------------------------------------------------------
    for task_id in cancelled_task_ids:
        await _emit_task_cancelled_sse(thread_id, task_id, reason)

    for node_id, node_name in cancelled_nodes:
        await _emit_node_sse(thread_id, node_id, node_name, reason)

    await _emit_thread_sse(
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

    Errors are logged but never raised — shutdown must proceed regardless.

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


# ---------------------------------------------------------------------------
# Internal SSE helpers
# ---------------------------------------------------------------------------


async def _emit_thread_sse(
    thread_id: str,
    event: str,
    payload: dict[str, Any],
) -> None:
    """Publish a thread-scoped SSE event (fire-and-forget on error)."""
    try:
        from backend.centrifugo_mq.sse_notification.thread import notify
        logger.error(
            "[lifecycle:thread] emitting thread SSE thread_id=%s event=%s",
            thread_id, event,
        )
        acked = await notify(
            thread_id=thread_id,
            event=event,
            payload=payload,
            dedup_key=f"thread:{event}:{payload.get('status', '')}",
        )
        if not acked:
            logger.error(
                "[lifecycle:thread] thread SSE not acked thread_id=%s event=%s",
                thread_id, event,
            )
        else:
            logger.error(
                "[lifecycle:thread] thread SSE acked thread_id=%s event=%s",
                thread_id, event,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[LC007] thread SSE publish failed thread_id=%s event=%s: %s",
            thread_id, event, exc,
        )


async def _emit_node_sse(
    thread_id: str,
    node_id: str,
    node_name: str,
    reason: str,
) -> None:
    """Publish a ``node_status: cancelled`` SSE event (fire-and-forget)."""
    try:
        from backend.centrifugo_mq.sse_notification.thread.node import notify
        logger.error(
            "[lifecycle:thread] emitting node cancelled SSE thread_id=%s node_id=%s",
            thread_id, node_id,
        )
        acked = await notify(
            thread_id=thread_id,
            node_id=node_id,
            event="node_status",
            payload={"status": "cancelled", "node_name": node_name, "reason": reason},
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


async def _emit_task_cancelled_sse(
    thread_id: str,
    task_id: str,
    reason: str,
) -> None:
    """Publish a ``task_status: cancelled`` SSE event (fire-and-forget)."""
    try:
        from backend.centrifugo_mq.sse_notification.thread.node.task import notify
        logger.error(
            "[lifecycle:thread] emitting task cancelled SSE thread_id=%s task_id=%s",
            thread_id, task_id,
        )
        acked = await notify(
            thread_id=thread_id,
            task_id=task_id,
            event="task_status",
            payload={"status": "cancelled", "reason": reason},
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


__all__ = [
    "register_thread",
    "get_cancel_token",
    "is_thread_cancelled",
    "complete_thread",
    "cancel_thread",
    "cancel_all_running_threads",
]
