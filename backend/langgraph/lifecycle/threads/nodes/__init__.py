"""backend.langgraph.lifecycle.threads.nodes — node-level lifecycle.

Public API
----------
:func:`upsert_node`    — INSERT or UPDATE a node row; emit ``node_status: running``.
:func:`complete_node`  — UPDATE to completed/failed; emit ``node_status: completed``.
:func:`cancel_node`    — UPDATE to cancelled; cascade to all active tasks; emit SSE.

All state transitions persist to ``fin_agents.nodes`` **before** the
corresponding SSE event is published.  Writes are conditional on non-terminal
status for idempotency.

Node completion is always driven by the graph runner (node functions) once
all their tasks have resolved.  Celery workers only write to ``fin_agents.tasks``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from backend.db.postgres import raw_conn
from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle.errors import (
    LIFECYCLE_CANCEL_FAILED,
    LIFECYCLE_DB_ERROR,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_UPSERT_NODE = """
    INSERT INTO fin_agents.nodes
        (node_id, thread_id, type, parent_node_id, node_name,
         status, input, started_at, updated_at)
    VALUES (%s, %s, %s, %s, %s, 'running', %s::jsonb, NOW(), NOW())
    ON CONFLICT (node_id) DO UPDATE
    SET status     = CASE
                       WHEN fin_agents.nodes.status IN
                            ('completed', 'failed', 'cancelled', 'wrong')
                       THEN fin_agents.nodes.status
                       ELSE 'running'
                     END,
        input      = EXCLUDED.input,
        updated_at = NOW()
"""

_UPDATE_NODE_COMPLETED = """
    UPDATE fin_agents.nodes
    SET status     = %s,
        output     = %s::jsonb,
        elapsed_ms = EXTRACT(EPOCH FROM (NOW() - started_at))::INT * 1000,
        updated_at = NOW()
    WHERE node_id  = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
"""

_CANCEL_NODE_SELF = """
    UPDATE fin_agents.nodes
    SET status     = 'cancelled',
        updated_at = NOW()
    WHERE node_id  = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING node_id, node_name
"""

_CANCEL_ACTIVE_TASKS_BY_NODE = """
    UPDATE fin_agents.tasks
    SET status     = 'cancelled',
        updated_at = NOW()
    WHERE node_id  = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING task_id
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def upsert_node(
    thread_id: str,
    node_id: str,
    node_name: str,
    node_type: str = NodeType.TYPICAL,
    parent_node_id: str | None = None,
    input_data: dict[str, Any] | None = None,
) -> None:
    """Persist a node execution row (INSERT or UPDATE to running).

    Safe to call multiple times for the same node; subsequent calls update
    the input and reset status to running (unless already terminal).

    Emits a ``node_status: running`` SSE event after the DB write.

    Args:
        thread_id:      LangGraph thread UUID.
        node_id:        Stable node ID (from ``make_node_id``).
        node_name:      Human-readable node name.
        node_type:      ``"Typical"``, ``"Reference"``, or ``"Subgraph"``.
        parent_node_id: Parent subgraph node ID, or ``None`` for top-level nodes.
        input_data:     Serialisable input payload.
    """
    t0 = time.monotonic()
    try:
        async with raw_conn() as conn:
            await conn.execute(
                _UPSERT_NODE,
                (
                    node_id, thread_id, node_type, parent_node_id, node_name,
                    json.dumps(input_data or {}),
                ),
            )
    except Exception as exc:
        logger.error(
            "[%s] upsert_node DB error node_id=%s thread_id=%s: %s",
            LIFECYCLE_DB_ERROR, node_id, thread_id, exc,
        )
        raise

    logger.debug(
        "[lifecycle:node] running node_id=%s node_name=%s db_ms=%.0f — emitting SSE",
        node_id, node_name, (time.monotonic() - t0) * 1000,
    )
    t_sse = time.monotonic()
    await _emit_node_sse(thread_id, node_id, node_name, status="running", payload={"input": input_data or {}})
    logger.debug(
        "[lifecycle:node] running SSE done node_id=%s node_name=%s sse_ms=%.0f",
        node_id, node_name, (time.monotonic() - t_sse) * 1000,
    )


async def complete_node(
    thread_id: str,
    node_id: str,
    node_name: str,
    output_data: dict[str, Any] | None = None,
    *,
    failed: bool = False,
    error: str | None = None,
) -> None:
    """Mark a node as completed (or failed) and emit the SSE event.

    Idempotent: if the node is already terminal, the UPDATE is a no-op
    and no SSE is emitted.

    Args:
        thread_id:   LangGraph thread UUID.
        node_id:     Node ID to update.
        node_name:   Human-readable node name.
        output_data: Result payload (stored in ``nodes.output``).
        failed:      ``True`` to mark as failed.
        error:       Error message included in output when *failed*.
    """
    await _complete_node_internal(
        thread_id=thread_id,
        node_id=node_id,
        node_name=node_name,
        output_data=output_data,
        failed=failed,
        error=error,
    )


async def _complete_node_internal(
    thread_id: str,
    node_id: str,
    node_name: str,
    output_data: dict[str, Any] | None,
    failed: bool,
    error: str | None,
) -> None:
    """Internal implementation used by both ``complete_node`` and auto-complete."""
    t0 = time.monotonic()
    status = "failed" if failed else "completed"
    out: dict[str, Any]
    if failed:
        out = {"error": error or "unknown error"}
    else:
        out = output_data or {}

    async with raw_conn() as conn:
        cur = await conn.execute(
            _UPDATE_NODE_COMPLETED,
            (status, json.dumps(out), node_id, thread_id),
        )
        updated = cur.rowcount

    if updated == 0:
        # Node already terminal — skip SSE. Log as error for diagnostics
        # (e.g. double-processing from recover_pending_runs race).
        try:
            async with raw_conn(readonly=True) as _rc:
                _cur = await _rc.execute(
                    "SELECT status FROM fin_agents.nodes WHERE node_id = %s AND thread_id = %s",
                    (node_id, thread_id),
                )
                _row = await _cur.fetchone()
            _existing = _row["status"] if _row else "not_found"
        except Exception:
            _existing = "unknown"
        logger.error(
            "[lifecycle:node] %s skipped node_id=%s node_name=%s existing_status=%s — node already terminal",
            status, node_id, node_name, _existing,
        )
        return  # Already terminal — skip SSE.

    logger.debug(
        "[lifecycle:node] %s node_id=%s node_name=%s db_ms=%.0f — emitting SSE",
        status, node_id, node_name, (time.monotonic() - t0) * 1000,
    )
    t_sse = time.monotonic()
    await _emit_node_sse(
        thread_id, node_id, node_name,
        status=status,
        payload={"output": out},
    )
    logger.debug(
        "[lifecycle:node] %s SSE done node_id=%s node_name=%s sse_ms=%.0f total_ms=%.0f",
        status, node_id, node_name,
        (time.monotonic() - t_sse) * 1000, (time.monotonic() - t0) * 1000,
    )


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

        registry = get_thread_registry()
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
    cancelled_task_ids: list[str] = []
    node_cancelled = False

    try:
        async with raw_conn() as conn:
            cur = await conn.execute(
                _CANCEL_ACTIVE_TASKS_BY_NODE, (node_id, thread_id)
            )
            cancelled_task_ids = [r["task_id"] for r in await cur.fetchall()]

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
    # 4. SSE — tasks first, then node.
    # ------------------------------------------------------------------
    for task_id in cancelled_task_ids:
        await _emit_task_cancelled_sse(thread_id, task_id, reason)

    await _emit_node_sse(
        thread_id, node_id, node_name="",
        status="cancelled",
        payload={"reason": reason},
    )
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def get_thread_registry():
    """Lazy import to avoid circular imports at module load time."""
    from backend.langgraph.lifecycle.threads.manager import (
        get_thread_registry as _get,
    )
    return _get()


async def _emit_node_sse(
    thread_id: str,
    node_id: str,
    node_name: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    """Publish a ``node_status`` SSE event (fire-and-forget on error)."""
    try:
        from backend.centrifugo_mq.sse_notification.thread.node import notify
        await notify(
            thread_id=thread_id,
            node_id=node_id,
            event="node_status",
            payload={"status": status, "node_name": node_name, **payload},
            dedup_key=f"node:{node_id}:{status}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[%s] node SSE publish failed node_id=%s status=%s: %s",
            "LC007", node_id, status, exc,
        )


async def _emit_task_cancelled_sse(
    thread_id: str,
    task_id: str,
    reason: str,
) -> None:
    """Publish a ``task_status: cancelled`` SSE event (fire-and-forget)."""
    try:
        from backend.centrifugo_mq.sse_notification.thread.node.task import notify
        await notify(
            thread_id=thread_id,
            task_id=task_id,
            event="task_status",
            payload={"status": "cancelled", "reason": reason},
            dedup_key=f"task:{task_id}:cancelled",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[%s] task cancelled SSE failed task_id=%s: %s",
            "LC007", task_id, exc,
        )


__all__ = ["upsert_node", "complete_node", "cancel_node"]
