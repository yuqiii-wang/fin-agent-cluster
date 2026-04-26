"""Service logic for cancelling a running or received query."""

from __future__ import annotations

import logging

from sqlalchemy import update

from backend.api.registry import running_tasks as _running_tasks
from backend.db import get_session_factory as _get_session_factory
from backend.db.redis.session.cancel_signal import publish_cancel
from backend.db.redis.session.query_phase import delete_query_phase
from backend.graph.models import AgentTask
from backend.sse_notifications import emit_done
from backend.users.models import UserQuery
from backend.users.schemas import QueryResponse

logger = logging.getLogger(__name__)


async def cancel_query(thread_id: str, reason: str = "user") -> QueryResponse:
    """Cancel a running or received query.

    Atomically claims the cancel transition in the DB, then emits the ``done``
    SSE event and publishes a Redis cancel signal so the owning instance can
    stop its asyncio.Task.  Idempotent — if the query is already in a terminal
    state the cancel is silently skipped.

    Args:
        thread_id: The UUID returned when the query was submitted.
        reason:    Cancellation reason — ``"user"`` for explicit user action,
                   ``"timeout"`` when the client-side safety timeout fired.

    Returns:
        ``QueryResponse`` with ``status`` matching *reason*.
    """
    # Pop the local asyncio.Task — may be None if this instance does not own the query.
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
