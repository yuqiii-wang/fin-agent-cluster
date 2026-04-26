"""FastAPI router for user query endpoints.

Mounted at ``/users`` under the parent API router, so full paths are:

    POST /api/v1/users/query
    POST /api/v1/users/query/{thread_id}/ack
    POST /api/v1/users/query/{thread_id}/cancel
    GET  /api/v1/users/query/{thread_id}
    GET  /api/v1/users/query/{thread_id}/tasks
    GET  /api/v1/users/query/{thread_id}/nodes

Business logic lives in :mod:`backend.users.queries`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header

from backend.users.auth import ensure_guest
from backend.users.queries import (
    ack_query,
    cancel_query,
    get_node_executions,
    get_query_status,
    get_query_tasks,
    perf_stable_signal,
    submit_query,
)
from backend.users.schemas import NodeExecutionInfo, QueryRequest, QueryResponse, SessionStatus

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/query", response_model=QueryResponse)
async def run_query(
    request: QueryRequest,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> QueryResponse:
    """Accept a financial analysis query and await client ACK before processing."""
    user, _ = await ensure_guest(x_user_token)
    return await submit_query(request, user)


@router.post("/query/{thread_id}/ack", response_model=QueryResponse)
async def ack_query_route(
    thread_id: str,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> QueryResponse:
    """Acknowledge a received query, starting LangGraph execution."""
    await ensure_guest(x_user_token)
    return await ack_query(thread_id)


@router.post("/query/{thread_id}/cancel", response_model=QueryResponse)
async def cancel_query_route(
    thread_id: str,
    reason: str = "user",
) -> QueryResponse:
    """Cancel a running or received query."""
    return await cancel_query(thread_id, reason)


@router.post("/query/{thread_id}/perf-stable", status_code=200)
async def perf_stable_route(thread_id: str) -> dict[str, str]:
    """Signal that the concurrency perf stream has reached stable TPS."""
    return await perf_stable_signal(thread_id)


@router.get("/query/{thread_id}", response_model=QueryResponse)
async def get_query_status_route(thread_id: str) -> QueryResponse:
    """Get the current status of a submitted query."""
    return await get_query_status(thread_id)


@router.get("/query/{thread_id}/tasks", response_model=SessionStatus)
async def get_query_tasks_route(thread_id: str) -> SessionStatus:
    """Return the query record and all its agent sub-tasks."""
    return await get_query_tasks(thread_id)


@router.get("/query/{thread_id}/nodes", response_model=list[NodeExecutionInfo])
async def get_node_executions_route(thread_id: str) -> list[NodeExecutionInfo]:
    """Return node-level input/output snapshots for a thread."""
    return await get_node_executions(thread_id)
