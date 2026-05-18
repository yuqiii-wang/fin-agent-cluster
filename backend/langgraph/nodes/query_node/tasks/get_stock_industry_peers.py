"""get_stock_industry_peers — NodeTask for query_node.

Execution layers
----------------
LangGraph layer (``_get_stock_industry_peers_task`` decorated with ``@task``):
    Calls ``create_task``, delegates to a Celery completion worker via
    ``delegate_completion``, and returns a ``TaskOutput``.  On exception,
    calls ``complete_task(failed=True)`` to emit the failure SSE.

Celery layer (``_handler``):
    Uses the Ollama LLM to determine the primary industry and 3-5 peer
    companies for the given stock.  Peers must operate in a similar business
    and the same geographic region as the target company.

Public export
-------------
``get_stock_industry_peers`` — ``NodeTask`` instance used by ``QueryNode.build_chain``.
``HANDLERS``                 — dict slice ``{"get_stock_industry_peers": _handler}``.
"""

from __future__ import annotations

import json
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

_TASK_NAME = "get_stock_industry_peers"

_PROMPT = (
    "You are a financial analyst. For the company or stock '{stock_name}', provide:\n"
    "1. Its primary industry sector (e.g. 'Semiconductors', 'Consumer Electronics', 'E-Commerce').\n"
    "2. A list of 3 to 5 peer companies that:\n"
    "   - Operate in the same or very similar business as '{stock_name}'\n"
    "   - Are primarily based and listed in the same geographic region\n\n"
    "Respond with valid JSON only, using this exact schema:\n"
    "{{\"industry\": \"<industry>\", \"peers\": [\"<company1>\", \"<company2>\", ...]}}\n"
    "No explanation, only the JSON."
)


# ---------------------------------------------------------------------------
# Intermediate output model
# ---------------------------------------------------------------------------


class GetStockIndustryPeersOutput(BaseModel):
    """Output from the get_stock_industry_peers task.

    Attributes:
        industry: Primary industry sector the company operates in.
        peers: Peer companies operating in a similar business and the same region.
    """

    industry: str = Field(description="Primary industry sector of the company.")
    peers: list[str] = Field(default_factory=list, description="Peer companies in similar business and region.")


# ---------------------------------------------------------------------------
# Celery layer — pure business logic
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Use Ollama LLM to determine the industry and peers for the stock.

    Args:
        payload: Serialised ``StockInfoInput`` dict from the Celery worker.

    Returns:
        Serialised ``GetStockIndustryPeersOutput`` dict.
    """
    inp = StockInfoInput.model_validate(payload)
    llm = get_llm("ollama")
    prompt = _PROMPT.format(stock_name=inp.stock_name)
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    raw = response.content.strip()

    try:
        data = json.loads(raw)
        industry = str(data.get("industry", ""))
        peers = [str(p) for p in data.get("peers", [])]
    except (json.JSONDecodeError, AttributeError):
        logger.error("get_stock_industry_peers: failed to parse LLM JSON for %r — raw: %r", inp.stock_name, raw)
        industry = ""
        peers = []

    return GetStockIndustryPeersOutput(industry=industry, peers=peers).model_dump()


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _get_stock_industry_peers_task(
    task_input: TaskInput[StockInfoInput],
) -> TaskOutput[GetStockIndustryPeersOutput]:
    """LangGraph @task: delegates get_stock_industry_peers to a Celery completion worker.

    Args:
        task_input: Typed envelope with TaskContext and StockInfoInput content.

    Returns:
        TaskOutput wrapping the GetStockIndustryPeersOutput from the Celery worker.
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
    output = GetStockIndustryPeersOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

get_stock_industry_peers = NodeTask(
    name=_TASK_NAME,
    description=(
        "Determine the primary industry and 3-5 regional peers for the given stock using an LLM. "
        "Peers must operate in a similar business and the same geographic region."
    ),
    input_type=StockInfoInput,
    output_type=GetStockIndustryPeersOutput,
    task_fn=_get_stock_industry_peers_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}
