"""analyze_query — NodeTask for query_node.

Execution layers
----------------
LangGraph layer (``_analyze_query_task`` decorated with ``@task``):
    Calls ``create_task``, delegates to a Celery completion worker via
    ``delegate_completion``, and returns a ``TaskOutput``.  On exception,
    calls ``complete_task(failed=True)`` to emit the failure SSE.

Celery layer (``_handler``):
    Uses the Ollama LLM to extract the primary company name or stock ticker
    from the raw user query.  Returns an ``AnalyzeQueryOutput``.

Public export
-------------
``analyze_query`` — ``NodeTask`` instance used by ``QueryNode.build_chain``.
``HANDLERS``      — dict slice ``{"analyze_query": _handler}``.
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
from backend.langgraph.nodes.query_node.models import QueryNodeInput
from backend.llm.factory import get_llm

logger = logging.getLogger(__name__)

_TASK_NAME = "analyze_query"

_PROMPT = (
    "You are a financial assistant. Extract the primary company name or stock ticker "
    "from the following user query.\n\n"
    "Respond with valid JSON only, using this exact schema:\n"
    '{{"stock_name": "<company name or ticker>", "not_seen": false}}\n\n'
    "Set not_seen to true if you do not recognise the company or stock, or if the query "
    "does not mention a specific publicly traded company. "
    "If not_seen is true, still try your best to extract what the user might be referring to "
    "in stock_name.\n"
    "No explanation, only the JSON.\n\n"
    "Query: {query}"
)


# ---------------------------------------------------------------------------
# Intermediate output model
# ---------------------------------------------------------------------------


class AnalyzeQueryOutput(BaseModel):
    """Output from the analyze_query task.

    Attributes:
        stock_name: Company name or ticker symbol extracted from the user query.
        not_seen:   True when the LLM does not recognise the stock or the query
                    does not mention a specific publicly traded company.
    """

    stock_name: str = Field(description="Company name or stock ticker extracted from the query.")
    not_seen: bool = Field(default=False, description="True when the LLM does not recognise the stock.")


# ---------------------------------------------------------------------------
# Celery layer — pure business logic
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Use Ollama LLM to extract the stock name from the user query.

    Args:
        payload: Serialised ``QueryNodeInput`` dict from the Celery worker.

    Returns:
        Serialised ``AnalyzeQueryOutput`` dict.
    """
    inp = QueryNodeInput.model_validate(payload)
    llm = get_llm("ollama")
    prompt = _PROMPT.format(query=inp.query)
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    raw = response.content.strip()
    try:
        data = json.loads(raw)
        stock_name = str(data.get("stock_name", "")).strip()
        not_seen = bool(data.get("not_seen", False))
    except (json.JSONDecodeError, AttributeError):
        logger.error("analyze_query: failed to parse LLM JSON — raw: %r", raw)
        stock_name = raw.split("\n")[0][:100]
        not_seen = True
    return AnalyzeQueryOutput(stock_name=stock_name, not_seen=not_seen).model_dump()


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _analyze_query_task(
    task_input: TaskInput[QueryNodeInput],
) -> TaskOutput[AnalyzeQueryOutput]:
    """LangGraph @task: delegates analyze_query to a Celery completion worker.

    Args:
        task_input: Typed envelope with TaskContext and QueryNodeInput content.

    Returns:
        TaskOutput wrapping the AnalyzeQueryOutput from the Celery worker.
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
    output = AnalyzeQueryOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

analyze_query = NodeTask(
    name=_TASK_NAME,
    description="Extract the primary company name or stock ticker from the user query using an LLM.",
    input_type=QueryNodeInput,
    output_type=AnalyzeQueryOutput,
    task_fn=_analyze_query_task,
    handler=_handler,
)


