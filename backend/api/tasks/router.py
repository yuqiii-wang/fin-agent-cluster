"""FastAPI router for task metadata and classification endpoints.

Task key metadata is sourced directly from
:mod:`backend.graph.agents.task_names`, which is the single source of truth for
all agent task keys.  No AST scanning or dynamic module imports are required.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.graph.agents.task_names import LLM_STREAM_KEYS, PERF_TOKEN_KEYS, STATIC_KEYS, STREAM_KEYS
from backend.sse_notifications import signal_task_control
from backend.api.errors import API_TASK_ID_INVALID

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskTypeMeta(BaseModel):
    """Task key classification metadata for frontend display routing.

    Attributes:
        llm_task_names: Keys that emit token-stream SSE events (call
            ``stream_text_task`` or ``stream_llm_task``).
        all_task_names: Every static key that is not an LLM stream key.
        perf_token_task_names: Keys that emit ``perf_token`` SSE events for
            silent metric aggregation (not shown as task output text).
        stream_task_names: Keys that use the Celery streaming path (Celery ingest
            → Centrifugo delivery).  The frontend should show "Streaming Output"
            for tasks with these keys rather than a static JSON output block.
    """

    llm_task_names: list[str]
    all_task_names: list[str]
    perf_token_task_names: list[str]
    stream_task_names: list[str]


def _build_task_meta() -> TaskTypeMeta:
    """Build task classification metadata from the task_names registry.

    Returns:
        :class:`TaskTypeMeta` with ``llm_task_names`` and ``all_task_names``
        derived from :mod:`backend.graph.agents.task_names`.
    """
    non_llm = STATIC_KEYS - LLM_STREAM_KEYS - PERF_TOKEN_KEYS
    return TaskTypeMeta(
        llm_task_names=sorted(LLM_STREAM_KEYS),
        all_task_names=sorted(non_llm),
        perf_token_task_names=sorted(PERF_TOKEN_KEYS),
        stream_task_names=sorted(STREAM_KEYS),
    )


@router.get("/meta", response_model=TaskTypeMeta)
async def get_task_type_meta() -> TaskTypeMeta:
    """Return task key classification metadata for frontend display routing.

    Reads static and LLM-stream key sets from
    :mod:`backend.graph.agents.task_names` and returns them classified.

    Returns:
        :class:`TaskTypeMeta` with ``llm_task_names`` (stream emitters) and
        ``all_task_names`` (all other static literal keys).
    """
    return _build_task_meta()


@router.post("/{task_id}/cancel", status_code=200)
async def cancel_task_action(task_id: str) -> dict:
    """Signal a running LLM task to cancel its stream and return an empty result.

    Args:
        task_id: Primary key (UUID string) of the task to cancel.

    Returns:
        Echo of the task_id and action.

    Raises:
        HTTPException: 400 if task_id is empty.
    """
    if not task_id or not task_id.strip():
        raise HTTPException(status_code=400, detail={"code": API_TASK_ID_INVALID, "message": "task_id must not be empty"})
    signal_task_control(task_id, "cancel")
    return {"task_id": task_id, "action": "cancel"}


@router.post("/{task_id}/pass", status_code=200)
async def pass_task_action(task_id: str) -> dict:
    """Signal a running LLM task to accept its partial accumulated output.

    Args:
        task_id: Primary key (UUID string) of the task to pass.

    Returns:
        Echo of the task_id and action.

    Raises:
        HTTPException: 400 if task_id is empty.
    """
    if not task_id or not task_id.strip():
        raise HTTPException(status_code=400, detail={"code": API_TASK_ID_INVALID, "message": "task_id must not be empty"})
    signal_task_control(task_id, "pass")
    return {"task_id": task_id, "action": "pass"}
