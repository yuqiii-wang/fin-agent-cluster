"""analyze_query — NodeTask for query_node.

Execution layers
----------------
LangGraph layer (``_analyze_query_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Streaming")``, delegates to the
    Celery stream worker via ``delegate_stream``, and returns a ``TaskOutput``.
    On exception, calls ``complete_task(failed=True)`` to emit the failure SSE.

Celery layer (``stream_task.run_stream``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to ``_build_analyze_query_prompt``.
    The Ollama LLM (or mock for test queries) extracts the primary company name
    or stock ticker from the raw user query and returns a JSON answer.

Public export
-------------
``analyze_query``         — ``NodeTask`` instance used by ``QueryNode.build_chain``.
``STREAM_PROMPT_BUILDERS`` — dict slice ``{"analyze_query": _build_analyze_query_prompt}``.
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

_TASK_NAME = "analyze_query"


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class AnalyzeQueryInput(BaseModel):
    """Input for the analyze_query task.

    Attributes:
        query: Raw user query string from the thread initiator.
    """

    query: str = Field(description="Raw user query string.")


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
# Streaming prompt builder — imported by stream_task.py
# ---------------------------------------------------------------------------


def _build_analyze_query_prompt(payload: dict) -> list[BaseMessage]:
    """Build the LangChain message list for analyze_query from a serialised AnalyzeQueryInput.

    Args:
        payload: Serialised ``AnalyzeQueryInput`` dict passed to ``run_stream``.

    Returns:
        LangChain message list (SystemMessage + HumanMessage) for the streaming LLM.
    """
    inp = AnalyzeQueryInput.model_validate(payload)
    system_content = (
        "You are a financial assistant. Extract the primary company name or stock ticker "
        "from user queries. Respond with valid JSON only, using this exact schema:\n"
        '{"stock_name": "<company name or ticker>", "not_seen": false}\n\n'
        "Set not_seen to true if you do not recognise the company or stock, or if the query "
        "does not mention a specific publicly traded company. "
        "If not_seen is true, still try your best to extract what the user might be referring to "
        "in stock_name.\n"
        "No explanation, only the JSON."
    )
    return [
        SystemMessage(content=system_content),
        HumanMessage(content=f"Query: {inp.query}"),
    ]


STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_analyze_query_prompt}


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _analyze_query_task(
    task_input: TaskInput[AnalyzeQueryInput],
) -> TaskOutput[AnalyzeQueryOutput]:
    """LangGraph @task: delegates analyze_query to the Celery stream worker.

    Tokens are streamed to the frontend via Centrifugo.  The final answer is
    parsed as JSON to extract ``stock_name`` and ``not_seen``.

    Args:
        task_input: Typed envelope with TaskContext and AnalyzeQueryInput content.

    Returns:
        TaskOutput wrapping the AnalyzeQueryOutput from the Celery stream worker.
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

        stock_name = str(answer_dict.get("stock_name", "")).strip()
        not_seen = bool(answer_dict.get("not_seen", True))
        output = AnalyzeQueryOutput(stock_name=stock_name, not_seen=not_seen)

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

analyze_query = NodeTask(
    name=_TASK_NAME,
    description="Extract the primary company name or stock ticker from the user query using a streaming LLM.",
    input_type=AnalyzeQueryInput,
    output_type=AnalyzeQueryOutput,
    task_fn=_analyze_query_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("analyze_query runs via the Celery stream worker.")
    ),
)


