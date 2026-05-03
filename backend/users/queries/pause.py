"""Service logic for pausing a running query.

Pause immediately cancels the running asyncio task (like cancel) but transitions
the DB status to ``'paused'`` instead of ``'cancelled'``, allowing the query to be
resumed later via :func:`~backend.users.queries.resume.resume_query`.

Design
------
The ``interrupt()`` call inside ``mock_analysis_node`` fires BEFORE the 30-second
streaming task starts.  Once auto-approved, there is no further interrupt checkpoint
during the task.  Waiting for the next checkpoint would mean the pause signal is
only consumed after the full task completes (~30 s) — effectively no pause.

Instead, we cancel the asyncio task immediately (same mechanism as ``cancel_query``)
and emit ``done(paused)`` right away.  The ``CancelledError`` propagates through the
running task; the graph runner's ``except CancelledError`` handler runs
``cleanup_thread_session`` only (DB already transitioned here).

On resume, the LangGraph ``AsyncPostgresSaver`` loads the last pre-node checkpoint
(before ``mock_analysis_node`` entered) and re-runs the node from scratch via
``run_resume_async(input=None)``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from backend.api.registry import running_tasks as _running_tasks
from backend.db import get_session_factory as _get_session_factory
from backend.db.redis.session.query_phase import delete_query_phase
from backend.graph.governance import publish_governance_end
from backend.graph.models import AgentTask
from backend.sse_notifications import emit_done, publish_task_lifecycle
from backend.users.models import UserQuery
from backend.users.schemas import QueryResponse

logger = logging.getLogger(__name__)


async def pause_query(thread_id: str) -> QueryResponse:
    """Immediately pause a running query by cancelling its asyncio task.

    Transitions the DB status to ``'paused'`` and emits ``done(paused)``
    atomically, then cancels the local asyncio task so ``CancelledError``
    propagates through the graph runner.  The runner's ``except CancelledError``
    handler performs final cleanup only (DB/SSE already done here).

    Idempotent: calling on an already-paused or non-running query is safe.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        ``QueryResponse`` with ``status="paused"`` when successfully paused,
        or the current status string if the query was not running.
    """
    # Pop the asyncio task first — guards against the race where the runner
    # naturally completes between the DB check and the task.cancel() call.
    local_task = _running_tasks.pop(thread_id, None)

    if local_task is not None and local_task.done():
        logger.info("[pause] pause_skipped_task_already_done thread_id=%s", thread_id)
        return QueryResponse(thread_id=thread_id, status="completed")

    factory = _get_session_factory()
    running_tasks: list = []
    async with factory() as session:
        result = await session.execute(
            update(UserQuery)
            .where(
                UserQuery.thread_id == thread_id,
                UserQuery.status.in_(["running", "received"]),
            )
            .values(status="paused")
            .returning(UserQuery.thread_id)
        )
        claimed = result.fetchone() is not None
        if claimed:
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
                .where(AgentTask.thread_id == thread_id, AgentTask.status == "running")
                .values(status="paused")
            )
        await session.commit()

    if claimed:
        await publish_governance_end(thread_id, reason="paused")
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
        await emit_done(thread_id, "paused", "Query paused by user")
        await delete_query_phase(thread_id)

    # Cancel the local asyncio task after DB + SSE so the runner's CancelledError
    # handler does not attempt a duplicate done emission.
    if local_task is not None and not local_task.done():
        local_task.cancel()

    logger.info(
        "[pause] paused thread_id=%s claimed=%s running_tasks=%d",
        thread_id, claimed, len(running_tasks),
    )
    return QueryResponse(thread_id=thread_id, status="paused" if claimed else "running")
