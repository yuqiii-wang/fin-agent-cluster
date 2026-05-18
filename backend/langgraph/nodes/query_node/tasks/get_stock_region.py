"""get_stock_region — NodeTask for query_node.

Execution layers
----------------
LangGraph layer (``_get_stock_region_task`` decorated with ``@task``):
    Calls ``create_task``, delegates to a Celery completion worker via
    ``delegate_completion``, and returns a ``TaskOutput``.  On exception,
    calls ``complete_task(failed=True)`` to emit the failure SSE.

Celery layer (``_handler``):
    Uses the Ollama LLM to determine the primary exchange region for the
    given stock name.  Returns one of: APAC, EMEA, AMER.

Public export
-------------
``get_stock_region`` — ``NodeTask`` instance used by ``QueryNode.build_chain``.
``HANDLERS``         — dict slice ``{"get_stock_region": _handler}``.
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage
from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.query_node.models import StockInfoInput
from backend.llm.factory import get_llm

logger = logging.getLogger(__name__)

_TASK_NAME = "get_stock_region"

_PROMPT = (
    "You are a financial data expert. For the company or stock '{stock_name}', "
    "identify the primary exchange region where it is primarily listed and traded. "
    "Return exactly one of: APAC, EMEA, AMER. "
    "No explanation, just the region code."
)

_VALID_REGIONS = {"APAC", "EMEA", "AMER"}


# ---------------------------------------------------------------------------
# Intermediate output model
# ---------------------------------------------------------------------------


class GetStockRegionOutput(BaseModel):
    """Output from the get_stock_region task.

    Attributes:
        region: Primary exchange region of the stock (APAC, EMEA, or AMER).
    """

    region: str = Field(description="Primary exchange region: APAC, EMEA, or AMER.")


# ---------------------------------------------------------------------------
# Celery layer — pure business logic
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Use Ollama LLM to determine the primary exchange region for the stock.

    Args:
        payload: Serialised ``StockInfoInput`` dict from the Celery worker.

    Returns:
        Serialised ``GetStockRegionOutput`` dict.
    """
    inp = StockInfoInput.model_validate(payload)
    llm = get_llm("ollama")
    prompt = _PROMPT.format(stock_name=inp.stock_name)
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    region = response.content.strip().upper()
    if region not in _VALID_REGIONS:
        logger.error("get_stock_region: unexpected region %r for %r — defaulting to AMER", region, inp.stock_name)
        region = "AMER"
    return GetStockRegionOutput(region=region).model_dump()


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _get_stock_region_task(
    task_input: TaskInput[StockInfoInput],
) -> TaskOutput[GetStockRegionOutput]:
    """LangGraph @task: delegates get_stock_region to a Celery completion worker.

    Args:
        task_input: Typed envelope with TaskContext and StockInfoInput content.

    Returns:
        TaskOutput wrapping the GetStockRegionOutput from the Celery worker.
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
    output = GetStockRegionOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

get_stock_region = NodeTask(
    name=_TASK_NAME,
    description="Determine the primary exchange region (APAC, EMEA, AMER) for the given stock using an LLM.",
    input_type=StockInfoInput,
    output_type=GetStockRegionOutput,
    task_fn=_get_stock_region_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}
