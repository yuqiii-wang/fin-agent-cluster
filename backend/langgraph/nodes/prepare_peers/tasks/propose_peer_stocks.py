"""propose_peer_stocks — iterative LLM streaming task for prepare_peers.

Each invocation asks the LLM for 3-5 equity ticker symbols that are likely
peers of the target stock.  Subsequent iterations receive the previously
rejected peer tickers (low correlation with target) so the LLM proposes
fresh candidates.

Execution layers
----------------
LangGraph layer (``_propose_peer_stocks_task`` decorated with ``@task``):
    Checks ``fin_agents.llm_responses`` for a recent identical request; on a
    cache hit, creates and immediately completes a ``ToolCall`` task.
    On a cache miss, calls ``create_task(..., view_type="Streaming")``, delegates
    to the Celery stream worker via ``delegate_stream``, and returns a
    ``TaskOutput``.  On exception, calls ``complete_task(failed=True)``.

Celery layer (``stream_task.run_stream``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to
    ``_build_propose_peer_stocks_prompt``.  The Ollama LLM returns a JSON
    object with ``industry`` and ``peers`` (ticker symbols only).

Public exports
--------------
``propose_peer_stocks``    — ``NodeTask`` instance used by ``AnalyzePeersNode``.
``STREAM_PROMPT_BUILDERS`` — dict slice for registration in ``stream_task.py``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_stream
from backend.db.postgres.connection import raw_conn
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import NodeContext, TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "propose_peer_stocks"
_CACHE_TTL_HOURS = 4

# ---------------------------------------------------------------------------
# Cache lookup SQL
# ---------------------------------------------------------------------------

_GET_CACHED_LLM_RESPONSE = """
    SELECT lr.thinking, lr.answer
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
      AND te.input->>'stock_name'         = %s
      AND (te.input->>'iteration')::int   = %s
      AND te.input->'excluded_peers'      @> %s::jsonb
      AND te.input->'excluded_peers'      <@ %s::jsonb
      AND lr.answer   IS NOT NULL
      AND lr.ts       > NOW() - INTERVAL '%s hours'
    ORDER BY lr.ts DESC
    LIMIT 1
"""


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class ProposePeerStocksInput(BaseModel):
    """Input for the propose_peer_stocks task.

    Attributes:
        stock_name:     Company name or stock ticker to find peers for.
        excluded_peers: Ticker symbols already tried whose correlation with the
                        target stock was below the acceptance threshold.  The LLM
                        should propose different stocks not in this list.
        iteration:      Current loop iteration (1–3).  Used to provide context
                        in the prompt when re-proposing after weak correlations.
    """

    stock_name: str = Field(description="Company name or stock ticker.")
    excluded_peers: list[str] = Field(
        default_factory=list,
        description="Previously tried tickers with weak correlation — avoid these.",
    )
    iteration: int = Field(default=1, ge=1, le=3, description="Current proposal iteration (1–3).")


class ProposePeerStocksOutput(BaseModel):
    """Output from the propose_peer_stocks task.

    Attributes:
        industry: Primary industry sector the company operates in.
        peers:    3-5 equity ticker symbols of likely peer companies.
    """

    industry: str = Field(description="Primary industry sector of the company.")
    peers: list[str] = Field(
        default_factory=list,
        description="5–8 ticker symbols of likely peer companies.",
    )


# ---------------------------------------------------------------------------
# Prompt template (module-level global)
# ---------------------------------------------------------------------------

_PROPOSE_PEER_STOCKS_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a quantitative equity analyst. "
     "Given a company or stock ticker, identify its primary industry sector and "
     "5 to 8 peer companies listed on public exchanges.\n\n"
     "IMPORTANT: Respond with valid JSON only using this exact schema:\n"
     '{{"industry": "<industry>", "peers": ["<TICKER1>", "<TICKER2>", ...]}}\n\n'
     "Rules:\n"
     "- industry: primary industry sector (e.g. 'Semiconductors', 'E-Commerce').\n"
     "- peers: USE ONLY EXCHANGE TICKER SYMBOLS (e.g. 'MSFT', 'GOOGL', '005930.KS') — "
     "NOT company names.\n"
     "- Peers must operate in the same or very similar business AND be primarily listed "
     "in the same geographic region as the target.\n"
     "- Provide exactly 5 to 8 ticker symbols.\n"
     "No markdown fences, no explanation, only the JSON."),
    ("human",
     "Find industry sector and peer ticker symbols for: {stock_name}"
     "{excluded_clause}{corr_context_clause}{iteration_clause}"),
])


# ---------------------------------------------------------------------------
# Streaming prompt builder — imported by stream_task.py
# ---------------------------------------------------------------------------


def _build_propose_peer_stocks_prompt(payload: dict) -> list[BaseMessage]:
    """Build the LangChain message list for propose_peer_stocks.

    Constructs an iteration-aware prompt that directs the LLM to avoid
    previously tried tickers and propose different candidates.

    Args:
        payload: Serialised ``ProposePeerStocksInput`` dict.

    Returns:
        LangChain message list (SystemMessage + HumanMessage) for the streaming LLM.
    """
    inp = ProposePeerStocksInput.model_validate(payload)

    excluded_clause = ""
    if inp.excluded_peers:
        excluded_clause = (
            f"\n\nDo NOT propose any of these tickers — they have already been evaluated "
            f"and showed weak statistical correlation with the target: "
            f"{', '.join(inp.excluded_peers)}.\n"
            "Propose genuinely different peer candidates."
        )

    agent_memory: list[dict] = payload.get("_agent_memory", [])
    corr_context_clause = ""
    if agent_memory:
        lines = []
        for entry in agent_memory:
            sym = entry.get("symbol", "")
            corr = entry.get("corr", 0.0)
            status = entry.get("status", "rejected")
            lines.append(f"  - {sym}: correlation={corr:.3f} ({status})")
        corr_context_clause = (
            "\n\nCorrelation analysis from previous iterations (Pearson abs(r) with target):\n"
            + "\n".join(lines)
            + "\nUse this to guide your next proposals towards peers with strong "
            "price co-movement with the target stock."
        )

    iteration_clause = ""
    if inp.iteration > 1:
        iteration_clause = (
            f"\n\nThis is proposal attempt {inp.iteration} of 3. "
            "Focus on alternative peers that are less obvious but still operate "
            "in a closely related segment."
        )

    return _PROPOSE_PEER_STOCKS_PROMPT.format_messages(
        stock_name=inp.stock_name,
        excluded_clause=excluded_clause,
        corr_context_clause=corr_context_clause,
        iteration_clause=iteration_clause,
    )


STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_propose_peer_stocks_prompt}


# ---------------------------------------------------------------------------
# PG cache function
# ---------------------------------------------------------------------------


async def _propose_peer_stocks_pg_cache(
    inp: ProposePeerStocksInput, ctx: NodeContext
) -> ProposePeerStocksOutput | None:
    """Check pg for a recent identical propose_peer_stocks result within the last 4 hours.

    Looks up ``fin_agents.llm_responses`` (via tasks + task_executions) for a
    completed ``propose_peer_stocks`` call with identical normalised inputs.

    Args:
        inp: Typed task input.
        ctx: Current node context (unused; present for signature compatibility).

    Returns:
        Parsed ``ProposePeerStocksOutput`` on a cache hit, or ``None``.
    """
    # Skip cache when agent memory is populated — subsequent iterations carry
    # unique correlation context that makes exact cache matches unlikely.
    if ctx.metadata.get("agent_memory"):
        return None

    excluded_json = json.dumps(sorted(inp.excluded_peers))
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            _GET_CACHED_LLM_RESPONSE,
            (
                _TASK_NAME,
                inp.stock_name.upper(),
                inp.iteration,
                excluded_json,
                excluded_json,
                _CACHE_TTL_HOURS,
            ),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    try:
        answer_dict: dict = json.loads(row["answer"]) if row.get("answer") else {}
    except (json.JSONDecodeError, TypeError):
        answer_dict = {}
    industry = str(answer_dict.get("industry", "")).strip()
    peers = [str(p).strip().upper() for p in answer_dict.get("peers", [])]
    return ProposePeerStocksOutput(industry=industry, peers=peers)


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _propose_peer_stocks_task(
    task_input: TaskInput[ProposePeerStocksInput],
) -> TaskOutput[ProposePeerStocksOutput]:
    """LangGraph @task: delegates propose_peer_stocks to the Celery stream worker.

    The pg cache check is handled upstream by ``run_task`` via ``pg_cache_fn``.
    This function is only reached on a cache miss.

    Tokens are streamed to the frontend via Centrifugo.  The final answer is
    parsed as JSON to extract ``industry`` and ``peers``.

    Args:
        task_input: Typed envelope with TaskContext and ProposePeerStocksInput.

    Returns:
        TaskOutput wrapping ProposePeerStocksOutput.
    """
    ctx = task_input.ctx
    content = task_input.content
    payload = content.model_dump()
    # Inject agent memory so the Celery stream worker's prompt builder can render
    # previously explored symbols and their correlation scores as LLM context.
    if task_input.memory:
        payload["_agent_memory"] = task_input.memory

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
        peers = [str(p).strip().upper() for p in answer_dict.get("peers", [])]
        output = ProposePeerStocksOutput(industry=industry, peers=peers)

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
# NodeTask registration
# ---------------------------------------------------------------------------

propose_peer_stocks = NodeTask(
    name=_TASK_NAME,
    description=(
        "Iteratively propose 5–8 equity ticker symbols as likely peers of the target stock "
        "using a streaming LLM.  Accepts excluded tickers (already validated with weak "
        "correlation) so subsequent iterations propose genuinely different candidates."
    ),
    input_type=ProposePeerStocksInput,
    output_type=ProposePeerStocksOutput,
    task_fn=_propose_peer_stocks_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("propose_peer_stocks runs via the Celery stream worker.")
    ),
    pg_cache_fn=_propose_peer_stocks_pg_cache,
)

__all__ = ["propose_peer_stocks", "ProposePeerStocksInput", "ProposePeerStocksOutput", "STREAM_PROMPT_BUILDERS"]
