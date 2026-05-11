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
    _LIST_ACTIVE_THREAD_IDS,
    _UPDATE_THREAD_COMPLETED,
    _UPDATE_THREAD_STATUS,
)
from backend.langgraph.lifecycle.threads.sse import (
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


__all__ = [
    "register_thread",
    "get_cancel_token",
    "is_thread_cancelled",
    "complete_thread",
    "cancel_thread",
    "cancel_all_running_threads",
]
