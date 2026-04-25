"""Streaming session health status query.

Extracted from ``backend.api.stream`` to keep the FastAPI router thin.

:func:`get_session_status` returns a point-in-time health snapshot for a
streaming session: current query status, still-running tasks, time since the
last token, and whether the backend asyncio task is still alive.  It is called
by ``GET /stream/{thread_id}/status`` for frontend stall detection.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from backend.api.registry import is_task_active_any_instance
from backend.db.postgres.engine import get_session_factory
from backend.db.redis.streams.publisher import get_last_token_ms_ago
from backend.graph.models import AgentTask
from backend.streaming.lifecycle.schemas import RunningTaskInfo, StreamingStatusResponse
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)


async def get_session_status(thread_id: str) -> StreamingStatusResponse:
    """Return a health snapshot for the streaming session of *thread_id*.

    Queries PostgreSQL for the current ``user_queries.status`` and all tasks
    still in ``'running'`` state, then checks Redis for the most-recent token
    timestamp and the in-process task-activity registry.

    Called by ``GET /stream/{thread_id}/status`` when the frontend detects a
    stall (no ``token`` event for ≥ 5 seconds).  If ``is_active`` is ``False``
    and ``query_status`` is ``'running'``, the client should treat the session
    as orphaned (backend restarted without emitting ``done``).

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        :class:`~backend.streaming.lifecycle.schemas.StreamingStatusResponse`
        with current streaming health data.
    """
    factory = get_session_factory()
    async with factory() as session:
        uq = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        query_status = uq.status if uq is not None else "unknown"

        result = await session.execute(
            select(AgentTask).where(
                AgentTask.thread_id == thread_id,
                AgentTask.status == "running",
            )
        )
        tasks = result.scalars().all()

    running = [
        RunningTaskInfo(task_id=t.id, task_key=t.task_key, node_name=t.node_name)
        for t in tasks
    ]
    last_token_ms_ago = await get_last_token_ms_ago(thread_id)
    active = await is_task_active_any_instance(thread_id)

    logger.debug(
        "[status] query_status=%s running=%d last_token_ms=%s active=%s thread_id=%s",
        query_status, len(running), last_token_ms_ago, active, thread_id,
    )
    return StreamingStatusResponse(
        thread_id=thread_id,
        query_status=query_status,
        running_tasks=running,
        last_token_ms_ago=last_token_ms_ago,
        is_active=active,
    )


__all__ = ["get_session_status"]
