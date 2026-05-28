"""Read-only task query operations."""

from __future__ import annotations

from typing import Any

from backend.db.postgres import raw_conn, pg_retry
from backend.langgraph.lifecycle.threads.nodes.tasks.sql import (
    _GET_EXISTING_TASK_FOR_NODE,
    _GET_LATEST_LLM_RESPONSE,
    _GET_PAUSED_TASK_FOR_NODE,
    _GET_TASK_FULL,
    _INVALIDATE_NODE_TASK_CACHES,
)


@pg_retry()
async def get_task_full(thread_id: str, task_id: str) -> dict[str, Any] | None:
    """Fetch a task row with its execution input from the DB.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task UUID.

    Returns:
        Row dict with task metadata and ``input`` field, or ``None`` if not found.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(_GET_TASK_FULL, (task_id, thread_id))
        row = await cur.fetchone()
    return dict(row) if row else None


@pg_retry()
async def get_paused_task_for_node(
    thread_id: str,
    node_id: str,
    task_name: str,
) -> dict[str, Any] | None:
    """Return the paused task row for (thread_id, node_id, task_name), or None.

    Called by :meth:`~backend.langgraph.models.node.BaseNode.run_task` on graph
    resume to detect whether a prior run left a paused task on this node so the
    node can continue from the saved snapshot instead of starting from scratch.

    Args:
        thread_id: LangGraph thread UUID.
        node_id:   Owning node UUID.
        task_name: Task name key.

    Returns:
        Dict with ``task_id``, or ``None`` if no paused task exists.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(_GET_PAUSED_TASK_FOR_NODE, (thread_id, node_id, task_name))
        row = await cur.fetchone()
    return dict(row) if row else None


@pg_retry()
async def get_existing_task_for_node(
    thread_id: str,
    node_id: str,
    task_name: str,
    input_json: str,
) -> dict[str, Any] | None:
    """Return any existing task row for (thread_id, node_id, task_name), or None.

    For non-completed tasks the match is unconditional so paused/failed tasks
    are reused (task_id reuse for retry).  For completed tasks the
    ``input_hash`` of the current invocation must match so a different input
    does not serve a stale cache result.

    Args:
        thread_id:  LangGraph thread UUID.
        node_id:    Owning node UUID.
        task_name:  Task name key.
        input_json: JSON-serialized task input; passed to Postgres so the
                    hash comparison is done server-side against the stored
                    ``md5(input::text)`` generated column.

    Returns:
        Dict with ``task_id``, ``status``, ``updated_at``, and
        ``cache_ttl_seconds``, or ``None`` if no matching task exists.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(_GET_EXISTING_TASK_FOR_NODE, (thread_id, node_id, task_name, input_json))
        row = await cur.fetchone()
    return dict(row) if row else None


@pg_retry()
async def get_latest_llm_response(task_id: str) -> dict[str, Any] | None:
    """Fetch the most recent LLM response record for a task.

    Args:
        task_id: Task UUID.

    Returns:
        Dict with ``thinking`` (str | None) and ``answer`` (str | None),
        or ``None`` if no response row exists.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(_GET_LATEST_LLM_RESPONSE, (task_id,))
        row = await cur.fetchone()
    return dict(row) if row else None


async def invalidate_node_task_caches(thread_id: str, node_id: str) -> int:
    """Zero-out cache_ttl_seconds for all completed tasks under *node_id*.

    After this call the tasks will not be matched as valid cache entries in
    ``get_existing_task_for_node`` and will be re-executed on the next run.

    Args:
        thread_id: LangGraph thread UUID.
        node_id:   Owning node UUID.

    Returns:
        Number of task rows invalidated.
    """
    async with raw_conn() as conn:
        cur = await conn.execute(_INVALIDATE_NODE_TASK_CACHES, (node_id, thread_id))
        return cur.rowcount


__all__ = [
    "get_existing_task_for_node",
    "get_latest_llm_response",
    "get_paused_task_for_node",
    "get_task_full",
    "invalidate_node_task_caches",
]
