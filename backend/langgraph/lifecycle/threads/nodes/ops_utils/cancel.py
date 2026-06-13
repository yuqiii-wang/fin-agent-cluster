"""cancel_node: revoke Celery tasks, bulk-cancel DB rows, emit SSE."""

from __future__ import annotations

import logging

from backend.db.postgres import raw_conn
from backend.langgraph.lifecycle.errors import (
    LIFECYCLE_CANCEL_FAILED,
    LIFECYCLE_DB_ERROR,
)
from backend.langgraph.lifecycle.threads.nodes.sql import (
    _CANCEL_ACTIVE_TASKS_BY_NODE,
    _CANCEL_NODE_SELF,
)
from backend.langgraph.lifecycle.threads.nodes.sse import (
    emit_node_sse,
    emit_task_cancelled_sse,
)

logger = logging.getLogger(__name__)


def _get_thread_registry():
    """Lazy import to avoid circular imports at module load time."""
    from backend.langgraph.lifecycle.threads.manager import (
        get_thread_registry as _get,
    )
    return _get()


async def cancel_node(
    thread_id: str,
    node_id: str,
    *,
    reason: str = "user",
) -> bool:
    """Cancel a node and all its active tasks, then emit SSE.

    Cascade order:
    1. Revoke all tracked Celery tasks for the node.
    2. Bulk-UPDATE active tasks to ``cancelled`` (RETURNING task_ids for SSE).
    3. UPDATE the node itself to ``cancelled``.
    4. Emit SSE for each cancelled task, then for the node.

    Args:
        thread_id: LangGraph thread UUID.
        node_id:   Node ID to cancel.
        reason:    Human-readable cancellation reason.

    Returns:
        ``True`` if the node was active and has been cancelled;
        ``False`` if it was already terminal.
    """
    # ------------------------------------------------------------------
    # 1. Revoke in-flight Celery tasks for this node.
    # ------------------------------------------------------------------
    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(
                "SELECT task_id FROM fin_agents.tasks WHERE node_id = %s "
                "AND thread_id = %s "
                "AND status NOT IN ('completed','failed','cancelled','wrong')",
                (node_id, thread_id),
            )
            active_task_ids = [r["task_id"] for r in await cur.fetchall()]

        registry = _get_thread_registry()
        for tid in active_task_ids:
            registry.revoke_celery_task(tid)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[%s] cancel_node revoke failed node_id=%s: %s",
            LIFECYCLE_CANCEL_FAILED, node_id, exc,
        )

    # ------------------------------------------------------------------
    # 2 & 3. Batch DB updates (tasks first, then node).
    # ------------------------------------------------------------------
    node_cancelled = False

    try:
        async with raw_conn() as conn:
            cur = await conn.execute(
                _CANCEL_ACTIVE_TASKS_BY_NODE, (node_id, thread_id)
            )
            cancelled_task_rows = await cur.fetchall()

            cur2 = await conn.execute(_CANCEL_NODE_SELF, (node_id, thread_id))
            node_cancelled = cur2.rowcount > 0
    except Exception as exc:
        logger.error(
            "[%s] cancel_node DB error node_id=%s: %s",
            LIFECYCLE_DB_ERROR, node_id, exc,
        )
        raise

    if not node_cancelled:
        return False  # Already terminal.

    # ------------------------------------------------------------------
    # 3b. Set per-node cancel flag in Redis so the delegation poll loop
    #     for this node's tasks exits within one cycle (avoids the 120 s
    #     task timeout when the node was cancelled mid-execution).
    # ------------------------------------------------------------------
    try:
        from backend.langgraph.lifecycle.cancel_flag import set_node_cancel_flag
        await set_node_cancel_flag(node_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[%s] cancel_node set_node_cancel_flag failed node_id=%s: %s",
            LIFECYCLE_CANCEL_FAILED, node_id, exc,
        )

    # ------------------------------------------------------------------
    # 4. SSE -- tasks first, then node.
    # ------------------------------------------------------------------
    for row in cancelled_task_rows:
        await emit_task_cancelled_sse(
            thread_id,
            row["task_id"],
            task_name=row["task_name"] or "",
            node_name=row["node_name"] or "",
            reason=reason,
        )

    await emit_node_sse(
        thread_id, node_id, node_name="",
        status="cancelled",
        payload={"reason": reason},
    )
    return True


__all__ = ["cancel_node"]
