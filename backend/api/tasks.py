"""FastAPI router for task metadata and classification endpoints.

Task key metadata is sourced directly from
:mod:`backend.graph.agents.task_keys`, which is the single source of truth for
all agent task keys.  No AST scanning or dynamic module imports are required.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.graph.agents.task_keys import LLM_STREAM_KEYS, STATIC_KEYS
from backend.graph.utils.task_stream import signal_task_control

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskTypeMeta(BaseModel):
    """Task key classification metadata for frontend display routing.

    Attributes:
        llm_task_keys: Keys that emit token-stream SSE events (call
            ``stream_text_task`` or ``stream_llm_task``).
        all_task_keys: Every static key that is not an LLM stream key.
    """

    llm_task_keys: list[str]
    all_task_keys: list[str]


def _build_task_meta() -> TaskTypeMeta:
    """Build task classification metadata from the task_keys registry.

    Returns:
        :class:`TaskTypeMeta` with ``llm_task_keys`` and ``all_task_keys``
        derived from :mod:`backend.graph.agents.task_keys`.
    """
    non_llm = STATIC_KEYS - LLM_STREAM_KEYS
    return TaskTypeMeta(
        llm_task_keys=sorted(LLM_STREAM_KEYS),
        all_task_keys=sorted(non_llm),
    )


@router.get("/meta", response_model=TaskTypeMeta)
async def get_task_type_meta() -> TaskTypeMeta:
    """Return task key classification metadata for frontend display routing.

    Reads static and LLM-stream key sets from
    :mod:`backend.graph.agents.task_keys` and returns them classified.

    Returns:
        :class:`TaskTypeMeta` with ``llm_task_keys`` (stream emitters) and
        ``all_task_keys`` (all other static literal keys).
    """
    return _build_task_meta()


@router.post("/{task_id}/cancel", status_code=200)
async def cancel_task_action(task_id: int) -> dict:
    """Signal a running LLM task to cancel and mark it as cancelled.

    Registers a ``"cancel"`` control signal for *task_id*.  The next
    iteration of the streaming loop in :func:`~backend.graph.utils.task_stream.stream_text_task`
    or :func:`~backend.graph.utils.task_stream.stream_llm_task` will raise
    :class:`~backend.graph.utils.task_stream.TaskCancelledSignal`, stop the
    upstream LLM generator, and persist ``status="cancelled"`` to the DB.

    Args:
        task_id: DB primary key of the task to cancel.

    Returns:
        Echo of the task_id and action.

    Raises:
        HTTPException: 400 if task_id is not positive.
    """
    if task_id <= 0:
        raise HTTPException(status_code=400, detail="task_id must be positive")
    signal_task_control(task_id, "cancel")
    return {"task_id": task_id, "action": "cancel"}


@router.post("/{task_id}/pass", status_code=200)
async def pass_task_action(task_id: int) -> dict:
    """Signal a running LLM task to accept its partial accumulated output.

    Registers a ``"pass"`` control signal for *task_id*.  The next iteration
    of the streaming loop will raise
    :class:`~backend.graph.utils.task_stream.TaskPassSignal` with the
    accumulated text so far, stop the upstream generator, and persist
    ``status="completed"`` using the partial JSON as the task output.

    Args:
        task_id: DB primary key of the task to pass.

    Returns:
        Echo of the task_id and action.

    Raises:
        HTTPException: 400 if task_id is not positive.
    """
    if task_id <= 0:
        raise HTTPException(status_code=400, detail="task_id must be positive")
    signal_task_control(task_id, "pass")
    return {"task_id": task_id, "action": "pass"}

