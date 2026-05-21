"""get_stock_industry_peers — NodeTask for query_node.

Execution layers
----------------
LangGraph layer (``_get_stock_industry_peers_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Streaming")``, delegates to the
    Celery stream worker via ``delegate_stream``, and returns a ``TaskOutput``.
    On exception, calls ``complete_task(failed=True)`` to emit the failure SSE.

Celery layer (``stream_task.run_stream``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to
    ``_build_get_stock_industry_peers_prompt``.  The Ollama LLM returns a JSON
    object with the primary industry sector and 3–5 regional peer companies.

Public export
-------------
``get_stock_industry_peers`` — ``NodeTask`` instance used by ``QueryNode.build_chain``.
``STREAM_PROMPT_BUILDERS``   — dict slice for registration in ``stream_task.py``.
"""

from __future__ import annotations

import logging

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_stream
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "get_stock_industry_peers"


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class GetStockIndustryPeersInput(BaseModel):
    """Input for the get_stock_industry_peers task.

    Attributes:
        stock_name: Company name or stock ticker to look up.
    """

    stock_name: str = Field(description="Company name or stock ticker.")




class GetStockIndustryPeersOutput(BaseModel):
    """Output from the get_stock_industry_peers task.

    Attributes:
        industry: Primary industry sector the company operates in.
        peers: Peer companies operating in a similar business and the same region.
    """

    industry: str = Field(description="Primary industry sector of the company.")
    peers: list[str] = Field(default_factory=list, description="Peer companies in similar business and region.")


# ---------------------------------------------------------------------------
# Streaming prompt builder — imported by stream_task.py
# ---------------------------------------------------------------------------


def _build_get_stock_industry_peers_prompt(payload: dict) -> list[BaseMessage]:
    """Build the LangChain message list for get_stock_industry_peers from a serialised GetStockIndustryPeersInput.

    Args:
        payload: Serialised ``GetStockIndustryPeersInput`` dict passed to ``run_stream``.

    Returns:
        LangChain message list (SystemMessage + HumanMessage) for the streaming LLM.
    """
    inp = GetStockIndustryPeersInput.model_validate(payload)
    system_content = (
        "You are a financial analyst. Respond with valid JSON only, using this exact schema:\n"
        '{\"industry\": \"<industry>\", \"peers\": [\"<company1>\", \"<company2>\", ...]}\n\n'
        "Rules:\n"
        "- industry: the primary industry sector of the company "
        "(e.g. 'Semiconductors', 'Consumer Electronics', 'E-Commerce').\n"
        "- peers: 3 to 5 peer companies that operate in the same or very similar business "
        "and are primarily based and listed in the same geographic region.\n"
        "No markdown fences, no explanation, only the JSON."
    )
    return [
        SystemMessage(content=system_content),
        HumanMessage(content=f"Company or stock: {inp.stock_name}"),
    ]


STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_get_stock_industry_peers_prompt}


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _get_stock_industry_peers_task(
    task_input: TaskInput[GetStockIndustryPeersInput],
) -> TaskOutput[GetStockIndustryPeersOutput]:
    """LangGraph @task: delegates get_stock_industry_peers to the Celery stream worker.

    Tokens are streamed to the frontend via Centrifugo.  The final answer is
    parsed as JSON to extract ``industry`` and ``peers``.

    Args:
        task_input: Typed envelope with TaskContext and GetStockIndustryPeersInput content.

    Returns:
        TaskOutput wrapping the GetStockIndustryPeersOutput from the Celery stream worker.
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

        industry = str(answer_dict.get("industry", "")).strip()
        peers = [str(p) for p in answer_dict.get("peers", [])]
        output = GetStockIndustryPeersOutput(industry=industry, peers=peers)

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

get_stock_industry_peers = NodeTask(
    name=_TASK_NAME,
    description=(
        "Determine the primary industry and 3-5 regional peers for the given stock using a streaming LLM. "
        "Peers must operate in a similar business and the same geographic region."
    ),
    input_type=GetStockIndustryPeersInput,
    output_type=GetStockIndustryPeersOutput,
    task_fn=_get_stock_industry_peers_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("get_stock_industry_peers runs via the Celery stream worker.")
    ),
)
