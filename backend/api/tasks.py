"""FastAPI router for task metadata and classification endpoints.

Task key metadata is sourced directly from
:mod:`backend.graph.agents.task_keys`, which is the single source of truth for
all agent task keys.  No AST scanning or dynamic module imports are required.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.graph.agents.task_keys import LLM_STREAM_KEYS, STATIC_KEYS

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

