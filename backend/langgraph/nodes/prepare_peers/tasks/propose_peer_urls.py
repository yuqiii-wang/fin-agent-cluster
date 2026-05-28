"""propose_peer_urls — propose a research URL for peer stock discovery.

For **iteration 1** the URL is built deterministically from the known MarketBeat
competitors-and-alternatives page via :func:`_competitors_url` (no LLM call).
For **iterations 2–3** a streaming LLM proposes a different financial data source.

Execution layers
----------------
LangGraph layer (``_propose_peer_urls_task`` decorated with ``@task``):
    Iteration 1 — derives the yfinance exchange code from ``quant_raw``, maps it
    to the MarketBeat exchange name via
    :func:`~backend.resources.web_knowledge.urls.yf_exchange_to_marketbeat`, builds
    the URL with :func:`~backend.resources.web_knowledge.urls.build_url`, and returns
    a ``TaskOutput`` immediately (no Celery delegation).

    Iterations 2–3 — calls ``create_task(..., view_type="Streaming")``, delegates to
    the Celery stream worker via ``delegate_stream``, parses the JSON answer, and
    returns a ``TaskOutput``.  On exception, calls ``complete_task(failed=True)``.

Celery layer (``stream_task.run_stream``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to
    ``_build_propose_peer_urls_prompt``.  The LLM returns a JSON object with
    ``url`` (the research URL) and ``reasoning`` (why this source is suitable).

Public exports
--------------
``propose_peer_urls``      — ``NodeTask`` instance used by ``AnalyzePeersNode``.
``ProposePeerUrlsInput``   — Pydantic input model.
``ProposePeerUrlsOutput``  — Pydantic output model.
``STREAM_PROMPT_BUILDERS`` — dict slice for registration in ``stream_task.py``.
"""

from __future__ import annotations

import logging

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_stream
from backend.db.postgres.queries.fin_markets_quant import get_yf_exchange_for_symbol
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.models.view_types import TASK_VIEW_JSON, TASK_VIEW_STREAMING
from backend.resources.web_knowledge.models import WebPageType
from backend.resources.web_knowledge.urls import build_url, yf_exchange_to_marketbeat

logger = logging.getLogger(__name__)

_TASK_NAME = "propose_peer_urls"


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class ProposePeerUrlsInput(BaseModel):
    """Input for the propose_peer_urls task.

    Attributes:
        stock_name:    Company name or stock ticker to find peers for.
        excluded_urls: URLs already tried in earlier iterations; the LLM
                       should propose a different source not in this list.
        iteration:     Current loop iteration (1–3).
    """

    stock_name: str = Field(description="Company name or stock ticker.")
    excluded_urls: list[str] = Field(
        default_factory=list,
        description="URLs already tried — avoid repeating these.",
    )
    iteration: int = Field(default=1, ge=1, le=3, description="Current proposal iteration (1–3).")


class ProposePeerUrlsOutput(BaseModel):
    """Output from the propose_peer_urls task.

    Attributes:
        url:       A public URL whose page lists peer/comparable companies
                   for the target stock.
        reasoning: LLM's brief rationale for why this source is suitable.
    """

    url: str = Field(description="URL of a page that lists peers of the target stock.")
    reasoning: str = Field(default="", description="Why this URL is a good source for peer discovery.")


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_PROPOSE_PEER_URLS_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a financial research assistant. "
     "Given a stock ticker or company name, propose a single public URL whose page "
     "lists the company's peer or comparable stocks.\n\n"
     "Good URL types:\n"
     "- Yahoo Finance peers tab: https://finance.yahoo.com/quote/<TICKER>/analysis/\n"
     "- Finviz stock screener filtered to the same sector/industry\n"
     "- Macrotrends or Wisesheets comparison pages\n"
     "- Any reliable financial data site that shows a 'similar companies' or "
     "'competitors' section for the target ticker\n\n"
     "Respond ONLY with valid JSON — no preamble, no explanation outside the JSON:\n"
     '{{ "url": "<full https URL>", "reasoning": "<1-2 sentences>" }}'),
    ("human",
     "Propose a peer-discovery URL for: {stock_name}"
     "{excluded_clause}"
     "{iteration_clause}"),
])


# ---------------------------------------------------------------------------
# Streaming prompt builder
# ---------------------------------------------------------------------------


def _build_propose_peer_urls_prompt(payload: dict) -> list[BaseMessage]:
    """Build the LangChain message list for propose_peer_urls.

    Args:
        payload: Serialised :class:`ProposePeerUrlsInput` dict.

    Returns:
        LangChain message list (SystemMessage + HumanMessage).
    """
    inp = ProposePeerUrlsInput.model_validate(payload)

    excluded_clause = ""
    if inp.excluded_urls:
        excluded_clause = (
            "\n\nDo NOT propose any of these URLs — they have already been tried:\n"
            + "\n".join(f"  - {u}" for u in inp.excluded_urls)
            + "\nPropose a genuinely different source."
        )

    iteration_clause = ""
    if inp.iteration > 1:
        iteration_clause = (
            f"\n\nThis is attempt {inp.iteration} of 3. "
            "Try a different financial data provider than the ones already used."
        )

    return _PROPOSE_PEER_URLS_PROMPT.format_messages(
        stock_name=inp.stock_name,
        excluded_clause=excluded_clause,
        iteration_clause=iteration_clause,
    )


STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_propose_peer_urls_prompt}


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _propose_peer_urls_task(
    task_input: TaskInput[ProposePeerUrlsInput],
) -> TaskOutput[ProposePeerUrlsOutput]:
    """LangGraph @task: propose a peer-discovery URL.

    Iteration 1 builds the MarketBeat competitors URL deterministically from the
    yfinance exchange code stored in ``quant_raw``.  Iterations 2–3 delegate to
    the Celery stream worker.

    Args:
        task_input: Typed envelope with TaskContext and ProposePeerUrlsInput.

    Returns:
        TaskOutput wrapping ProposePeerUrlsOutput.
    """
    ctx = task_input.ctx
    inp = task_input.content
    payload = inp.model_dump()

    # ── Iteration 1: use _competitors_url deterministically (no LLM) ──────────
    if inp.iteration == 1:
        symbol = inp.stock_name.strip().upper()
        marketbeat_exchange: str | None = None
        yf_exchange = await get_yf_exchange_for_symbol(symbol)
        if yf_exchange:
            marketbeat_exchange = yf_exchange_to_marketbeat(yf_exchange)
        if marketbeat_exchange:
            try:
                url = build_url(WebPageType.competitors, symbol, marketbeat_exchange)
                output = ProposePeerUrlsOutput(
                    url=url,
                    reasoning=(
                        f"MarketBeat competitors page for {symbol} on {marketbeat_exchange} "
                        f"(yf_exchange={yf_exchange})."
                    ),
                )
                await create_task(
                    ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
                    payload, view_type=TASK_VIEW_JSON,
                )
                await complete_task(
                    ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
                    output_data=output.model_dump(),
                    view_type=TASK_VIEW_JSON,
                )
                return TaskOutput(ctx=ctx, content=output)
            except ValueError:
                pass  # exchange resolved but build_url raised — fall through to LLM

    # ── Iterations 2–3 (or iteration 1 fallback when exchange not found) ───
    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type=TASK_VIEW_STREAMING,
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
        output = ProposePeerUrlsOutput(
            url=str(answer_dict.get("url", "")).strip(),
            reasoning=str(answer_dict.get("reasoning", "")).strip(),
        )
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=StreamingTaskOutput(
                thinking=result.get("thinking"),
                answer=output.model_dump(),
            ).model_dump(),
            view_type=TASK_VIEW_STREAMING,
        )
        return TaskOutput(ctx=ctx, content=output)
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc), view_type=TASK_VIEW_STREAMING,
        )
        raise


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

propose_peer_urls = NodeTask(
    name=_TASK_NAME,
    description="Propose a public URL whose page lists peer or comparable companies for the target stock.",
    input_type=ProposePeerUrlsInput,
    output_type=ProposePeerUrlsOutput,
    task_fn=_propose_peer_urls_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("propose_peer_urls runs via the Celery stream worker.")
    ),
)

__all__ = [
    "propose_peer_urls",
    "ProposePeerUrlsInput",
    "ProposePeerUrlsOutput",
    "STREAM_PROMPT_BUILDERS",
]
