"""get_stock_from_web_if_not_seen — NodeTask for query_node.

This is a WebRequest task: it searches the web for the stock that
``analyze_query`` could not identify, then returns the raw web content for
``analyze_stock_from_web_if_not_seen`` to process.

Execution layers
----------------
LangGraph layer (``_get_stock_from_web_if_not_seen_task``):
    Calls ``create_task(..., view_type="WebRequest")``, delegates to a Celery
    completion worker, returns a ``TaskOutput``.

Celery layer (``_handler``):
    Uses :class:`~backend.resources.info.InfoClient` (DDGS) to search for
    company/ticker information.  Returns a ``WebStockOutput``.

Public export
-------------
``get_stock_from_web_if_not_seen`` — ``NodeTask`` instance.
``HANDLERS``                        — dict slice for the completion registry.
"""

from __future__ import annotations

import logging

from langgraph.func import task

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.query_node.models import WebStockInput, WebStockOutput
from backend.resources.info import InfoClient

logger = logging.getLogger(__name__)

_TASK_NAME = "get_stock_from_web_if_not_seen"


# ---------------------------------------------------------------------------
# Celery layer — pure business logic
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Fetch web summary for the given stock using DDGS.

    Args:
        payload: Serialised ``WebStockInput`` dict from the Celery worker.

    Returns:
        Serialised ``WebStockOutput`` dict.
    """
    inp = WebStockInput.model_validate(payload)
    client = InfoClient()
    for search_term in (f"{inp.stock_name} company stock", inp.query):
        results = await client.search(search_term, max_results=1)
        if results:
            r = results[0]
            return WebStockOutput(url=r.url, title=r.title, content=r.content).model_dump()
    return WebStockOutput().model_dump()


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _get_stock_from_web_if_not_seen_task(
    task_input: TaskInput[WebStockInput],
) -> TaskOutput[WebStockOutput]:
    """LangGraph @task: delegates web fetch to a Celery completion worker.

    Args:
        task_input: Typed envelope with TaskContext and WebStockInput content.

    Returns:
        TaskOutput wrapping the WebStockOutput from the Celery worker.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="WebRequest",
    )
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
    output = WebStockOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

get_stock_from_web_if_not_seen = NodeTask(
    name=_TASK_NAME,
    description=(
        "Fetch a Wikipedia summary for the stock when the LLM did not recognise it. "
        "Returns the URL, title, and plain-text content extract."
    ),
    input_type=WebStockInput,
    output_type=WebStockOutput,
    task_fn=_get_stock_from_web_if_not_seen_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}
