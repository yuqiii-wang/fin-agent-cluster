"""FastAPI router for user query endpoints.

Mounted at ``/users`` under the parent API router, so full paths are:

    POST /api/v1/users/query
    POST /api/v1/users/query/{thread_id}/ack
    POST /api/v1/users/query/{thread_id}/cancel
    POST /api/v1/users/query/{thread_id}/pause
    POST /api/v1/users/query/{thread_id}/resume
    POST /api/v1/users/query/{thread_id}/nodes/{node_id}/cancel
    POST /api/v1/users/query/{thread_id}/tasks/{task_id}/cancel
    POST /api/v1/users/query/{thread_id}/perf-stable?stream_id={stream_id}
    GET  /api/v1/users/query/{thread_id}
    GET  /api/v1/users/query/{thread_id}/tasks
    GET  /api/v1/users/query/{thread_id}/nodes

Business logic lives in :mod:`backend.users.queries`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query

from backend.users.auth import ensure_guest
from backend.users.queries import (
    ack_query,
    cancel_node,
    cancel_query,
    cancel_task_by_uuid,
    fork_from_node,
    get_node_executions,
    get_query_status,
    get_query_tasks,
    pause_query,
    resume_query,
    replay_from_node,
    submit_query,
)
from backend.users.schemas import (
    ForkFromNodeRequest,
    ForkFromNodeResponse,
    NodeExecutionInfo,
    QueryRequest,
    QueryResponse,
    ReplayFromNodeRequest,
    SessionStatus,
)
from backend.db.redis.session.perf_stable_signal import set_perf_stable

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
    """Cancel a running or received query (thread-level)."""
    return await cancel_query(thread_id, reason)


@router.post("/query/{thread_id}/nodes/{node_id}/cancel")
async def cancel_node_route(thread_id: str, node_id: str) -> dict:
    """Cancel a specific node execution and all tasks running under it."""
    return await cancel_node(thread_id, node_id)


@router.post("/query/{thread_id}/pause", response_model=QueryResponse)
async def pause_query_route(thread_id: str) -> QueryResponse:
    """Request that a running query pause at the next LangGraph interrupt checkpoint.

    Sets a Redis pause signal.  The graph runner will stop auto-approving the
    next ``interrupt()`` call and emit a ``done(paused)`` SSE event once the
    graph has persisted its checkpoint.  Use ``POST /resume`` to continue.
    """
    return await pause_query(thread_id)


@router.post("/query/{thread_id}/resume", response_model=QueryResponse)
async def resume_query_route(thread_id: str) -> QueryResponse:
    """Resume a cancelled, failed, or paused query from its last LangGraph checkpoint.

    Dispatches the correct resume strategy:
    - ``paused``: ``Command(resume=True)`` — continues from the interrupt checkpoint.
    - ``cancelled`` / ``failed``: ``input=None`` — re-runs from last pre-node checkpoint.
    """
    return await resume_query(thread_id)


@router.post("/query/{thread_id}/replay", response_model=QueryResponse)
async def replay_query_route(thread_id: str, body: ReplayFromNodeRequest) -> QueryResponse:
    """Replay a completed/paused/cancelled query from a specific node's last checkpoint.

    Uses LangGraph time-travel: finds the checkpoint where *node_name* is in
    ``snapshot.next`` and re-invokes the graph from that point.  Nodes before
    *node_name* are replayed from cached checkpoints (not re-executed); the
    target node and all subsequent nodes execute fresh.

    The thread must not be currently running.
    """
    return await replay_from_node(thread_id, body.node_name)


@router.post("/query/{thread_id}/fork", response_model=ForkFromNodeResponse)
async def fork_query_route(thread_id: str, body: ForkFromNodeRequest) -> ForkFromNodeResponse:
    """Fork a query from a specific node's checkpoint into a new independent thread.

    Unlike replay (which re-runs the same thread), fork creates a brand-new
    ``thread_id`` that starts from the fork point.  The source thread is not
    modified.  The caller receives the new ``thread_id`` and can subscribe to
    its Centrifugo channel independently.

    The source thread must not be currently running.
    """
    return await fork_from_node(thread_id, body.node_name)


@router.post("/query/{thread_id}/tasks/{task_id}/cancel")
async def cancel_task_route(
    thread_id: str,
    task_id: str,
    node_id: str = "",
) -> dict:
    """Send a cancel signal to a specific task by its governance UUID."""
    return await cancel_task_by_uuid(thread_id, task_id, node_id=node_id)


@router.post("/query/{thread_id}/perf-stable", status_code=204)
async def perf_stable_route(
    thread_id: str,
    stream_id: Annotated[str, Query(description="Celery ingest run UUID (leaf-level governance ID)")],
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> None:
    """Signal that the concurrency stream identified by *stream_id* has reached stable TPS.

    Called by the frontend when per-stream TPS history satisfies the
    group-stability condition.  Sets a Redis flag that causes the running
    stream_ingest Celery worker to stop gracefully and emit ``stream_complete``
    (not ``stream_stopped``), marking the session as completed rather than
    timed out.

    The ``stream_id`` query parameter scopes the signal to the specific Celery
    ingest run so concurrent streams on the same ``thread_id`` never
    cross-pollinate stable signals.

    Args:
        thread_id: LangGraph thread UUID (top-level scope; used for routing).
        stream_id: Celery ingest run UUID (leaf-level scope; the signal key).
    """
    await ensure_guest(x_user_token)
    await set_perf_stable(stream_id, thread_id)


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
