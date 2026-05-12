"""backend.users.queries — business logic for thread query operations.

Provides helpers called by :mod:`backend.api.threads.router` to submit,
acknowledge, cancel, resume, and inspect query threads.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from backend.db.postgres import raw_conn
from backend.users.models import UserQuery
from backend.users.schemas import (
    NodeExecutionInfo,
    QueryRequest,
    QueryResponse,
    SessionStatus,
    SseInfo,
    TaskInfo,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------


# Immediate submission: status starts as 'received'; is_ack is set upfront
# so the graph can launch without a separate client ACK round-trip.
# Status is updated to 'running' once the graph task actually begins.
_INSERT_QUERY_IMMEDIATE = """
    INSERT INTO fin_agents.user_queries
        (thread_id, user_id, query, status, is_ack)
    VALUES (%s, %s, %s, 'received', TRUE)
    RETURNING thread_id, status, query, created_at, completed_at, answer, error
"""

_SET_STATUS_RUNNING = """
    UPDATE fin_agents.user_queries
    SET status = 'running'
    WHERE thread_id = %s
      AND status = 'received'
"""

_SELECT_QUERY = """
    SELECT thread_id, status, query, answer, error, created_at, completed_at
    FROM fin_agents.user_queries
    WHERE thread_id = %s
"""

_ACK_QUERY = """
    UPDATE fin_agents.user_queries
    SET status = 'running', is_ack = TRUE
    WHERE thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled')
    RETURNING thread_id, status, query, answer, error, created_at, completed_at
"""

_CANCEL_QUERY_STATUS = """
    SELECT status FROM fin_agents.user_queries WHERE thread_id = %s
"""

_LIST_NODES = """
    SELECT node_id, thread_id, node_name, status, type,
           parent_node_id, parallel_group, input, output,
           started_at, elapsed_ms, updated_at
    FROM fin_agents.nodes
    WHERE thread_id = %s
    ORDER BY started_at
"""

_LIST_TASKS = """
    SELECT task_id, thread_id, node_id, node_name, task_name,
           status, input, output, created_at, updated_at
    FROM fin_agents.tasks
    WHERE thread_id = %s
    ORDER BY created_at
"""

# Task names whose output is delivered as a live LLM token stream.
# Keep in sync with the stream_task worker dispatch list.
_STREAMING_TASK_NAMES: frozenset[str] = frozenset({"stream_conclusion"})

# Reset the parent subgraph container + all its inner nodes from 'cancelled'
# to 'pending' so the upcoming upsert_node calls can set them to 'running'.
_RESET_SUBGRAPH_NODES_TO_PENDING = """
    UPDATE fin_agents.nodes
    SET status = 'pending', updated_at = NOW()
    WHERE thread_id = %s
      AND (node_id = %s OR parent_node_id = %s)
      AND status = 'cancelled'
"""

# Same reset for a single top-level node.
_RESET_NODE_TO_PENDING = """
    UPDATE fin_agents.nodes
    SET status = 'pending', updated_at = NOW()
    WHERE thread_id = %s
      AND node_id = %s
      AND status = 'cancelled'
"""

# ---------------------------------------------------------------------------
# Cascade-up helpers: check remaining active siblings / nodes / tasks.
# ---------------------------------------------------------------------------

# Active tasks still running in a given node (used for task → node cascade).
_ACTIVE_TASK_COUNT_IN_NODE = """
    SELECT COUNT(*) AS cnt
    FROM fin_agents.tasks
    WHERE node_id   = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
"""

# Active inner nodes remaining inside a subgraph (used for inner-node → subgraph cascade).
_ACTIVE_SIBLING_NODE_COUNT = """
    SELECT COUNT(*) AS cnt
    FROM fin_agents.nodes
    WHERE parent_node_id = %s
      AND thread_id      = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
"""

# Active top-level nodes remaining in a thread (used for node → thread cascade).
_ACTIVE_TOP_LEVEL_NODE_COUNT = """
    SELECT COUNT(*) AS cnt
    FROM fin_agents.nodes
    WHERE thread_id      = %s
      AND parent_node_id IS NULL
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_query_response(row: Any) -> QueryResponse:
    """Convert a DB row (tuple or mapping) to :class:`QueryResponse`."""
    return QueryResponse(
        thread_id=row["thread_id"],
        status=row["status"],
        query=row["query"],
        answer=row["answer"],
        error=row["error"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


async def _cascade_up_from_cancelled_node(
    thread_id: str,
    node_id: str,
    parent_node_id: str | None,
    reason: str,
) -> None:
    """Propagate cancellation upward after a node reaches 'cancelled' state.

    Rules (applied once per level, non-recursive for top-level):
    - Inner node (``parent_node_id`` set): if no active siblings remain inside
      the parent subgraph, cancel the parent subgraph node and recurse.
    - Top-level node (``parent_node_id`` is ``None``): if no active top-level
      nodes remain, cancel the thread (sets Redis cancel flag + DB status).

    Args:
        thread_id:      LangGraph thread UUID.
        node_id:        The node that was just cancelled.
        parent_node_id: Parent subgraph node ID, or ``None`` for top-level nodes.
        reason:         Propagated cancellation reason label.
    """
    from backend.langgraph.lifecycle.threads.nodes import cancel_node as _cancel_node_lc
    from backend.langgraph.lifecycle import cancel_thread as _cancel_thread_lc
    from backend.main_thread.cancel_flag import set_cancel_flag

    if parent_node_id:
        # --- Inner node: check whether all siblings in the subgraph are done ---
        try:
            async with raw_conn(readonly=True) as conn:
                cur = await conn.execute(
                    _ACTIVE_SIBLING_NODE_COUNT,
                    (parent_node_id, thread_id),
                )
                row = await cur.fetchone()
            active_siblings = row["cnt"] if row else 0
        except Exception as exc:
            logger.error(
                "[cascade_up] DB error checking siblings parent_node_id=%s: %s",
                parent_node_id, exc,
            )
            return

        if active_siblings > 0:
            return  # Siblings still running — parent stays alive.

        # All siblings done → cascade up to the parent subgraph node.
        try:
            async with raw_conn(readonly=True) as conn:
                cur = await conn.execute(
                    "SELECT parent_node_id FROM fin_agents.nodes"
                    " WHERE node_id = %s AND thread_id = %s",
                    (parent_node_id, thread_id),
                )
                prow = await cur.fetchone()
            grandparent_id: str | None = prow["parent_node_id"] if prow else None
        except Exception as exc:
            logger.error(
                "[cascade_up] DB error fetching parent info node_id=%s: %s",
                parent_node_id, exc,
            )
            return

        await _cancel_node_lc(thread_id, parent_node_id, reason=reason)
        await _cascade_up_from_cancelled_node(
            thread_id, parent_node_id, grandparent_id, reason
        )
        return

    # --- Top-level node: check whether all top-level nodes are done ---
    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(
                _ACTIVE_TOP_LEVEL_NODE_COUNT,
                (thread_id,),
            )
            row = await cur.fetchone()
        active_top_nodes = row["cnt"] if row else 0
    except Exception as exc:
        logger.error(
            "[cascade_up] DB error checking top-level nodes thread_id=%s: %s",
            thread_id, exc,
        )
        return

    if active_top_nodes > 0:
        return  # Other top-level nodes still running.

    # No active nodes left → cancel the thread.
    try:
        await set_cancel_flag(thread_id)
        await _cancel_thread_lc(thread_id, reason=reason)
    except Exception as exc:
        logger.error(
            "[cascade_up] thread cancel failed thread_id=%s: %s",
            thread_id, exc,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def submit_query(request: QueryRequest, user: Any) -> QueryResponse:
    """Insert a new user query, immediately start graph execution, and return SSE bootstrap info.

    Creates a row in ``fin_agents.user_queries`` with ``status='received'`` and
    ``is_ack=TRUE``, dispatches the LangGraph run as a background asyncio task.
    Status transitions to ``'running'`` once the graph task begins executing.
    Returns Centrifugo SSE connection details so the client can subscribe to
    ``thread:{thread_id}`` on the correct shard without a separate ACK round-trip.

    Args:
        request: Incoming query payload.
        user:    Authenticated guest user object (must have ``id`` attribute).

    Returns:
        :class:`QueryResponse` with ``status='received'``, the new ``thread_id``,
        and an :class:`SseInfo` block for the matching centrifugo-sse shard.
    """
    from backend.auth.jwt import make_connection_token, make_subscription_token
    from backend.centrifugo_mq.client import get_shard_index, get_sse_shard_index
    from backend.config import get_settings

    settings = get_settings()
    thread_id = str(uuid.uuid4())

    from fastapi import HTTPException
    from psycopg.errors import UniqueViolation
    from backend.api.errors import API_ERRORS, API_QUERY_DUPLICATE

    try:
        async with raw_conn() as conn:
            cur = await conn.execute(
                _INSERT_QUERY_IMMEDIATE,
                (thread_id, str(user.id), request.query),
            )
            row = await cur.fetchone()
    except UniqueViolation:
        raise HTTPException(
            status_code=429,
            detail={"code": API_QUERY_DUPLICATE, "message": API_ERRORS[API_QUERY_DUPLICATE]},
        )

    # Set viewer flags BEFORE dispatching the graph run so that stream_task's
    # has_thread_viewer / has_app_viewer checks always see the flags even when
    # the Celery worker starts executing before this coroutine resumes.
    # Race window without this ordering: dispatch → Celery runs stream_task →
    # has_thread_viewer returns False → viewers_present=False → 0 tokens streamed.
    from backend.db.redis.session.thread_user_store import set_thread_user
    from backend.db.redis.session.viewer_store import set_viewer
    await set_thread_user(thread_id, str(user.id))
    await set_viewer(str(user.id), thread_id)
    # Dispatch graph run directly on this main thread's asyncio event loop.
    from backend.main_thread import dispatch_graph_run
    await dispatch_graph_run(thread_id, request.query)

    user_id = str(user.id)
    secret = settings.CENTRIFUGO_SECRET

    sse_shard = get_sse_shard_index(thread_id)
    channel = f"thread:{thread_id}"
    ws_url_sse = f"{settings.CENTRIFUGO_PUBLIC_BASE}/centrifugo-sse-{sse_shard}/connection/websocket"

    llm_shard = get_shard_index(thread_id)
    ws_url_llm = f"{settings.CENTRIFUGO_PUBLIC_BASE}/centrifugo-llm-{llm_shard}/connection/websocket"

    return QueryResponse(
        thread_id=row["thread_id"],
        status=row["status"],
        query=row["query"],
        answer=None,
        error=None,
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        sse=SseInfo(
            ws_url=ws_url_sse,
            connection_token=make_connection_token(user_id, secret),
            subscription_token=make_subscription_token(user_id, channel, secret),
            channel=channel,
        ),
        llm=SseInfo(
            ws_url=ws_url_llm,
            connection_token=make_connection_token(user_id, secret),
            subscription_token=make_subscription_token(user_id, channel, secret),
            channel=channel,
        ),
    )


async def get_query_status(thread_id: str) -> QueryResponse:
    """Return the current status of a query thread from the DB.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        :class:`QueryResponse` reflecting the latest DB state.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(_SELECT_QUERY, (thread_id,))
        row = await cur.fetchone()
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    return _row_to_query_response(row)


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

    # Dispatch graph run directly on this main thread's asyncio event loop.
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

    Cancels the target node and all its active tasks.  Cascade-up behaviour:

    - Inner subgraph node: if all sibling inner nodes are now terminal,
      the parent subgraph node is also cancelled and the check repeats.
    - Top-level node (or promoted-to-top-level from subgraph cascade):
      if no active top-level nodes remain, the thread is cancelled.

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

    # Resolve node_id if not provided by the caller.
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

    # Cascade-up: any active tasks still running in the same node?
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            _ACTIVE_TASK_COUNT_IN_NODE, (node_id, thread_id)
        )
        row = await cur.fetchone()
    active_tasks_remaining = row["cnt"] if row else 0

    if active_tasks_remaining > 0:
        # Other tasks still live — node keeps running.
        return {"thread_id": thread_id, "task_id": task_id, "action": "cancelled"}

    # Last active task in the node → cancel the node and propagate upward.
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


async def get_node_executions(thread_id: str) -> list[NodeExecutionInfo]:
    """Return all node executions for a thread ordered by start time.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        List of :class:`NodeExecutionInfo` records.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(_LIST_NODES, (thread_id,))
        rows = await cur.fetchall()

    return [
        NodeExecutionInfo(
            node_id=r["node_id"],
            thread_id=r["thread_id"],
            node_name=r["node_name"],
            status=r["status"],
            type=r["type"],
            parent_node_id=r["parent_node_id"],
            parallel_group=r["parallel_group"],
            input=r["input"],
            output=r["output"],
            started_at=r["started_at"],
            elapsed_ms=r["elapsed_ms"] or 0,
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


async def get_query_tasks(thread_id: str) -> SessionStatus:
    """Return the query record and all its agent sub-tasks.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        :class:`SessionStatus` with the thread and all tasks.
    """
    thread = await get_query_status(thread_id)

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(_LIST_TASKS, (thread_id,))
        rows = await cur.fetchall()

    tasks = [
        TaskInfo(
            task_id=r["task_id"],
            thread_id=r["thread_id"],
            node_id=r["node_id"],
            node_name=r["node_name"],
            task_name=r["task_name"],
            status=r["status"],
            is_streaming=r["task_name"] in _STREAMING_TASK_NAMES,
            input=r["input"],
            output=r["output"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]
    return SessionStatus(thread=thread, tasks=tasks)


async def re_explore_node(thread_id: str, node_id: str) -> QueryResponse:
    """Re-explore a node by forking the graph at the checkpoint just before it ran.

    Finds the LangGraph snapshot where *node_name* (or its parent subgraph) is
    in ``snapshot.next``, then calls ``ainvoke(None, config=snapshot.config)``
    to create a new branch from that fork point.

    For inner subgraph nodes (``parent_node_id`` is set in the DB), falls back
    to the snapshot where the parent subgraph is in ``next``.

    Args:
        thread_id: LangGraph thread UUID.
        node_id:   Node execution ID in the format ``{thread_id}:{node_name}``.

    Returns:
        Updated :class:`QueryResponse` with ``status='running'``.
    """
    from fastapi import HTTPException
    from backend.langgraph.compiled import get_compiled_graph
    from backend.langgraph.lifecycle.errors import (
        LIFECYCLE_CHECKPOINT_NOT_FOUND,
        LIFECYCLE_NODE_NOT_FOUND,
    )

    node_name = node_id.split(":", 1)[1] if ":" in node_id else node_id

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            "SELECT parent_node_id FROM fin_agents.nodes"
            " WHERE node_id = %s AND thread_id = %s",
            (node_id, thread_id),
        )
        row = await cur.fetchone()

    if row is None:
        logger.error(
            "[%s] re_explore_node: node not found node_id=%s thread_id=%s",
            LIFECYCLE_NODE_NOT_FOUND, node_id, thread_id,
        )
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    parent_node_id: str | None = row["parent_node_id"]
    parent_node_name: str | None = (
        parent_node_id.split(":", 1)[1]
        if parent_node_id and ":" in parent_node_id
        else None
    )

    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": thread_id}}

    target_snapshot = None
    async for snapshot in graph.aget_state_history(config):
        if node_name in snapshot.next:
            target_snapshot = snapshot
            break
        if parent_node_name and parent_node_name in snapshot.next:
            target_snapshot = snapshot
            break

    if target_snapshot is None:
        logger.error(
            "[%s] re_explore_node: no checkpoint found node_id=%s thread_id=%s",
            LIFECYCLE_CHECKPOINT_NOT_FOUND, node_id, thread_id,
        )
        raise HTTPException(
            status_code=404,
            detail=f"No checkpoint found to re-explore node '{node_name}'",
        )

    # Build fork config, omitting empty checkpoint_ns to avoid checkpointer errors.
    snap_conf = target_snapshot.config.get("configurable", {})
    fork_configurable: dict = {"thread_id": thread_id}
    if snap_conf.get("checkpoint_id"):
        fork_configurable["checkpoint_id"] = snap_conf["checkpoint_id"]
    if snap_conf.get("checkpoint_ns"):
        fork_configurable["checkpoint_ns"] = snap_conf["checkpoint_ns"]
    fork_config = {"configurable": fork_configurable}

    # Reset cancelled node rows so upsert_node can re-activate them on re-run.
    async with raw_conn() as conn:
        if parent_node_id:
            # Inner node: reset the parent subgraph + all its inner nodes.
            await conn.execute(
                _RESET_SUBGRAPH_NODES_TO_PENDING,
                (thread_id, parent_node_id, parent_node_id),
            )
        else:
            # Top-level node: reset only the target node.
            await conn.execute(_RESET_NODE_TO_PENDING, (thread_id, node_id))

        await conn.execute(
            "UPDATE fin_agents.user_queries SET status = 'running'"
            " WHERE thread_id = %s",
            (thread_id,),
        )

    from backend.main_thread import dispatch_graph_run
    # Encode fork_config as JSON in the query field (prefixed) so the executor
    # can distinguish a fork-resume from a normal resume.
    import json as _json
    await dispatch_graph_run(
        thread_id,
        f"__fork__:{_json.dumps(fork_config)}",
    )
    return await get_query_status(thread_id)


__all__ = [
    "ack_query",
    "cancel_node",
    "cancel_query",
    "cancel_task_by_uuid",
    "get_node_executions",
    "get_query_status",
    "get_query_tasks",
    "re_explore_node",
    "resume_query",
    "submit_query",
]
