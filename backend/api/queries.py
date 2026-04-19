"""FastAPI router for user query endpoints.

Mounted at ``/users`` under the parent API router, so full paths are:

    POST /api/v1/users/query
    POST /api/v1/users/query/{thread_id}/cancel
    GET  /api/v1/users/query/{thread_id}
    GET  /api/v1/users/query/{thread_id}/tasks
    GET  /api/v1/users/query/{thread_id}/nodes
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select, update

from backend.db import get_session_factory as _get_session_factory
from backend.graph.models import AgentTask, NodeExecution
from backend.api.registry import running_tasks as _running_tasks
from backend.sse_notifications import emit_done
from backend.streaming.workers.graph_runner import run_graph_async as _run_graph_async
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

    # Dispatch the unified graph as an asyncio task on the FastAPI event loop.
    # The graph routes internally: perf-test trigger → perf_test_streamer;
    # all other queries → fin-analysis pipeline.
    # I/O-bound LLM / DB / Redis calls yield cooperatively so multiple
    # concurrent requests run in parallel without blocking each other.
    task = asyncio.create_task(_run_graph_async(thread_id, request.query))
    _running_tasks[thread_id] = task
    logger.info(
        "[queries] query_accepted thread_id=%s query=%r",
        thread_id,
        request.query[:80],
    )
    return QueryResponse(thread_id=thread_id, status="running")


@router.post("/query/{thread_id}/cancel", response_model=QueryResponse)
async def cancel_query(thread_id: str) -> QueryResponse:
    """Cancel a running query.

    Cancels the asyncio.Task running the graph on the FastAPI event loop.
    The cancel endpoint also takes ownership of the final DB status update
    and ``done`` SSE event so the graph runner does not have to.

    Args:
        thread_id: The UUID returned when the query was submitted.

    Returns:
        ``QueryResponse`` with ``status="cancelled"``.
    """
    task = _running_tasks.pop(thread_id, None)
    if task is None:
        return QueryResponse(thread_id=thread_id, status="cancelled")

    # Update DB and emit done before cancelling so the graph's CancelledError
    # handler does not race with this endpoint.
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

    if not task.done():
        task.cancel()
    logger.info("[queries] task_cancelled thread_id=%s", thread_id)

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
