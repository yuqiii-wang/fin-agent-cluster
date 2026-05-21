"""get_stock_region — NodeTask for query_node.

Execution layers
----------------
LangGraph layer (``_get_stock_region_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Streaming")``, delegates to the
    Celery stream worker via ``delegate_stream``, and returns a ``TaskOutput``.
    On exception, calls ``complete_task(failed=True)`` to emit the failure SSE.

Celery layer (``stream_task.run_stream``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to ``_build_get_stock_region_prompt``.
    The Ollama LLM returns a JSON object ``{"region": "AMER"}`` with the
    primary exchange region for the given stock.

Public export
-------------
``get_stock_region``       — ``NodeTask`` instance used by ``QueryNode.build_chain``.
``STREAM_PROMPT_BUILDERS`` — dict slice for registration in ``stream_task.py``.
"""

from __future__ import annotations

import json
import logging
from typing import Literal, get_args

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_stream
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "get_stock_region"


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class GetStockRegionInput(BaseModel):
    """Input for the get_stock_region task.

    Attributes:
        stock_name: Company name or stock ticker to look up.
    """

    stock_name: str = Field(description="Company name or stock ticker.")


class GetStockRegionOutput(BaseModel):
    """Output from the get_stock_region task.

    Attributes:
        region: Primary exchange region of the stock.
    """

    region: Literal["APAC", "EMEA", "AMER"] = Field(description="Primary exchange region.")


# ---------------------------------------------------------------------------
# Streaming prompt builder — imported by stream_task.py
# ---------------------------------------------------------------------------


def _build_get_stock_region_prompt(payload: dict) -> list[BaseMessage]:
    """Build the LangChain message list for get_stock_region from a serialised GetStockRegionInput.

    Args:
        payload: Serialised ``GetStockRegionInput`` dict passed to ``run_stream``.

    Returns:
        LangChain message list (SystemMessage + HumanMessage) for the streaming LLM.
    """
    inp = GetStockRegionInput.model_validate(payload)
    valid_regions = list(get_args(GetStockRegionOutput.model_fields["region"].annotation))
    schema = json.dumps(GetStockRegionOutput.model_json_schema())
    system_content = (
        "You are a financial data expert. Identify the primary exchange region where "
        "the given company or stock is primarily listed and traded. "
        f"Respond with valid JSON only, matching this schema:\n{schema}\n\n"
        f"region must be exactly one of: {', '.join(valid_regions)}.\n"
        "No markdown fences, no explanation, only the JSON."
    )
    return [
        SystemMessage(content=system_content),
        HumanMessage(content=f"Company or stock: {inp.stock_name}"),
    ]


STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_get_stock_region_prompt}


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _get_stock_region_task(
    task_input: TaskInput[GetStockRegionInput],
) -> TaskOutput[GetStockRegionOutput]:
    """LangGraph @task: delegates get_stock_region to the Celery stream worker.

    Tokens are streamed to the frontend via Centrifugo.  The final answer is
    parsed as JSON to extract the region code.

    Args:
        task_input: Typed envelope with TaskContext and GetStockRegionInput content.

    Returns:
        TaskOutput wrapping the GetStockRegionOutput from the Celery stream worker.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Streaming",
    )
    try:
        result = await delegate_stream(
            thread_id=ctx.thread_id,
            task_id=ctx.task_id,
            task_name=ctx.task_name,
            node_name=ctx.node_name,
            payload=payload,
        )
        answer_dict: dict = result.get("answer", {})

        region = str(answer_dict.get("region", "")).strip().upper()
        valid_regions = get_args(GetStockRegionOutput.model_fields["region"].annotation)
        if region not in valid_regions:
            logger.error(
                "[get_stock_region] unexpected region %r task_id=%s — defaulting to AMER",
                region, ctx.task_id,
            )
            region = "AMER"
        output = GetStockRegionOutput(region=region)

        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=StreamingTaskOutput(thinking=result.get("thinking"), answer=output.model_dump()).model_dump(),
            view_type="Streaming",
        )
        return TaskOutput(ctx=ctx, content=output)

    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc), view_type="Streaming",
        )
        raise


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

get_stock_region = NodeTask(
    name=_TASK_NAME,
    description="Determine the primary exchange region (APAC, EMEA, AMER) for the given stock using a streaming LLM.",
    input_type=GetStockRegionInput,
    output_type=GetStockRegionOutput,
    task_fn=_get_stock_region_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("get_stock_region runs via the Celery stream worker.")
    ),
)
