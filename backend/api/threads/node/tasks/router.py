"""backend.api.threads.node.tasks — task-level API endpoints.

Routes (all mounted on the parent ``/threads`` router):

    GET  /api/v1/threads/{thread_id}/tasks                             — list all tasks
    GET  /api/v1/threads/{thread_id}/tasks/{task_id}                   — single task status
    POST /api/v1/threads/{thread_id}/tasks/{task_id}/cancel            — cancel a task
    POST /api/v1/threads/{thread_id}/tasks/{task_id}/pause             — pause a task
    POST /api/v1/threads/{thread_id}/tasks/{task_id}/retry             — retry a terminal task
    POST /api/v1/threads/{thread_id}/tasks/{task_id}/retry-fresh       — pause-if-running then restart
    POST /api/v1/threads/{thread_id}/tasks/{task_id}/retry-restart     — restart terminal task directly
    POST /api/v1/threads/{thread_id}/tasks/{task_id}/continue          — continue a paused task
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from backend.users.queries import (
    cancel_task_by_uuid,
    continue_task,
    get_query_tasks,
    get_task_by_id,
    pause_task_by_uuid,
    retry_fresh_task,
    retry_restart_task,
    retry_task,
)
from backend.users.schemas import RetryTaskRequest, SessionStatus, TaskInfo

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


@router.get("/{thread_id}/tasks/{task_id}", response_model=TaskInfo, tags=["task"])
async def get_task_route(thread_id: TThreadId, task_id: TTaskId) -> TaskInfo:
    """Get the full status and output of a specific task, with view metadata."""
    return await get_task_by_id(thread_id, task_id)


@router.post("/{thread_id}/tasks/{task_id}/cancel", tags=["task"])
async def cancel_task_route(
    thread_id: TThreadId,
    task_id: TTaskId,
    node_id: str = "",
) -> dict:
    """Send a cancel signal to a specific task by its governance UUID."""
    return await cancel_task_by_uuid(thread_id, task_id, node_id=node_id)


@router.post("/{thread_id}/tasks/{task_id}/pause", tags=["task"])
async def pause_task_route(
    thread_id: TThreadId,
    task_id: TTaskId,
) -> dict:
    """Pause a running task, saving partial stream thinking if applicable."""
    return await pause_task_by_uuid(thread_id, task_id)


@router.post("/{thread_id}/tasks/{task_id}/retry", response_model=TaskInfo, tags=["task"])
async def retry_task_route(
    thread_id: TThreadId,
    task_id: TTaskId,
    body: RetryTaskRequest = RetryTaskRequest(),
) -> TaskInfo:
    """Retry a terminal task with the same input.

    For non-streaming tasks ``mode`` must be ``"restart"``.
    For streaming tasks ``mode`` may be ``"restart"`` (re-run from scratch)
    or ``"compact_and_continue"`` (continue from compressed prior thinking).

    Returns the task row with status ``running``; further progress is
    delivered via Centrifugo SSE events on the thread channel.
    """
    return await retry_task(thread_id, task_id, mode=body.mode)


@router.post("/{thread_id}/tasks/{task_id}/retry-fresh", response_model=TaskInfo, tags=["task"])
async def retry_fresh_task_route(
    thread_id: TThreadId,
    task_id: TTaskId,
) -> TaskInfo:
    """Pause a running task (if needed) then restart it from scratch.

    If the task is currently ``running``, pauses it immediately and schedules
    a restart once the old Celery worker has exited.  Returns the task with
    status ``paused`` while the restart is pending.

    If the task is already in a terminal retryable state, restarts it
    synchronously and returns with status ``running``.
    """
    return await retry_fresh_task(thread_id, task_id)


@router.post("/{thread_id}/tasks/{task_id}/retry-restart", response_model=TaskInfo, tags=["task"])
async def retry_restart_task_route(
    thread_id: TThreadId,
    task_id: TTaskId,
) -> TaskInfo:
    """Restart a terminal task from scratch, dropping all existing output.

    Requires the task to already be in a retryable terminal state
    (``completed`` / ``failed`` / ``cancelled`` / ``paused``).
    Use this for non-streaming completion tasks where there is no active
    Celery stream worker to coordinate with.
    """
    return await retry_restart_task(thread_id, task_id)


@router.post("/{thread_id}/tasks/{task_id}/continue", response_model=TaskInfo, tags=["task"])
async def continue_task_route(
    thread_id: TThreadId,
    task_id: TTaskId,
) -> TaskInfo:
    """Continue a paused streaming task from where it left off.

    Uses ``compact_and_continue`` mode — compresses prior thinking and
    resumes generation.  Only valid when the task is in ``paused`` status.
    """
    return await continue_task(thread_id, task_id)

