"""Reduced queries router for assistant instances.

Exposes the query *read* and *control* endpoints only.  The LangGraph-
triggering endpoints (submit / ack) are intentionally excluded; Kong
routes those exclusively to runner instances.

Endpoints:
    POST /users/query/{thread_id}/cancel                  cancel a running query
    POST /users/query/{thread_id}/resume                  resume cancelled/failed query
    POST /users/query/{thread_id}/nodes/{node_id}/cancel  cancel a node + its tasks
    POST /users/query/{thread_id}/tasks/{task_id}/cancel  cancel a specific task
    POST /users/query/{thread_id}/tasks/{task_id}/enable-stream  enable opt-in token streaming
    POST /users/query/{thread_id}/perf-stable             signal stable TPS
    GET  /users/query/{thread_id}                         poll query status
    GET  /users/query/{thread_id}/tasks                   list agent sub-tasks
    GET  /users/query/{thread_id}/nodes                   node-level I/O snapshots
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query

from backend.users.queries import (
    cancel_node,
    cancel_query,
    cancel_task_by_uuid,
    get_node_executions,
    get_query_status,
    get_query_tasks,
    resume_query,
)
from backend.users.schemas import NodeExecutionInfo, QueryResponse, SessionStatus
from backend.db.redis.session.perf_stable_signal import set_perf_stable
from backend.users.auth import ensure_guest

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/query/{thread_id}/cancel", response_model=QueryResponse)
async def cancel_query_route(
    thread_id: str,
    reason: str = "user",
) -> QueryResponse:
    """Cancel a running or received query."""
    return await cancel_query(thread_id, reason)


@router.post("/query/{thread_id}/nodes/{node_id}/cancel")
async def cancel_node_route(thread_id: str, node_id: str) -> dict:
    """Cancel a specific node execution and all tasks running under it."""
    return await cancel_node(thread_id, node_id)


@router.post("/query/{thread_id}/tasks/{task_id}/cancel")
async def cancel_task_route(
    thread_id: str,
    task_id: str,
    node_id: str = "",
) -> dict:
    """Send a cancel signal to a specific task by its governance UUID."""
    return await cancel_task_by_uuid(thread_id, task_id, node_id=node_id)


@router.post("/query/{thread_id}/tasks/{task_id}/enable-stream", status_code=200)
async def enable_task_stream_route(thread_id: str, task_id: str) -> dict:
    """Enable live Centrifugo streaming for a buffered opt-in streaming task.

    Sets the Redis live flag so the running analysis/report task immediately
    begins forwarding buffered and future tokens to Centrifugo.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task invocation UUID to enable streaming for.

    Returns:
        Echo of thread_id, task_id, and streaming status.
    """
    from backend.db.redis.session.task_preview import enable_task_stream  # noqa: PLC0415
    await enable_task_stream(thread_id, task_id)
    return {"thread_id": thread_id, "task_id": task_id, "streaming": True}


@router.post("/query/{thread_id}/resume", response_model=QueryResponse)
async def resume_query_route(thread_id: str) -> QueryResponse:
    """Resume a cancelled, failed, or paused query from its last LangGraph checkpoint."""
    return await resume_query(thread_id)


@router.post("/query/{thread_id}/perf-stable", status_code=204)
async def perf_stable_route(
    thread_id: str,
    stream_id: Annotated[str, Query(description="Celery ingest run UUID (leaf-level governance ID)")],
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> None:
    """Signal that the concurrency perf stream has reached stable TPS."""
    await ensure_guest(x_user_token)
    await set_perf_stable(stream_id, thread_id)


@router.get("/query/{thread_id}", response_model=QueryResponse)
async def get_query_status_route(thread_id: str) -> QueryResponse:
    """Return current status of a submitted query."""
    return await get_query_status(thread_id)


@router.get("/query/{thread_id}/tasks", response_model=SessionStatus)
async def get_query_tasks_route(thread_id: str) -> SessionStatus:
    """Return the query record and all its agent sub-tasks."""
    return await get_query_tasks(thread_id)


@router.get("/query/{thread_id}/nodes", response_model=list[NodeExecutionInfo])
async def get_node_executions_route(thread_id: str) -> list[NodeExecutionInfo]:
    """Return node-level I/O snapshots for a query thread."""
    return await get_node_executions(thread_id)
