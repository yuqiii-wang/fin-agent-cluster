"""Service logic for replaying a completed query from a specific node's checkpoint.

LangGraph time-travel replay:
- Walk ``aget_state_history`` to find the checkpoint where *node_name* is in
  ``snapshot.next`` (i.e. the graph state just before that node ran).
- Invoke the graph from that checkpoint via the checkpoint_id in
  ``snapshot.config``.  LangGraph re-runs the target node and all subsequent
  nodes, overwriting future checkpoints in the same thread.

This endpoint is only available when the thread is in a terminal state
(completed, paused, cancelled, failed) — never while running.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select, update

from backend.api.registry import running_tasks as _running_tasks
from backend.db import get_session_factory as _get_session_factory
from backend.users.models import UserQuery
from backend.users.schemas import QueryResponse
from backend.sse_notifications.thread import emit_query_status
from backend.api.errors import API_QUERY_NOT_FOUND, API_QUERY_STATUS_CONFLICT, API_REPLAY_CHECKPOINT_NOT_FOUND

logger = logging.getLogger(__name__)

# Statuses from which replay is allowed.
_REPLAYABLE_STATUSES: frozenset[str] = frozenset({"completed", "paused", "cancelled", "failed"})


async def replay_from_node(thread_id: str, node_name: str) -> QueryResponse:
    """Replay a query from the checkpoint just before *node_name* last ran.

    Walks LangGraph checkpoint history to find the snapshot where
    ``node_name in snapshot.next``, then re-invokes the graph from that
    checkpoint.  All nodes from *node_name* onwards are re-executed; nodes
    before it are replayed from their cached checkpoints (not re-executed).

    The thread must be in a terminal state (completed / paused / cancelled /
    failed).  Returns immediately with ``status="running"`` while the graph
    executes asynchronously in the FastAPI event loop.

    Args:
        thread_id: LangGraph UUID of the query to replay.
        node_name: Name of the graph node to replay from.

    Returns:
        ``QueryResponse`` with ``status="running"`` on success.

    Raises:
        404: Thread not found.
        409: Thread is currently running (cannot replay a live run).
        422: No checkpoint found for *node_name* in the thread's history.
    """
    from fastapi import HTTPException  # noqa: PLC0415

    factory = _get_session_factory()
    async with factory() as session:
        uq = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        if uq is None:
            raise HTTPException(
                status_code=404,
                detail={"code": API_QUERY_NOT_FOUND, "message": f"Thread {thread_id!r} not found."},
            )

        current_status: str = uq.status
        if current_status not in _REPLAYABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": API_QUERY_STATUS_CONFLICT,
                    "message": (
                        f"Cannot replay a thread in status '{current_status}'. "
                        f"Allowed statuses: {sorted(_REPLAYABLE_STATUSES)}"
                    ),
                },
            )

        # Find the checkpoint where node_name is in next.
        try:
            checkpoint_config = await _find_checkpoint_for_node(thread_id, node_name)
        except Exception as _exc:
            logger.exception(
                "[replay] find_checkpoint_error thread_id=%s node_name=%s error=%r",
                thread_id,
                node_name,
                _exc,
            )
            raise
        if checkpoint_config is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": API_REPLAY_CHECKPOINT_NOT_FOUND,
                    "message": (
                        f"No checkpoint found where node '{node_name}' is scheduled to run "
                        f"in thread {thread_id!r}. The node may not have run yet."
                    ),
                },
            )

        # Atomically claim the running transition.
        result = await session.execute(
            update(UserQuery)
            .where(
                UserQuery.thread_id == thread_id,
                UserQuery.status.in_(list(_REPLAYABLE_STATUSES)),
            )
            .values(status="running")
            .returning(UserQuery.thread_id)
        )
        claimed = result.fetchone() is not None
        await session.commit()

    if not claimed:
        logger.info("[replay] replay_claim_missed thread_id=%s", thread_id)
        return QueryResponse(thread_id=thread_id, status="running")

    await emit_query_status(thread_id, "running")

    from backend.graph.runner import run_replay_from_node_async  # noqa: PLC0415

    task = asyncio.get_event_loop().create_task(
        run_replay_from_node_async(thread_id, checkpoint_config),
        name=f"replay:{thread_id}:{node_name}",
    )
    _running_tasks[thread_id] = task

    logger.info(
        "[replay] query_replay_started thread_id=%s node_name=%s",
        thread_id,
        node_name,
    )
    return QueryResponse(thread_id=thread_id, status="running")


async def _find_checkpoint_for_node(thread_id: str, node_name: str) -> dict | None:
    """Walk state history and return the checkpoint config where *node_name* is in ``next``.

    Strategy:
    1. Walk root ``aget_state_history`` and check outer nodes directly.
    2. For each outer snapshot, expand active subgraph tasks via
       ``aget_state(config, subgraphs=True)`` to find subgraph entry-point nodes.
    3. Fallback: walk each subgraph namespace history directly to find
       mid-subgraph checkpoints (e.g. just before ``merge`` ran inside the
       subgraph).  This requires ``checkpointer=True`` on the subgraph so
       per-node checkpoints exist.

    Returns the **most recent** checkpoint config where *node_name* is in
    ``snapshot.next``, or ``None`` if not found.

    Args:
        thread_id: LangGraph thread UUID.
        node_name: Target graph node name.

    Returns:
        The ``config`` dict from the matching ``StateSnapshot``, or ``None``
        if no such checkpoint exists.
    """
    from backend.graph.compiled import get_compiled_graph  # noqa: PLC0415
    from backend.db import raw_conn  # noqa: PLC0415
    from langgraph.types import StateSnapshot  # noqa: PLC0415

    graph = get_compiled_graph()
    root_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    # Pass 1 & 2: walk root history; expand subgraph tasks with subgraphs=True.
    async for snapshot in graph.aget_state_history(root_config):
        # 1. Outer-graph node scheduled next.
        if node_name in (snapshot.next or ()):
            logger.debug(
                "[replay] outer_checkpoint_found thread_id=%s node_name=%s checkpoint_id=%s",
                thread_id,
                node_name,
                snapshot.config.get("configurable", {}).get("checkpoint_id"),
            )
            return snapshot.config

        # 2. Check subgraph entry-point nodes via get_state(subgraphs=True).
        #    Catches the case where the node is the *first* node scheduled
        #    inside an active subgraph task at this outer snapshot.
        expanded = await graph.aget_state(snapshot.config, subgraphs=True)
        for task in expanded.tasks:
            if isinstance(task.state, StateSnapshot) and node_name in (task.state.next or ()):
                logger.debug(
                    "[replay] subgraph_entry_checkpoint_found thread_id=%s node_name=%s "
                    "ns=%s checkpoint_id=%s",
                    thread_id,
                    node_name,
                    task.state.config.get("configurable", {}).get("checkpoint_ns"),
                    task.state.config.get("configurable", {}).get("checkpoint_id"),
                )
                return task.state.config

    # Pass 3: fallback — walk subgraph namespace histories for mid-subgraph
    # checkpoints (e.g. the checkpoint just before ``merge`` ran, which lives
    # in the subgraph's own namespace and is invisible to the root history).
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            "SELECT DISTINCT checkpoint_ns FROM fin_agents.checkpoints WHERE thread_id = %s",
            (thread_id,),
        )
        rows = await cur.fetchall()

    subgraph_namespaces: list[str] = sorted(
        [row["checkpoint_ns"] for row in rows if row["checkpoint_ns"] != ""]
    )

    for ns in subgraph_namespaces:
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns}}
        async for snapshot in graph.aget_state_history(config):
            if node_name in (snapshot.next or ()):
                logger.debug(
                    "[replay] subgraph_ns_checkpoint_found thread_id=%s node_name=%s "
                    "ns=%s checkpoint_id=%s",
                    thread_id,
                    node_name,
                    ns,
                    snapshot.config.get("configurable", {}).get("checkpoint_id"),
                )
                return snapshot.config

    logger.warning(
        "[replay] checkpoint_not_found thread_id=%s node_name=%s",
        thread_id,
        node_name,
    )
    return None
