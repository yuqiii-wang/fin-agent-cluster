"""propose_industry_news_topics -- iterative LLM streaming task for prepare_industry_news.

Given a stock ticker, asks the LLM to identify the company's industry sector and
propose 5-8 specific news topics that best capture industry-level events relevant
to that company (e.g. "AI chip demand", "cloud spending", "semiconductor regulation").

Execution layers
----------------
LangGraph layer (``_propose_industry_news_topics_task`` decorated with ``@task``):
    Checks ``fin_agents.llm_responses`` for a recent identical request (4-hour TTL);
    on a cache hit, creates and immediately completes a ``ToolCall`` task.
    On a cache miss, calls ``create_task(..., view_type="Streaming")``, delegates
    to the Celery stream worker via ``delegate_stream``, and returns a ``TaskOutput``.
    On exception, calls ``complete_task(failed=True)``.

Celery layer (``stream_task.run_stream``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to
    ``_build_propose_industry_news_topics_prompt``.  The LLM returns a JSON object
    with ``industry`` and ``topics``.

Public exports
--------------
``propose_industry_news_topics``  -- ``NodeTask`` instance used by ``PrepareIndustryNewsNode``.
``STREAM_PROMPT_BUILDERS``        -- dict slice for registration in ``stream_task.py``.
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate

from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_stream
from backend.db.postgres.connection import raw_conn
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import NodeContext, TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "propose_industry_news_topics"
_CACHE_TTL_HOURS = 4

# ---------------------------------------------------------------------------
# Cache lookup SQL
# ---------------------------------------------------------------------------

_GET_CACHED_LLM_RESPONSE = """
    SELECT lr.answer
    FROM fin_agents.llm_responses lr
    JOIN fin_agents.tasks t ON t.task_id = lr.task_id
    JOIN LATERAL (
        SELECT input
        FROM fin_agents.task_executions
        WHERE task_id = t.task_id
        ORDER BY retry_num DESC
        LIMIT 1
    ) te ON TRUE
    WHERE t.task_name = %s
      AND t.status    = 'completed'
      AND te.input->>'stock_name' = %s
      AND lr.answer   IS NOT NULL
      AND lr.ts       > NOW() - INTERVAL '%s hours'
    ORDER BY lr.ts DESC
    LIMIT 1
"""

# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------

class ProposeIndustryNewsTopicsInput(BaseModel):
    """Input for the propose_industry_news_topics task.

    Attributes:
        stock_name: Company name or stock ticker to propose industry topics for.
    """

    stock_name: str = Field(description="Company name or stock ticker.")

class ProposeIndustryNewsTopicsOutput(BaseModel):
    """Output from the propose_industry_news_topics task.

    Attributes:
        industry: Primary industry sector the company operates in.
        topics:   5-8 specific news topic keywords relevant to the company's industry.
    """

    industry: str = Field(description="Primary industry sector of the company.")
    topics: list[str] = Field(
        default_factory=list,
        description="5-8 industry-specific news topic keywords.",
    )

# ---------------------------------------------------------------------------
# Prompt template (module-level global)
# ---------------------------------------------------------------------------

_PROPOSE_INDUSTRY_NEWS_TOPICS_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a financial news analyst specialising in industry and sector research. "
     "Given a company or stock ticker, identify its primary industry sector and "
     "propose 5 to 8 specific news topic keywords that best capture industry-level "
     "events relevant to that company.\n\n"
     "IMPORTANT: Respond with valid JSON only using this exact schema:\n"
     '{{"industry": "<industry>", "topics": ["<topic1>", "<topic2>", ...]}}\n\n'
     "Rules:\n"
     "- industry: primary industry sector (e.g. 'Semiconductors', 'Cloud Computing', "
     "'E-Commerce').\n"
     "- topics: 5 to 8 concise topic keywords specific enough to surface relevant "
     "industry news (e.g. 'AI chip demand', 'cloud spending', 'semiconductor regulation', "
     "'supply chain disruption').\n"
     "- Topics should reflect the company's competitive landscape and macro sector "
     "drivers -- not company-specific earnings or analyst coverage.\n"
     "No markdown fences, no explanation, only the JSON."),
    ("human",
     "Identify the industry and propose industry news topics for: {stock_name}"),
])

# ---------------------------------------------------------------------------
# Streaming prompt builder -- imported by stream_task.py
# ---------------------------------------------------------------------------

def _build_propose_industry_news_topics_prompt(payload: dict) -> list[BaseMessage]:
    """Build the LangChain message list for propose_industry_news_topics.

    Args:
        payload: Serialised ``ProposeIndustryNewsTopicsInput`` dict.

    Returns:
        LangChain message list (SystemMessage + HumanMessage) for the streaming LLM.
    """
    inp = ProposeIndustryNewsTopicsInput.model_validate(payload)
    return _PROPOSE_INDUSTRY_NEWS_TOPICS_PROMPT.format_messages(
        stock_name=inp.stock_name,
    )

STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_propose_industry_news_topics_prompt}

# ---------------------------------------------------------------------------
# PG cache function
# ---------------------------------------------------------------------------

async def _propose_industry_news_topics_pg_cache(
    inp: ProposeIndustryNewsTopicsInput, ctx: NodeContext
) -> ProposeIndustryNewsTopicsOutput | None:
    """Check pg for a recent identical propose_industry_news_topics result.

    Looks up ``fin_agents.llm_responses`` for a completed call with the same
    normalised stock name within the last ``_CACHE_TTL_HOURS`` hours.

    Args:
        inp: Typed task input.
        ctx: Current node context.

    Returns:
        Parsed ``ProposeIndustryNewsTopicsOutput`` on a cache hit, or ``None``.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            _GET_CACHED_LLM_RESPONSE,
            (_TASK_NAME, inp.stock_name.upper(), _CACHE_TTL_HOURS),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    try:
        answer_dict: dict = json.loads(row["answer"]) if row.get("answer") else {}
    except (json.JSONDecodeError, TypeError):
        return None
    industry = str(answer_dict.get("industry", "")).strip()
    topics = [str(t).strip() for t in answer_dict.get("topics", []) if t]
    if not topics:
        return None
    return ProposeIndustryNewsTopicsOutput(industry=industry, topics=topics)

# ---------------------------------------------------------------------------
# LangGraph layer -- @task orchestration
# ---------------------------------------------------------------------------

async def _propose_industry_news_topics_task(
    task_input: TaskInput[ProposeIndustryNewsTopicsInput],
) -> TaskOutput[ProposeIndustryNewsTopicsOutput]:
    """LangGraph @task: delegates propose_industry_news_topics to the Celery stream worker.

    The pg cache check is handled upstream by ``run_task`` via ``pg_cache_fn``.
    This function is only reached on a cache miss.

    Tokens are streamed to the frontend via Centrifugo.  The final answer is
    parsed as JSON to extract ``industry`` and ``topics``.

    Args:
        task_input: Typed envelope with TaskContext and ProposeIndustryNewsTopicsInput.

    Returns:
        TaskOutput wrapping ProposeIndustryNewsTopicsOutput.
    """
    ctx = task_input.ctx
    content = task_input.content
    payload = content.model_dump()

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
        answer_dict = result.get("answer", {})

        industry = str(answer_dict.get("industry", "")).strip()
        topics = [str(t).strip() for t in answer_dict.get("topics", []) if t]
        output = ProposeIndustryNewsTopicsOutput(industry=industry, topics=topics)

        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=StreamingTaskOutput(
                thinking=result.get("thinking"), answer=output.model_dump()
            ).model_dump(),
            view_type="Streaming",
        )
        return TaskOutput(ctx=ctx, content=output, thinking=result.get("thinking"))

    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc), view_type="Streaming",
        )
        raise

# ---------------------------------------------------------------------------
# NodeTask instance -- imported by PrepareIndustryNewsNode
# ---------------------------------------------------------------------------

propose_industry_news_topics = NodeTask(
    name=_TASK_NAME,
    description=(
        "Ask the LLM to identify the company's industry sector and propose 5-8 "
        "specific news topic keywords that best capture industry-level events "
        "relevant to that company."
    ),
    input_type=ProposeIndustryNewsTopicsInput,
    output_type=ProposeIndustryNewsTopicsOutput,
    task_fn=_propose_industry_news_topics_task,
    handler=None,
    pg_cache_fn=_propose_industry_news_topics_pg_cache,
)

__all__ = [
    "propose_industry_news_topics",
    "ProposeIndustryNewsTopicsInput",
    "ProposeIndustryNewsTopicsOutput",
    "STREAM_PROMPT_BUILDERS",
]
