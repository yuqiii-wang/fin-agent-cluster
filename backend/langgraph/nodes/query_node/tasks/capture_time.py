"""capture_time — NodeTask for query_node.

Captures the current UTC timestamp at the moment the LangGraph @task is
invoked.  The timestamp is embedded in the Celery payload so the handler
simply echoes it back — the source of truth is the @task invocation time,
not the worker pick-up time.

Public export
-------------
``capture_time`` — ``NodeTask`` instance registered in ``HANDLERS`` alongside
                   ``analyze_query``.
``HANDLERS``      — dict slice ``{"capture_time": _handler}``
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.nodes.base.models import TaskInput, TaskOutput
from backend.langgraph.nodes.base.task import NodeTask
from backend.langgraph.nodes.query_node.models import QueryNodeInput

logger = logging.getLogger(__name__)

_TASK_NAME = "capture_time"


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class CaptureTimeOutput(BaseModel):
    """Output from the capture_time task.

    Attributes:
        query_time: UTC ISO 8601 timestamp captured at @task invocation time.
    """

    query_time: str = Field(description="UTC ISO 8601 timestamp when the query entered the graph.")


# ---------------------------------------------------------------------------
# Celery layer — pure business logic
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Echo back the query_time that was captured at @task invocation time.

    Args:
        payload: Dict containing ``query_time`` pre-stamped by the @task.

    Returns:
        Serialised ``CaptureTimeOutput`` dict.
    """
    return CaptureTimeOutput(query_time=payload["query_time"]).model_dump()


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _capture_time_task(
    task_input: TaskInput[QueryNodeInput],
) -> TaskOutput[CaptureTimeOutput]:
    """LangGraph @task: stamps current UTC time and delegates to Celery.

    The timestamp is captured here (LangGraph execution time) and embedded
    into the Celery payload, ensuring the time reflects when the query
    entered the graph rather than Celery worker pick-up time.

    Args:
        task_input: Typed envelope with TaskContext and QueryNodeInput content.

    Returns:
        TaskOutput wrapping the CaptureTimeOutput.
    """
    ctx = task_input.ctx
    query_time = datetime.now(timezone.utc).isoformat()
    payload = {**task_input.content.model_dump(), "query_time": query_time}

    await create_task(ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload)
    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload
        )
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc),
        )
        raise
    output = CaptureTimeOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

capture_time = NodeTask(
    name=_TASK_NAME,
    description=(
        "Capture the UTC timestamp at the moment the query enters the graph.  "
        "Used downstream to route the query to the appropriate regional analysis node."
    ),
    input_type=QueryNodeInput,
    output_type=CaptureTimeOutput,
    task_fn=_capture_time_task,
    handler=_handler,
)
