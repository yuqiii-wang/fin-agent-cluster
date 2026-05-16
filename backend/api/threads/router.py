"""FastAPI router for thread-scoped query, node, task, and stream endpoints.

All endpoints are nested under ``/threads/{thread_id}`` to enforce the full
governance hierarchy on every call.

Top-level (no thread_id)
------------------------
POST /api/v1/threads/query              — submit a new query and get thread_id

Thread-level
------------
GET  /api/v1/threads/{thread_id}                         — query status
POST /api/v1/threads/{thread_id}/ack                      — ACK and start execution
POST /api/v1/threads/{thread_id}/cancel                   — cancel entire thread
POST /api/v1/threads/{thread_id}/resume                   — resume from checkpoint

Node-level
----------
GET  /api/v1/threads/{thread_id}/nodes                          — all node executions
POST /api/v1/threads/{thread_id}/nodes/{node_id}/cancel         — cancel a node
POST /api/v1/threads/{thread_id}/nodes/{node_id}/re-explore     — fork at pre-node checkpoint

Version-level
-------------
GET  /api/v1/threads/{thread_id}/version/{version_id}           — fork node + branch nodes for version

Task-level
----------
GET  /api/v1/threads/{thread_id}/tasks                    — all tasks in thread
POST /api/v1/threads/{thread_id}/tasks/{task_id}/cancel  — cancel a task
GET  /api/v1/threads/{thread_id}/tasks/{task_id}         — single task status

Business logic lives in :mod:`backend.users.queries`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Path

from backend.users.auth import ensure_guest
from backend.users.queries import (
    ack_query,
    cancel_query,
    get_query_status,
    resume_query,
    submit_query,
)
from backend.users.schemas import QueryRequest, QueryResponse
from backend.api.threads.node.router import router as node_router
from backend.api.threads.node.tasks.router import router as tasks_router
from backend.api.threads.version.router import router as version_router

router = APIRouter(prefix="/threads", tags=["threads"])
router.include_router(node_router)
router.include_router(tasks_router)
router.include_router(version_router)


TThreadId = Annotated[str, Path(description="LangGraph thread UUID")]
TNodeId = Annotated[str, Path(description="Node execution UUID")]
TTaskId = Annotated[str, Path(description="Task invocation UUID")]
TStreamId = Annotated[str, Path(description="Celery ingest run UUID (leaf-level)")]


# ---------------------------------------------------------------------------
# Top-level: submit query (no thread yet)
# ---------------------------------------------------------------------------


@router.post("/query", response_model=QueryResponse, tags=["query"])
async def run_query(
    request: QueryRequest,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> QueryResponse:
    """Accept a financial analysis query and await client ACK before processing."""
    user, _ = await ensure_guest(x_user_token)
    return await submit_query(request, user)


# ---------------------------------------------------------------------------
# Thread-level
# ---------------------------------------------------------------------------


@router.get("/{thread_id}", response_model=QueryResponse, tags=["thread"])
async def get_thread_route(
    thread_id: TThreadId,
) -> QueryResponse:
    """Get the current status of a submitted query."""
    return await get_query_status(thread_id)


@router.post("/{thread_id}/ack", response_model=QueryResponse, tags=["thread"])
async def ack_thread_route(
    thread_id: TThreadId,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> QueryResponse:
    """Acknowledge a received query, starting LangGraph execution."""
    await ensure_guest(x_user_token)
    return await ack_query(thread_id)


@router.post("/{thread_id}/cancel", response_model=QueryResponse, tags=["thread"])
async def cancel_thread_route(
    thread_id: TThreadId,
    reason: str = "user",
) -> QueryResponse:
    """Cancel a running or received query (thread-level)."""
    return await cancel_query(thread_id, reason)


@router.post("/{thread_id}/resume", response_model=QueryResponse, tags=["thread"])
async def resume_thread_route(thread_id: TThreadId) -> QueryResponse:
    """Resume a cancelled or failed query from its last LangGraph checkpoint.

    Dispatches to ``run_resume_async`` which passes ``input=None`` so LangGraph
    loads the last pre-node checkpoint and re-runs the interrupted node from scratch.
    """
    return await resume_query(thread_id)


@router.put("/{thread_id}/viewer", status_code=204, tags=["thread"])
async def register_viewer_route(
    thread_id: TThreadId,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> None:
    """Register the calling user as actively viewing *thread_id*.

    Sets the explicit Redis viewer flags (app-level and thread-level) so
    ``stream_task`` can detect viewer presence without relying on Centrifugo
    WebSocket presence timing.

    Called by the frontend whenever the user navigates to a thread that was
    submitted in a previous session (history threads) or when the app reopens
    a running thread.  For freshly submitted threads the flags are already set
    by :func:`~backend.users.queries.submit_query`.

    Args:
        thread_id:    LangGraph thread UUID.
        x_user_token: Guest-auth bearer token from ``localStorage``.

    Returns:
        HTTP 204 No Content on success.

    Raises:
        HTTPException 401: If ``x_user_token`` is invalid.
    """
    from backend.db.redis.session.viewer_store import set_viewer

    user, _ = await ensure_guest(x_user_token)
    if user is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid user token")
    await set_viewer(str(user.id), thread_id)

