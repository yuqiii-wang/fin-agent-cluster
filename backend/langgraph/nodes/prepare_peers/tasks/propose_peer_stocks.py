"""propose_peer_stocks — iterative LLM streaming task for prepare_peers.

Each invocation asks the LLM for 3-5 equity ticker symbols that are likely
peers of the target stock.  Subsequent iterations receive the previously
rejected peer tickers (low correlation with target) so the LLM proposes
fresh candidates.

Execution layers
----------------
LangGraph layer (``_propose_peer_stocks_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Streaming")``, delegates to the
    Celery stream worker via ``delegate_stream``, and returns a ``TaskOutput``.
    On exception, calls ``complete_task(failed=True)`` to emit the failure SSE.

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

_TASK_NAME = "propose_peer_stocks"


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

    system_content = (
        "You are a quantitative equity analyst. "
        "Given a company or stock ticker, identify its primary industry sector and "
        "5 to 8 peer companies listed on public exchanges.\n\n"
        "IMPORTANT: Respond with valid JSON only using this exact schema:\n"
        '{\"industry\": \"<industry>\", \"peers\": [\"<TICKER1>\", \"<TICKER2>\", ...]}\n\n'
        "Rules:\n"
        "- industry: primary industry sector (e.g. 'Semiconductors', 'E-Commerce').\n"
        "- peers: USE ONLY EXCHANGE TICKER SYMBOLS (e.g. 'MSFT', 'GOOGL', '005930.KS') — "
        "NOT company names.\n"
        "- Peers must operate in the same or very similar business AND be primarily listed "
        "in the same geographic region as the target.\n"
        "- Provide exactly 5 to 8 ticker symbols.\n"
        "No markdown fences, no explanation, only the JSON."
    )

    excluded_clause = ""
    if inp.excluded_peers:
        excluded_clause = (
            f"\n\nDo NOT propose any of these tickers — they have already been evaluated "
            f"and showed weak statistical correlation with the target: "
            f"{', '.join(inp.excluded_peers)}.\n"
            "Propose genuinely different peer candidates."
        )

    iteration_clause = ""
    if inp.iteration > 1:
        iteration_clause = (
            f"\n\nThis is proposal attempt {inp.iteration} of 3. "
            "Focus on alternative peers that are less obvious but still operate "
            "in a closely related segment."
        )

    human_content = (
        f"Find industry sector and peer ticker symbols for: {inp.stock_name}"
        f"{excluded_clause}{iteration_clause}"
    )

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=human_content),
    ]


STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_propose_peer_stocks_prompt}


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _propose_peer_stocks_task(
    task_input: TaskInput[ProposePeerStocksInput],
) -> TaskOutput[ProposePeerStocksOutput]:
    """LangGraph @task: delegates propose_peer_stocks to the Celery stream worker.

    Tokens are streamed to the frontend via Centrifugo.  The final answer is
    parsed as JSON to extract ``industry`` and ``peers`` (ticker symbols).

    Args:
        task_input: Typed envelope with TaskContext and ProposePeerStocksInput.

    Returns:
        TaskOutput wrapping ProposePeerStocksOutput.
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
)

__all__ = ["propose_peer_stocks", "ProposePeerStocksInput", "ProposePeerStocksOutput", "STREAM_PROMPT_BUILDERS"]
