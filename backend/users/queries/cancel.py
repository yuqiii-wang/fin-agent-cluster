"""Service logic for cancelling a running or received query, or a specific node/task."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from backend.api.registry import running_tasks as _running_tasks
from backend.db import get_session_factory as _get_session_factory
from backend.db.redis.session.cancel_signal import publish_cancel
from backend.db.redis.session.query_phase import delete_query_phase
from backend.graph.governance import (
    publish_governance_end,
    publish_node_cancel,
    publish_task_cancel,
    request_node_cancel,
    request_task_cancel,
)
from backend.graph.models import AgentTask, NodeExecution
from backend.sse_notifications import emit_done, emit_node_status, publish_task_lifecycle
from backend.users.models import UserQuery
from backend.users.schemas import QueryResponse

logger = logging.getLogger(__name__)


async def cancel_query(thread_id: str, reason: str = "user") -> QueryResponse:
    """Cancel a running or received query.

    Atomically claims the cancel transition in the DB, then emits the ``done``
    SSE event and publishes a Redis cancel signal so the owning instance can
    stop its asyncio.Task.  Idempotent -- if the query is already in a terminal
    state the cancel is silently skipped.

    After claiming the cancel transition, traverses the governance registry to
    emit ``stream_stopped`` for every live stream under this thread so the
    frontend receives a terminal event for each in-flight stream.

    Args:
        thread_id: The UUID returned when the query was submitted.
        reason:    Cancellation reason -- ``"user"`` for explicit user action,
                   ``"timeout"`` when the client-side safety timeout fired.

    Returns:
        ``QueryResponse`` with ``status`` matching *reason*.
    """
    # Pop the local asyncio.Task -- may be None if this instance does not own the query.
    local_task = _running_tasks.pop(thread_id, None)

    # Guard: if the local task already finished naturally the runner claimed the
    # done transition; return early to avoid a duplicate done event.
    if local_task is not None and local_task.done():
        logger.info(
            "[cancel] cancel_skipped_already_done thread_id=%s reason=%s",
            thread_id,
            reason,
        )
        return QueryResponse(thread_id=thread_id, status="completed")

    done_status = reason if reason == "timeout" else "cancelled"
    db_status = "cancelled"

    # Atomically claim the cancel transition.  WHERE status IN ('running', 'received')
    # ensures only one writer (this endpoint or the graph runner) emits done.
    factory = _get_session_factory()
    running_tasks: list = []
    async with factory() as session:
        result_update = await session.execute(
            update(UserQuery)
            .where(
                UserQuery.thread_id == thread_id,
                UserQuery.status.in_(["running", "received"]),
            )
            .values(status=db_status)
            .returning(UserQuery.thread_id)
        )
        claimed = result_update.fetchone() is not None
        if claimed:
            # Collect running tasks BEFORE the bulk update so we can emit
            # terminal events in the correct order (before `done`).
            tasks_result = await session.execute(
                select(AgentTask.task_id, AgentTask.task_name, AgentTask.node_name)
                .where(
                    AgentTask.thread_id == thread_id,
                    AgentTask.status == "running",
                )
            )
            running_tasks = tasks_result.fetchall()
            await session.execute(
                update(AgentTask)
                .where(
                    AgentTask.thread_id == thread_id,
                    AgentTask.status == "running",
                )
                .values(status=db_status)
            )
        await session.commit()

    if claimed:
        # Propagate cancellation down the governance hierarchy so every live
        # stream under this thread receives a stream_stopped event.
        await publish_governance_end(thread_id, reason=done_status)
        # Emit task cancelled events BEFORE done so the frontend receives them
        # while the WebSocket is still open.  The bulk DB update above already
        # marked the tasks as cancelled; we only need the SSE publish here.
        _updated_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        for row in running_tasks:
            await publish_task_lifecycle(thread_id, {
                "event": "cancelled",
                "task_id": row.task_id,
                "node_name": row.node_name,
                "task_name": row.task_name,
                "output": {},
                "updated_at_ms": _updated_at_ms,
            })
        await emit_done(thread_id, done_status, "Query cancelled by user")
        await delete_query_phase(thread_id)

    # Publish Redis cancel signal so the owning instance cancels its asyncio.Task.
    await publish_cancel(thread_id, reason)

    # Cancel local task if this instance owns it (no-op when task is on another instance).
    if local_task is not None and not local_task.done():
        local_task.cancel()

    logger.info(
        "[cancel] task_cancelled thread_id=%s reason=%s claimed=%s",
        thread_id,
        reason,
        claimed,
    )
    return QueryResponse(thread_id=thread_id, status=done_status)


async def cancel_node(thread_id: str, node_id: str) -> dict:
    """Cancel a specific node and all tasks running under it.

    Sets the Redis governance cancel signal for the node, cascades cancel
    signals to every task registered under it (Redis signal + in-process
    streaming-loop signal), emits ``stream_stopped`` for every live stream,
    updates the corresponding PG ``node_executions`` row to ``'cancelled'``,
    and emits a ``node_status`` SSE event.

    Args:
        thread_id: Top-level thread UUID.
        node_id:   The ``node_uuid`` that identifies the node execution.

    Returns:
        Dict with ``thread_id``, ``node_id``, and ``status``.
    """
    await request_node_cancel(thread_id, node_id)

    factory = _get_session_factory()
    async with factory() as session:
        await session.execute(
            update(NodeExecution)
            .where(
                NodeExecution.thread_id == thread_id,
                NodeExecution.node_uuid == node_id,
                NodeExecution.status == "running",
            )
            .values(status="cancelled")
        )
        # NOTE: AgentTask rows are updated (with SSE events) by cancel_query below.
        # Do NOT do a silent bulk update here — that would consume the running status
        # before cancel_query can SELECT and emit the cancelled events.
        await session.commit()

    # Cascade: signal all tasks + emit stream_stopped for live streams under this node.
    await publish_node_cancel(thread_id, node_id)

    await emit_node_status(thread_id, node_id, "", "cancelled")

    # LangGraph does not support per-node cancellation — the graph runs as a
    # single asyncio.Task.  Cancel the whole query so the graph execution stops
    # and the checkpoint is preserved for an optional resume.  The atomic claim
    # in cancel_query prevents a duplicate done event if the query was already
    # transitioning to a terminal state.
    await cancel_query(thread_id, reason="user")

    logger.info(
        "[cancel] node_cancelled thread_id=%s node_id=%s", thread_id, node_id
    )
    return {"thread_id": thread_id, "node_id": node_id, "status": "cancelled"}


async def cancel_task_by_uuid(thread_id: str, task_id: str, node_id: str = "") -> dict:
    """Cancel a specific task by its governance UUID.

    Sets the Redis governance cancel signal for the task, signals any
    in-process streaming loop via :func:`publish_task_cancel`, and emits
    ``stream_stopped`` for every live stream under the task.  No PG row update
    is performed here because ``task_id`` is stored only in the
    ``extra_payload`` JSON, not as a dedicated indexed column; the running task
    itself is responsible for updating its own PG row upon detecting the cancel
    signal.

    Args:
        thread_id:  Top-level thread UUID.
        task_id:  Governance-level task UUID used as Redis cancel key.
        node_id:    Optional parent node UUID for governance inheritance checks.

    Returns:
        Dict with ``thread_id``, ``task_id``, and ``status``.
    """
    await request_task_cancel(thread_id, task_id, node_id=node_id)
    # Cascade: signal in-process streaming loop + emit stream_stopped for live streams.
    await publish_task_cancel(thread_id, node_id, task_id)

    logger.info(
        "[cancel] task_cancel_signal_sent thread_id=%s task_id=%s", thread_id, task_id
    )
    return {"thread_id": thread_id, "task_id": task_id, "status": "cancelling"}
