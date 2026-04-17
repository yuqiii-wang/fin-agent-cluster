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

from backend.db import checkpointer, get_session_factory as _get_session_factory
from backend.graph import build_graph
from backend.graph.models import AgentTask, NodeExecution
from backend.api.registry import running_tasks as _running_tasks
from backend.graph.utils.task_stream import emit_done
from backend.users.auth import ensure_guest
from backend.users.models import UserQuery
from backend.users.schemas import QueryRequest, QueryResponse, SessionStatus, TaskInfo, NodeExecutionInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


async def _run_graph(thread_id: str, query: str) -> None:
    """Background coroutine: execute the LangGraph workflow and emit a ``done`` event.

    Runs after the POST response has been returned.  Emits ``done``
    (completed or failed) via ``pg_notify`` so SSE subscribers can finalise
    the UI state.

    Args:
        thread_id: LangGraph UUID already persisted to the DB.
        query:     Raw user query string.
    """
    factory = _get_session_factory()
    # Brief yield so the SSE client has time to connect and register LISTEN
    # before the first pg_notify fires.  LLM cold-start takes seconds; 1 s is
    # enough for TCP + HTTP handshake on a local connection.
    await asyncio.sleep(1)
    try:
        async with checkpointer() as cp:
            graph = build_graph().compile(checkpointer=cp)
            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                }
            }
            initial_state = {
                "query": query,
                "thread_id": thread_id,
                "ticker": "",
                "market_data": "",
                "fundamental_analysis": "",
                "technical_analysis": "",
                "risk_assessment": "",
                "report": "",
                "steps": [],
            }
            final_state = await graph.ainvoke(initial_state, config)
            report = final_state.get("market_data", "No report generated")

        async with factory() as session:
            await session.execute(
                update(UserQuery)
                .where(UserQuery.thread_id == thread_id)
                .values(status="completed", answer=report, completed_at=datetime.utcnow())
            )
            await session.commit()

        await emit_done(thread_id, "completed", report)

    except asyncio.CancelledError:
        logger.info("Query %s cancelled by user", thread_id)
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

    except Exception as exc:
        logger.exception("Error processing query %s: %s", thread_id, exc)
        async with factory() as session:
            await session.execute(
                update(UserQuery)
                .where(UserQuery.thread_id == thread_id)
                .values(status="failed", error=str(exc))
            )
            await session.commit()
        await emit_done(thread_id, "failed", str(exc))

    finally:
        _running_tasks.pop(thread_id, None)


@router.post("/query", response_model=QueryResponse)
async def run_query(
    request: QueryRequest,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> QueryResponse:
    """Submit a financial analysis query and begin processing asynchronously.

    Creates a *UserQuery* record and immediately returns the *thread_id*.
    Graph execution runs in the background; subscribe to
    ``GET /api/v1/stream/{thread_id}`` for real-time SSE events including a
    final ``done`` event with the completed status.

    Args:
        request: Query payload containing the user's natural-language question.
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

    task = asyncio.create_task(_run_graph(thread_id, request.query))
    _running_tasks[thread_id] = task
    return QueryResponse(thread_id=thread_id, status="running")


@router.post("/query/{thread_id}/cancel", response_model=QueryResponse)
async def cancel_query(thread_id: str) -> QueryResponse:
    """Cancel a running query and notify SSE subscribers.

    Cancels the background asyncio task for *thread_id*, marks the
    ``UserQuery`` and all its running ``AgentTask`` rows as ``cancelled`` in
    the DB, and emits a ``done`` SSE event so the frontend can update.

    Args:
        thread_id: The UUID returned when the query was submitted.

    Returns:
        ``QueryResponse`` with ``status="cancelled"``.

    Raises:
        HTTPException 404: If *thread_id* is not found in the running-tasks
            registry (query already finished or was never started).
    """
    task = _running_tasks.get(thread_id)
    if task is None or task.done():
        raise HTTPException(status_code=404, detail="No running query found for this thread_id")
    task.cancel()
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
