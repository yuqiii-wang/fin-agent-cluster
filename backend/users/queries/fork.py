"""Service logic for forking a query thread from a specific node's checkpoint.

LangGraph fork vs replay
------------------------
**Replay** (``replay_from_node``) — Re-invokes the *same* thread from a historical
checkpoint.  Future checkpoints in that thread are overwritten.  The original
run history is gone from that point onward.  Best for: re-testing the same
query with the same parameters.

**Fork** (``fork_from_node``) — Creates an *independent* new thread that starts
from the checkpoint where *node_name* would have run.  The source thread is not
touched.  The new thread has its own ``thread_id`` and its own ``user_queries``
row.  Best for: exploring a divergent branch without losing the original result.

Implementation
--------------
LangGraph's ``AsyncPostgresSaver`` stores checkpoints with the key
``(thread_id, checkpoint_ns, checkpoint_id)``.  To fork, we:

1. Walk ``aget_state_history`` on the source thread to find the checkpoint
   where ``node_name in snapshot.next`` (same lookup as replay).
2. Read the full checkpoint blob (values + writes) via ``aget_state``.
3. Apply that state onto a new thread using ``graph.aupdate_state``, which
   writes a *new* checkpoint row keyed to the new ``thread_id``.
4. Atomically insert a new ``user_queries`` row with the new ``thread_id``
   and status = "received".
5. Launch the graph from the new thread (``run_graph_async``-style entrypoint).
   All nodes from *node_name* onwards execute fresh; nodes before it are
   re-run (their ``@task`` caches are *not* transferred — a known trade-off of
   forking vs. replaying).

The caller receives the new ``thread_id`` so it can subscribe to the new
Centrifugo channel and display the forked execution independently.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import insert, select

from backend.api.errors import (
    API_QUERY_NOT_FOUND,
    API_QUERY_STATUS_CONFLICT,
    API_FORK_CHECKPOINT_NOT_FOUND,
)
from backend.api.registry import running_tasks as _running_tasks
from backend.db import get_session_factory as _get_session_factory
from backend.users.models import UserQuery
from backend.users.schemas import ForkFromNodeResponse
from backend.sse_notifications.thread import emit_query_status

logger = logging.getLogger(__name__)

# Forking is allowed from any terminal state (same as replay).
_FORKABLE_STATUSES: frozenset[str] = frozenset({"completed", "paused", "cancelled", "failed"})


async def fork_from_node(source_thread_id: str, node_name: str) -> ForkFromNodeResponse:
    """Fork a query thread from the checkpoint just before *node_name* last ran.

    Creates a new independent thread that starts from the same graph state as
    the source thread had just before *node_name* ran.  The source thread is
    not modified.

    Args:
        source_thread_id: LangGraph UUID of the source thread.
        node_name:        Name of the graph node to fork from.

    Returns:
        ``ForkFromNodeResponse`` with the new ``thread_id`` and
        ``status="running"`` on success.

    Raises:
        404: Source thread not found.
        409: Source thread is currently running (cannot fork a live run).
        422: No checkpoint found for *node_name* in the source thread's history.
    """
    from fastapi import HTTPException  # noqa: PLC0415

    factory = _get_session_factory()
    async with factory() as session:
        uq = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == source_thread_id)
        )
        if uq is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": API_QUERY_NOT_FOUND,
                    "message": f"Thread {source_thread_id!r} not found.",
                },
            )

        current_status: str = uq.status
        if current_status not in _FORKABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": API_QUERY_STATUS_CONFLICT,
                    "message": (
                        f"Cannot fork a thread in status '{current_status}'. "
                        f"Allowed statuses: {sorted(_FORKABLE_STATUSES)}"
                    ),
                },
            )

        source_query: str = uq.query
        source_user_id: str | None = uq.user_id

    # Find the checkpoint in the source thread where node_name is in next.
    try:
        fork_state = await _load_fork_state(source_thread_id, node_name)
    except Exception as exc:
        logger.exception(
            "[fork] load_state_error source_thread_id=%s node_name=%s error=%r",
            source_thread_id,
            node_name,
            exc,
        )
        raise

    if fork_state is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": API_FORK_CHECKPOINT_NOT_FOUND,
                "message": (
                    f"No checkpoint found where node '{node_name}' is scheduled to run "
                    f"in thread {source_thread_id!r}."
                ),
            },
        )

    # Create a new thread ID for the fork.
    new_thread_id = str(uuid.uuid4())

    # Apply the source state onto the new thread (writes a new checkpoint row).
    new_config = await _apply_state_to_new_thread(new_thread_id, fork_state, node_name)

    # Insert the new user_queries row for the forked thread.
    async with factory() as session:
        await session.execute(
            insert(UserQuery).values(
                thread_id=new_thread_id,
                user_id=source_user_id,
                query=source_query,
                status="running",
                created_at=datetime.utcnow(),
            )
        )
        await session.commit()

    await emit_query_status(new_thread_id, "running")

    from backend.graph.runner import run_fork_from_checkpoint_async  # noqa: PLC0415

    task = asyncio.get_event_loop().create_task(
        run_fork_from_checkpoint_async(new_thread_id, new_config),
        name=f"fork:{source_thread_id}:{new_thread_id}:{node_name}",
    )
    _running_tasks[new_thread_id] = task

    logger.info(
        "[fork] fork_started source_thread_id=%s new_thread_id=%s node_name=%s",
        source_thread_id,
        new_thread_id,
        node_name,
    )
    return ForkFromNodeResponse(
        source_thread_id=source_thread_id,
        new_thread_id=new_thread_id,
        node_name=node_name,
        status="running",
    )


async def _load_fork_state(source_thread_id: str, node_name: str):
    """Find and return the state snapshot for the fork point.

    Args:
        source_thread_id: Source thread UUID.
        node_name:        Target node name — fork starts just before this node.

    Returns:
        The ``StateSnapshot`` at the fork point, or ``None`` if not found.
    """
    from backend.graph.compiled import get_compiled_graph  # noqa: PLC0415
    from backend.db import raw_conn  # noqa: PLC0415

    graph = get_compiled_graph()

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            "SELECT DISTINCT checkpoint_ns FROM fin_agents.checkpoints WHERE thread_id = %s",
            (source_thread_id,),
        )
        rows = await cur.fetchall()

    namespaces: list[str] = sorted(
        [row["checkpoint_ns"] for row in rows],
        key=lambda ns: (0 if ns == "" else 1, ns),
    )

    for ns in namespaces:
        config = {"configurable": {"thread_id": source_thread_id, "checkpoint_ns": ns}}
        async for snapshot in graph.aget_state_history(config):
            if node_name in (snapshot.next or ()):
                logger.debug(
                    "[fork] fork_point_found source_thread_id=%s node_name=%s ns=%s checkpoint_id=%s",
                    source_thread_id,
                    node_name,
                    ns,
                    snapshot.config.get("configurable", {}).get("checkpoint_id"),
                )
                return snapshot

    logger.warning(
        "[fork] fork_point_not_found source_thread_id=%s node_name=%s",
        source_thread_id,
        node_name,
    )
    return None


async def _apply_state_to_new_thread(
    new_thread_id: str,
    snapshot,
    node_name: str,
) -> dict:
    """Apply the snapshot's values onto a new thread via ``graph.aupdate_state``.

    Uses ``as_node=node_name`` so LangGraph positions the new thread at the
    same point in the graph (i.e. ``node_name`` is the next node to run).

    Args:
        new_thread_id: New thread UUID.
        snapshot:      ``StateSnapshot`` from the source thread.
        node_name:     The node that should run next in the forked thread.

    Returns:
        The new thread's config dict (with checkpoint_id) for launching the run.
    """
    from backend.graph.compiled import get_compiled_graph  # noqa: PLC0415

    graph = get_compiled_graph()
    new_config = {
        "configurable": {
            "thread_id": new_thread_id,
            "checkpoint_ns": "",
        }
    }
    # aupdate_state writes the snapshot values as the current state of the new
    # thread and returns the updated config (including the new checkpoint_id).
    updated_config = await graph.aupdate_state(
        new_config,
        snapshot.values,
        as_node=node_name,
    )
    return updated_config
