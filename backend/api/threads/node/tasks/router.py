"""backend.api.threads.node.tasks — task-level API endpoints.

Routes (all mounted on the parent ``/threads`` router):

    GET  /api/v1/threads/{thread_id}/tasks                       — list all tasks
    GET  /api/v1/threads/{thread_id}/tasks/{task_id}             — single task status
    POST /api/v1/threads/{thread_id}/tasks/{task_id}/cancel      — cancel a task
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from backend.users.queries import cancel_task_by_uuid, get_query_status, get_query_tasks
from backend.users.schemas import QueryResponse, SessionStatus

router = APIRouter()

TThreadId = Annotated[str, Path(description="LangGraph thread UUID")]
TTaskId = Annotated[str, Path(description="Task invocation UUID")]


# ---------------------------------------------------------------------------
# Task-level
# ---------------------------------------------------------------------------


@router.get("/{thread_id}/tasks", response_model=SessionStatus, tags=["task"])
async def list_tasks_route(thread_id: TThreadId) -> SessionStatus:
    """Return the query record and all its agent sub-tasks."""
    return await get_query_tasks(thread_id)


@router.get("/{thread_id}/tasks/{task_id}", response_model=QueryResponse, tags=["task"])
async def get_task_route(thread_id: TThreadId, task_id: TTaskId) -> QueryResponse:
    """Get the status of a specific task within a thread."""
    return await get_query_status(thread_id)


@router.post("/{thread_id}/tasks/{task_id}/cancel", tags=["task"])
async def cancel_task_route(
    thread_id: TThreadId,
    task_id: TTaskId,
    node_id: str = "",
) -> dict:
    """Send a cancel signal to a specific task by its governance UUID."""
    return await cancel_task_by_uuid(thread_id, task_id, node_id=node_id)

