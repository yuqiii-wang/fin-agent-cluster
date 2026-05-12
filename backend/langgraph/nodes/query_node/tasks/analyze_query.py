"""analyze_query — NodeTask for query_node.

Execution layers
----------------
LangGraph layer (``_analyze_query_task`` decorated with ``@task``):
    Calls ``create_task``, delegates to a Celery completion worker via
    ``delegate_completion``, and returns a ``TaskOutput``.  On exception,
    calls ``complete_task(failed=True)`` to emit the failure SSE.

Celery layer (``_handler``):
    Pure async function containing the actual business logic.  Registered
    in ``HANDLERS`` and dispatched by the Celery completion worker.  The
    worker calls ``persist_task_result`` for DB persistence; SSE for
    successful completion is handled by the lifecycle module.

Public export
-------------
``analyze_query`` — ``NodeTask`` instance used by ``QueryNode.orchestrate``.
``HANDLERS``      — dict slice ``{"analyze_query": _handler}`` assembled by
                    ``nodes/__init__.py`` into the global registry.
"""

from __future__ import annotations

import logging
import re

from langgraph.func import task

from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.nodes.base.models import TaskInput, TaskOutput
from backend.langgraph.nodes.base.task import NodeTask
from backend.langgraph.nodes.query_node.models import QueryNodeInput, QueryNodeOutput
from backend.celery_task.workers.task_delegation import delegate_completion

logger = logging.getLogger(__name__)

_TASK_NAME = "analyze_query"


# ---------------------------------------------------------------------------
# Celery layer — pure business logic
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Parse the user query to extract intent and equity symbols.

    Args:
        payload: Serialised ``QueryNodeInput`` dict from the Celery worker.

    Returns:
        Serialised ``QueryNodeOutput`` dict.
    """
    inp = QueryNodeInput.model_validate(payload)
    symbols = re.findall(r"\b[A-Z]{1,5}\b", inp.query)
    return QueryNodeOutput(
        intent="market_analysis",
        symbols=symbols[:5] or ["AAPL"],
        filters={},
    ).model_dump()


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _analyze_query_task(
    task_input: TaskInput[QueryNodeInput],
) -> TaskOutput[QueryNodeOutput]:
    """LangGraph @task: delegates analyze_query to a Celery completion worker.

    Args:
        task_input: Typed envelope with TaskContext and QueryNodeInput content.

    Returns:
        TaskOutput wrapping the QueryNodeOutput from the Celery worker.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

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
    output = QueryNodeOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

analyze_query = NodeTask(
    name=_TASK_NAME,
    description=(
        "Parse the raw user query to extract the trading intent, equity ticker "
        "symbols, and optional filters (date range, interval, etc.)."
    ),
    input_type=QueryNodeInput,
    output_type=QueryNodeOutput,
    task_fn=_analyze_query_task,
    handler=_handler,
)
