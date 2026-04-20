"""FastAPI router for user query endpoints.

Mounted at ``/users`` under the parent API router, so full paths are:

    POST /api/v1/users/query
    POST /api/v1/users/query/{thread_id}/cancel
    GET  /api/v1/users/query/{thread_id}
    GET  /api/v1/users/query/{thread_id}/tasks
    GET  /api/v1/users/query/{thread_id}/nodes
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select, update

from backend.db import get_session_factory as _get_session_factory
from backend.db.redis.query_phase import delete_query_phase, set_query_phase
from backend.graph.models import AgentTask, NodeExecution
from backend.api.registry import running_tasks as _running_tasks
from backend.sse_notifications import emit_done
from backend.sse_notifications.perf_test import emit_query_status
from backend.streaming.celery_app import celery_app as _celery_app
from backend.graph.runner import TASK_NAME as _GRAPH_TASK_NAME
from backend.users.auth import ensure_guest
from backend.users.models import UserQuery
from backend.users.schemas import QueryRequest, QueryResponse, SessionStatus, TaskInfo, NodeExecutionInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/query", response_model=QueryResponse)
async def run_query(
    request: QueryRequest,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> QueryResponse:
    """Submit a financial analysis query and begin processing asynchronously.

    Both normal fin-analysis and perf-test queries run as asyncio tasks on the
    FastAPI event loop via the unified LangGraph graph.  The graph routes
    internally based on the query text.  LLM calls, DB I/O, and Redis XADD
    are all I/O-bound coroutines — cooperative multitasking provides real
    parallelism across concurrent requests without gevent/asyncio conflicts.

    Creates a *UserQuery* record and immediately returns the *thread_id*.
    Subscribe to ``GET /api/v1/stream/{thread_id}`` for real-time SSE events
    including a final ``done`` event with the completed status.

    Args:
        request: Query payload with the user's natural-language question.
                 If the query equals ``PERF_TEST_TRIGGER`` the perf-test branch
                 runs; no special parameters are required.
        x_user_token: Guest bearer token from ``X-User-Token`` header.

    Returns:
        ``QueryResponse`` with *thread_id* and ``status="running"``.
    """
    user, _ = await ensure_guest(x_user_token)
    thread_id = str(uuid.uuid4())
    factory = _get_session_factory()

    async with factory() as session:
        session.add(
            UserQuery(
                thread_id=thread_id,
                user_id=user.id,
                query=request.query,
                status="running",
            )
        )
        await session.commit()

    # Dispatch graph execution to a dedicated per-thread Celery queue.
    # Using a per-thread queue gives complete isolation: no two queries share
    # a worker slot, so a slow LLM inference cannot block another query.
    # The queue is registered on-the-fly then cleaned up by the worker when
    # the task finishes.
    queue = f"graph:{thread_id}"
    _celery_app.control.add_consumer(queue, reply=False)
    result = _celery_app.send_task(
        _GRAPH_TASK_NAME,
        kwargs={
            "thread_id": thread_id,
            "query": request.query,
            "perf_total_tokens": request.perf_total_tokens or 100_000,
            "perf_timeout_secs": request.perf_timeout_secs or 60,
            "perf_pub_mode": request.perf_pub_mode or "browser",
        },
        queue=queue,
    )
    _running_tasks[thread_id] = result
    logger.info(
        "[queries] query_accepted thread_id=%s celery_task_id=%s query=%r",
        thread_id,
        result.id,
        request.query[:80],
    )

    # Store phase in Redis immediately so late-connecting SSE clients can
    # recover the current state via _replay_existing even if they missed the
    # pg_notify event.  pg_notify is a best-effort delivery for live clients.
    await set_query_phase(thread_id, "received")
    await emit_query_status(thread_id, "received")

    return QueryResponse(thread_id=thread_id, status="running")


@router.post("/query/{thread_id}/cancel", response_model=QueryResponse)
async def cancel_query(thread_id: str) -> QueryResponse:
    """Cancel a running query.

    Revokes the Celery task running the graph worker.  The cancel endpoint
    also takes ownership of the final DB status update and ``done`` SSE event
    so the graph runner does not have to.

    Args:
        thread_id: The UUID returned when the query was submitted.

    Returns:
        ``QueryResponse`` with ``status="cancelled"``.
    """
    result = _running_tasks.pop(thread_id, None)
    if result is None:
        return QueryResponse(thread_id=thread_id, status="cancelled")

    # Update DB and emit done before revoking so there is no race between the
    # worker's completion path and the cancel endpoint.
    factory = _get_session_factory()
    async with factory() as session:
        await session.execute(
            update(UserQuery)
            .where(UserQuery.thread_id == thread_id)
            .values(status="cancelled")
        )
        await session.execute(
            update(AgentTask)
            .where(AgentTask.thread_id == thread_id, AgentTask.status == "running")
            .values(status="cancelled")
        )
        await session.commit()
    await emit_done(thread_id, "cancelled", "Query cancelled by user")
    await delete_query_phase(thread_id)

    # Revoke the Celery task — terminate=True sends SIGTERM to the worker process.
    if not result.ready():
        result.revoke(terminate=True, signal="SIGTERM")
    logger.info("[queries] task_cancelled thread_id=%s celery_task_id=%s", thread_id, result.id)

    return QueryResponse(thread_id=thread_id, status="cancelled")


@router.get("/query/{thread_id}", response_model=QueryResponse)
async def get_query_status(thread_id: str) -> QueryResponse:
    """Get the status of a previously submitted query.

    Args:
        thread_id: The UUID returned when the query was submitted.

    Returns:
        ``QueryResponse`` reflecting the current *status* and any *error*.
    """
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Query not found")

    return QueryResponse(
        thread_id=row.thread_id,
        status=row.status,
        report=row.answer,
        error=row.error,
    )


@router.get("/query/{thread_id}/tasks", response_model=SessionStatus)
async def get_query_tasks(thread_id: str) -> SessionStatus:
    """Return the query record and all its agent sub-tasks.

    Used by clients to discover active task IDs, node names, and statuses so
    they can correlate streaming events (received via the SSE endpoint) back
    to specific work items.

    Args:
        thread_id: The UUID returned when the query was submitted.

    Returns:
        ``SessionStatus`` containing the query status and a list of
        ``TaskInfo`` records — one per sub-task across all nodes.
    """
    factory = _get_session_factory()
    async with factory() as session:
        uq_result = await session.execute(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        uq_row = uq_result.scalar_one_or_none()
        if not uq_row:
            raise HTTPException(status_code=404, detail="Query not found")

        tasks_result = await session.execute(
            select(AgentTask)
            .where(AgentTask.thread_id == thread_id)
            .order_by(AgentTask.created_at)
        )
        task_rows = tasks_result.scalars().all()

    return SessionStatus(
        thread_id=thread_id,
        user_query_id=uq_row.id,
        status=uq_row.status,
        tasks=[
            TaskInfo(
                id=t.id,
                thread_id=t.thread_id,
                node_execution_id=t.node_execution_id,
                node_name=t.node_name,
                task_key=t.task_key,
                status=t.status,
                input=t.input,
                output=t.output,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
            for t in task_rows
        ],
    )


@router.get("/query/{thread_id}/nodes", response_model=list[NodeExecutionInfo])
async def get_node_executions(thread_id: str) -> list[NodeExecutionInfo]:
    """Return node-level input/output snapshots for a thread.

    Each entry corresponds to one node invocation and contains the full
    ``input`` state fed into the node and the ``output`` state diff it
    returned.  Used by the UI to show per-node I/O in the pipeline graph.

    Args:
        thread_id: The UUID returned when the query was submitted.

    Returns:
        List of :class:`NodeExecutionInfo` ordered by execution start time.
    """
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(NodeExecution)
            .where(NodeExecution.thread_id == thread_id)
            .order_by(NodeExecution.started_at)
        )
        rows = result.scalars().all()

    return [
        NodeExecutionInfo(
            id=r.id,
            node_name=r.node_name,
            input=r.input,
            output=r.output,
            started_at=r.started_at,
            elapsed_ms=r.elapsed_ms,
        )
        for r in rows
    ]
