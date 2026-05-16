"""backend.users.queries.lifecycle — ack, cancel, resume, cancel_node, cancel_task."""

from __future__ import annotations

from backend.db.postgres import raw_conn
from backend.users.schemas import QueryResponse
from backend.users.queries._sql import _ACK_QUERY, _ACTIVE_TASK_COUNT_IN_NODE
from backend.users.queries._helpers import _row_to_query_response, _cascade_up_from_cancelled_node
from backend.users.queries.status import get_query_status


async def ack_query(thread_id: str) -> QueryResponse:
    """Acknowledge a received query and launch the LangGraph graph.

    Updates the DB status to ``'running'`` and dispatches the graph execution
    as a background asyncio task so the HTTP response returns immediately.

    Args:
        thread_id: LangGraph thread UUID previously returned by :func:`submit_query`.

    Returns:
        :class:`QueryResponse` with ``status='running'``.
    """
    async with raw_conn() as conn:
        cur = await conn.execute(_ACK_QUERY, (thread_id,))
        row = await cur.fetchone()

    if row is None:
        return await get_query_status(thread_id)

    from backend.main_thread import dispatch_graph_run
    await dispatch_graph_run(thread_id, row["query"])

    return QueryResponse(
        thread_id=row["thread_id"],
        status=row["status"],
        query=row["query"],
        answer=row["answer"],
        error=row["error"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


async def cancel_query(thread_id: str, reason: str = "user") -> QueryResponse:
    """Cancel a running or received query thread.

    Writes a Redis cancel flag so the graph runner's delegation poll loop
    detects it within ``_CANCEL_POLL_INTERVAL`` and revokes Celery tasks.
    Also performs the DB cascade (nodes + tasks → cancelled) so the UI
    receives accurate status regardless of graph runner timing.

    Args:
        thread_id: LangGraph thread UUID.
        reason:    Human-readable cancellation reason.

    Returns:
        Updated :class:`QueryResponse`.
    """
    from backend.main_thread.cancel_flag import set_cancel_flag
    from backend.langgraph.lifecycle import cancel_thread
    await set_cancel_flag(thread_id)
    await cancel_thread(thread_id, reason=reason)
    return await get_query_status(thread_id)


async def resume_query(thread_id: str) -> QueryResponse:
    """Resume a cancelled or failed query from its last LangGraph checkpoint.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        Updated :class:`QueryResponse` with ``status='running'``.
    """
    async with raw_conn() as conn:
        cur = await conn.execute(
            """
            UPDATE fin_agents.user_queries
            SET status = 'running'
            WHERE thread_id = %s
              AND status IN ('cancelled', 'failed')
            RETURNING thread_id, status, query, answer, error, created_at, completed_at
            """,
            (thread_id,),
        )
        row = await cur.fetchone()

    if row is None:
        return await get_query_status(thread_id)

    from backend.main_thread import dispatch_graph_run
    await dispatch_graph_run(thread_id, row["query"], resume=True)
    return _row_to_query_response(row)


async def cancel_node(thread_id: str, node_id: str) -> dict:
    """Cancel a specific node and cascade upward if no active siblings/nodes remain.

    Args:
        thread_id: LangGraph thread UUID.
        node_id:   Node execution UUID.

    Returns:
        Dict with ``thread_id``, ``node_id``, and ``action``.
    """
    from backend.langgraph.lifecycle.threads.nodes import cancel_node as _cancel

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            "SELECT parent_node_id FROM fin_agents.nodes"
            " WHERE node_id = %s AND thread_id = %s",
            (node_id, thread_id),
        )
        row = await cur.fetchone()
    parent_node_id: str | None = row["parent_node_id"] if row else None

    await _cancel(thread_id, node_id)
    await _cascade_up_from_cancelled_node(thread_id, node_id, parent_node_id, reason="user")

    return {"thread_id": thread_id, "node_id": node_id, "action": "cancelled"}


async def cancel_task_by_uuid(
    thread_id: str,
    task_id: str,
    *,
    node_id: str = "",
) -> dict:
    """Cancel a specific task and cascade upward if it was the last active task.

    After cancelling the task (output set to ``{}`` by the lifecycle layer),
    checks whether any other active tasks remain in the owning node:

    - Active tasks remain → stop; node keeps running and can decide whether
      the cancelled task's missing output is blocking.
    - No active tasks remain → cancel the node and continue cascade-up via
      :func:`_cascade_up_from_cancelled_node`.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task governance UUID.
        node_id:   Owning node UUID (optional; resolved from DB when empty).

    Returns:
        Dict with ``thread_id``, ``task_id``, and ``action``.
    """
    from backend.langgraph.lifecycle.threads.nodes.tasks import cancel_task as _cancel
    from backend.langgraph.lifecycle.threads.nodes import cancel_node as _cancel_node_lc

    if not node_id:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(
                "SELECT node_id FROM fin_agents.tasks WHERE task_id = %s",
                (task_id,),
            )
            row = await cur.fetchone()
            node_id = row["node_id"] if row else ""

    await _cancel(thread_id, task_id)

    if not node_id:
        return {"thread_id": thread_id, "task_id": task_id, "action": "cancelled"}

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            _ACTIVE_TASK_COUNT_IN_NODE, (node_id, thread_id)
        )
        row = await cur.fetchone()
    active_tasks_remaining = row["cnt"] if row else 0

    if active_tasks_remaining > 0:
        return {"thread_id": thread_id, "task_id": task_id, "action": "cancelled"}

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            "SELECT parent_node_id FROM fin_agents.nodes"
            " WHERE node_id = %s AND thread_id = %s",
            (node_id, thread_id),
        )
        row = await cur.fetchone()
    parent_node_id: str | None = row["parent_node_id"] if row else None

    await _cancel_node_lc(thread_id, node_id, reason="user")
    await _cascade_up_from_cancelled_node(thread_id, node_id, parent_node_id, reason="user")

    return {"thread_id": thread_id, "task_id": task_id, "action": "cancelled"}


__all__ = [
    "ack_query",
    "cancel_query",
    "resume_query",
    "cancel_node",
    "cancel_task_by_uuid",
]
