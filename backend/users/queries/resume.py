"""Service logic for resuming a cancelled or failed query from the last LangGraph checkpoint."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select, update

from backend.api.registry import running_tasks as _running_tasks
from backend.db import get_session_factory as _get_session_factory
from backend.users.models import UserQuery
from backend.users.schemas import QueryResponse
from backend.sse_notifications.thread import emit_query_status

logger = logging.getLogger(__name__)


async def resume_query(thread_id: str) -> QueryResponse:
    """Resume a previously cancelled or failed query from its last LangGraph checkpoint.

    Dispatches to :func:`~backend.graph.runner.run_resume_async` which passes
    ``input=None`` to LangGraph so it loads the last pre-node checkpoint and
    re-runs the interrupted node from its beginning.

    Args:
        thread_id: LangGraph UUID of the query to resume.

    Returns:
        ``QueryResponse`` with ``status="running"`` on success, or the
        current status string when the query is not in a resumable state.
    """
    factory = _get_session_factory()
    async with factory() as session:
        uq = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        if uq is None:
            logger.warning("[resume] thread_not_found thread_id=%s", thread_id)
            return QueryResponse(thread_id=thread_id, status="not_found")

        prior_status: str = uq.status
        if prior_status not in ("cancelled", "failed"):
            logger.info(
                "[resume] resume_skipped_not_resumable thread_id=%s status=%s",
                thread_id, prior_status,
            )
            return QueryResponse(thread_id=thread_id, status=prior_status)

        result = await session.execute(
            update(UserQuery)
            .where(
                UserQuery.thread_id == thread_id,
                UserQuery.status.in_(["cancelled", "failed"]),
            )
            .values(status="running")
            .returning(UserQuery.thread_id)
        )
        claimed = result.fetchone() is not None
        await session.commit()

    if not claimed:
        logger.info("[resume] resume_claim_missed thread_id=%s", thread_id)
        return QueryResponse(thread_id=thread_id, status="running")

    await emit_query_status(thread_id, "running")

    from backend.graph.runner import run_resume_async  # noqa: PLC0415
    task = asyncio.get_event_loop().create_task(
        run_resume_async(thread_id), name=f"resume:{thread_id}"
    )
    _running_tasks[thread_id] = task

    logger.info("[resume] query_resumed thread_id=%s prior_status=%s", thread_id, prior_status)
    return QueryResponse(thread_id=thread_id, status="running")

logger = logging.getLogger(__name__)


async def resume_query(thread_id: str) -> QueryResponse:
    """Resume a previously cancelled or paused query from its last LangGraph checkpoint.

    Dispatches to :func:`~backend.graph.runner.run_resume_async` for all
    resumable statuses (``'paused'``, ``'cancelled'``, ``'failed'``).
    ``run_resume_async`` passes ``input=None`` to LangGraph so it loads the
    last pre-node checkpoint and re-runs the interrupted node from its beginning.
    Pause is handled by direct ``asyncio.Task.cancel()`` (same as cancel), so
    the checkpoint is always a pre-node boundary — ``Command(resume=True)`` is
    never needed.

    Args:
        thread_id: LangGraph UUID of the query to resume.

    Returns:
        ``QueryResponse`` with ``status="running"`` on success, or the
        current status string when the query is not in a resumable state.
    """
    factory = _get_session_factory()
    async with factory() as session:
        # Guard: only resume if the query is in a terminal-but-resumable state.
        uq = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        if uq is None:
            logger.warning("[resume] thread_not_found thread_id=%s", thread_id)
            return QueryResponse(thread_id=thread_id, status="not_found")

        prior_status: str = uq.status
        if prior_status not in ("cancelled", "failed", "paused"):
            logger.info(
                "[resume] resume_skipped_not_terminal thread_id=%s status=%s",
                thread_id, prior_status,
            )
            return QueryResponse(thread_id=thread_id, status=prior_status)

        # Atomically reclaim the running transition.
        result = await session.execute(
            update(UserQuery)
            .where(
                UserQuery.thread_id == thread_id,
                UserQuery.status.in_(["cancelled", "failed", "paused"]),
            )
            .values(status="running")
            .returning(UserQuery.thread_id)
        )
        claimed = result.fetchone() is not None
        await session.commit()

    if not claimed:
        logger.info("[resume] resume_claim_missed thread_id=%s", thread_id)
        return QueryResponse(thread_id=thread_id, status="running")

    await emit_query_status(thread_id, "running")

    # Lazy import to avoid circular dependency with runner.py.
    from backend.graph.runner import run_resume_async  # noqa: PLC0415
    runner_coro = run_resume_async(thread_id)
    task_name = f"resume:{thread_id}"

    task = asyncio.get_event_loop().create_task(runner_coro, name=task_name)
    _running_tasks[thread_id] = task

    logger.info("[resume] query_resumed thread_id=%s prior_status=%s", thread_id, prior_status)
    return QueryResponse(thread_id=thread_id, status="running")

