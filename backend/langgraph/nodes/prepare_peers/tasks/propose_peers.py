"""propose_peers — LLM streaming task that proposes peer companies for a target stock.

The LLM receives the stock name and returns a JSON object with a list of peer
ticker symbols and brief reasoning.

Execution layers
----------------
LangGraph layer (``_propose_peers_task`` decorated with ``@task``):
    Creates a streaming task record, delegates to the Celery stream worker via
    ``delegate_stream``, parses the JSON answer, and returns a ``TaskOutput``.

Celery layer (``stream_task.run_stream``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to ``_build_propose_peers_prompt``.
    The LLM returns a JSON object with ``peers`` (list of ticker symbols) and
    ``reasoning`` (brief rationale).

Public exports
--------------
``propose_peers``             — ``NodeTask`` instance used by ``PreparePeersNode``.
``ProposePeersInput``         — Pydantic input model.
``ProposePeersOutput``        — Pydantic output model.
``STREAM_PROMPT_BUILDERS``    — dict slice for registration in ``stream_task.py``.
"""

from __future__ import annotations

import logging

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate

from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_stream
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.models.view_types import TASK_VIEW_STREAMING

logger = logging.getLogger(__name__)

_TASK_NAME = "propose_peers"

# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------

class ProposePeersInput(BaseModel):
    """Input for the propose_peers task.

    Attributes:
        stock_name: Company name or stock ticker to find peers for.
    """

    stock_name: str = Field(description="Company name or stock ticker.")

class ProposePeersOutput(BaseModel):
    """Output from the propose_peers task.

    Attributes:
        peers:     List of peer ticker symbols proposed by the LLM.
        reasoning: LLM's brief rationale for the peer selection.
    """

    peers: list[str] = Field(
        default_factory=list,
        description="Peer ticker symbols for the target stock.",
    )
    reasoning: str = Field(
        default="",
        description="Why these companies are considered peers.",
    )

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_PROPOSE_PEERS_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a financial research assistant. "
     "Given a stock ticker or company name, identify 3–6 peer or comparable companies "
     "that trade on the same or a closely related exchange.\n\n"
     "Selection criteria:\n"
     "- Same primary industry or sub-sector\n"
     "- Similar market capitalisation range\n"
     "- Listed on the same regional exchange or a major global exchange\n"
     "- Companies frequently cited as competitors or comparables in analyst reports\n\n"
     "Respond ONLY with valid JSON — no preamble, no explanation outside the JSON:\n"
     '{{ "peers": ["TICKER1", "TICKER2", ...], "reasoning": "<1-3 sentences>" }}'),
    ("human", "Propose peer companies for: {stock_name}"),
])

# ---------------------------------------------------------------------------
# Streaming prompt builder
# ---------------------------------------------------------------------------

def _build_propose_peers_prompt(payload: dict) -> list[BaseMessage]:
    """Build the LangChain message list for propose_peers.

    Args:
        payload: Serialised :class:`ProposePeersInput` dict.

    Returns:
        LangChain message list (SystemMessage + HumanMessage).
    """
    inp = ProposePeersInput.model_validate(payload)
    return _PROPOSE_PEERS_PROMPT.format_messages(stock_name=inp.stock_name)

STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_propose_peers_prompt}

# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------

async def _propose_peers_task(
    task_input: TaskInput[ProposePeersInput],
) -> TaskOutput[ProposePeersOutput]:
    """LangGraph @task: propose peer companies via LLM streaming.

    Delegates to the Celery stream worker, parses the JSON answer, and
    returns a typed ``TaskOutput``.

    Args:
        task_input: Typed envelope with TaskContext and ProposePeersInput.

    Returns:
        TaskOutput wrapping ProposePeersOutput.
    """
    ctx = task_input.ctx
    inp = task_input.content
    payload = inp.model_dump()

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
        payload, view_type=TASK_VIEW_STREAMING,
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
        raw_peers = answer_dict.get("peers", [])
        peers = [str(p).strip().upper() for p in raw_peers if str(p).strip()]
        output = ProposePeersOutput(
            peers=peers,
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

propose_peers = NodeTask(
    name=_TASK_NAME,
    description="Propose 3–6 peer or comparable companies for the target stock using LLM.",
    input_type=ProposePeersInput,
    output_type=ProposePeersOutput,
    task_fn=_propose_peers_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("propose_peers runs via the Celery stream worker.")
    ),
)

__all__ = [
    "propose_peers",
    "ProposePeersInput",
    "ProposePeersOutput",
    "STREAM_PROMPT_BUILDERS",
]
