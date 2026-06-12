"""analyze_stock_from_web_if_not_seen — NodeTask for query_node.

This is a Streaming task: it uses ``delegate_stream`` so the LLM analysis is
streamed token-by-token to the frontend via Centrifugo.

Execution layers
----------------
LangGraph layer (``_analyze_stock_from_web_if_not_seen_task``):
    Calls ``create_task(..., view_type="Streaming")``, delegates to the
    Celery stream worker via ``delegate_stream``, calls ``complete_task`` on
    success.  If the LLM still reports the stock as not recognised
    (``not_seen=True`` in the parsed answer), raises ``ValueError`` to fail
    the node with a clear error message.

Celery layer:
    Handled by ``stream_task.run_stream`` which dispatches to
    ``_build_analyze_web_stock_prompt`` registered in ``STREAM_PROMPT_BUILDERS``.
    The prompt builder is implemented in this module and imported by
    ``stream_task`` at startup.

Public export
-------------
``analyze_stock_from_web_if_not_seen`` — ``NodeTask`` instance.
``STREAM_PROMPT_BUILDERS``             — dict slice consumed by ``stream_task``.
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate

from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_stream
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "analyze_stock_from_web_if_not_seen"

# ---------------------------------------------------------------------------
# Intermediate models (task-local)
# ---------------------------------------------------------------------------

class AnalyzeWebStockInput(BaseModel):
    """Input for the ``analyze_stock_from_web_if_not_seen`` streaming task.

    Attributes:
        stock_name: Best-guess company name / ticker from ``analyze_query``.
        query:      Original raw user query.
        web_title:  Title of the Wikipedia page fetched by the web task.
        web_url:    Canonical URL of the fetched page.
        web_content: Plain-text extract from the fetched page (≤2 000 chars).
    """

    stock_name: str = Field(description="Best-guess stock name from analyze_query.")
    query: str = Field(description="Original raw user query.")
    web_title: str = Field(default="", description="Title of the fetched Wikipedia page.")
    web_url: str = Field(default="", description="URL of the fetched page.")
    web_content: str = Field(default="", description="Plain-text extract from the fetched page.")

class AnalyzeWebStockOutput(BaseModel):
    """Output from the ``analyze_stock_from_web_if_not_seen`` streaming task.

    Attributes:
        stock_name: Confirmed company name or ticker after analysing web content.
        not_seen:   True when the web content was still insufficient to identify
                    the stock (triggers a node failure).
    """

    stock_name: str = Field(description="Confirmed company name or ticker.")
    not_seen: bool = Field(default=False, description="True when the stock could not be identified.")

# ---------------------------------------------------------------------------
# Prompt template (module-level global)
# ---------------------------------------------------------------------------

_ANALYZE_WEB_STOCK_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a financial analyst. Identify company names and stock tickers from web content. "
     "Respond with valid JSON only:\n"
     '{{"stock_name": "<exact company name or ticker>", "not_seen": false}}\n\n'
     "Set not_seen to true ONLY if the web content clearly does not match any known publicly "
     "traded company. No explanation, only the JSON."),
    ("human",
     'The user asked: "{query}"\n\n'
     'We could not initially identify the stock "{stock_name}". '
     "We fetched the following information from the web:\n\n"
     "{web_section}\n\n"
     "Based on this information, identify the exact company name and primary stock ticker symbol."),
])

# ---------------------------------------------------------------------------
# Streaming prompt builder — imported by stream_task.py
# ---------------------------------------------------------------------------

def _build_analyze_web_stock_prompt(payload: dict) -> list[BaseMessage]:
    """Build the LangChain message list from an ``AnalyzeWebStockInput`` payload dict.

    Args:
        payload: Serialised ``AnalyzeWebStockInput`` dict passed to ``run_stream``.

    Returns:
        LangChain message list (SystemMessage + HumanMessage) for the streaming LLM.
    """
    inp = AnalyzeWebStockInput.model_validate(payload)
    web_section = (
        f"Title: {inp.web_title}\nURL: {inp.web_url}\n\n{inp.web_content}"
        if inp.web_content
        else "No web content was retrieved."
    )
    return _ANALYZE_WEB_STOCK_PROMPT.format_messages(
        query=inp.query,
        stock_name=inp.stock_name,
        web_section=web_section,
    )

STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_analyze_web_stock_prompt}

# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------

async def _analyze_stock_from_web_if_not_seen_task(
    task_input: TaskInput[AnalyzeWebStockInput],
) -> TaskOutput[AnalyzeWebStockOutput]:
    """LangGraph @task: streams web-stock analysis to the frontend via Centrifugo.

    Delegates to the Celery stream worker.  Parses the final LLM answer as
    JSON to extract ``stock_name`` and ``not_seen``.  Raises ``ValueError``
    when ``not_seen`` is still True after web analysis — this fails the node
    with a clear user-visible error.

    Args:
        task_input: Typed envelope with TaskContext and AnalyzeWebStockInput content.

    Returns:
        TaskOutput wrapping the AnalyzeWebStockOutput.

    Raises:
        ValueError: When the LLM still cannot identify the stock after web lookup.
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
        raw_answer = result.get("answer", {})
        if isinstance(raw_answer, str):
            try:
                answer_dict = json.loads(raw_answer)
            except (json.JSONDecodeError, TypeError):
                logger.error(
                    "[analyze_stock_from_web] answer JSON parse failed task_id=%s — raw: %r",
                    ctx.task_id, raw_answer,
                )
                answer_dict = {}
        else:
            answer_dict = raw_answer

        stock_name = str(answer_dict.get("stock_name", task_input.content.stock_name)).strip()
        not_seen = bool(answer_dict.get("not_seen", True))

        output = AnalyzeWebStockOutput(stock_name=stock_name, not_seen=not_seen)
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=StreamingTaskOutput(thinking=result.get("thinking"), answer=output.model_dump()).model_dump(),
            view_type="Streaming",
        )

        if not_seen:
            raise ValueError(
                f"Stock not recognised even after web lookup (query={task_input.content.query!r})"
            )

        return TaskOutput(ctx=ctx, content=output)

    except ValueError:
        # not_seen failure — already called complete_task above; re-raise to fail the node.
        raise
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc), view_type="Streaming",
        )
        raise

# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

analyze_stock_from_web_if_not_seen = NodeTask(
    name=_TASK_NAME,
    description=(
        "Stream an LLM analysis of web-fetched content to identify the stock. "
        "Fails the node when the stock still cannot be identified after web lookup."
    ),
    input_type=AnalyzeWebStockInput,
    output_type=AnalyzeWebStockOutput,
    task_fn=_analyze_stock_from_web_if_not_seen_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("analyze_stock_from_web_if_not_seen runs via the Celery stream worker.")
    ),
)
