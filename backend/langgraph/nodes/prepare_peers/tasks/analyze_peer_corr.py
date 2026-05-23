"""analyze_peer_corr — computation task: assess per-peer correlations and conclude confirmed peers.

For each proposed peer, evaluates whether its abs(Pearson r) with the target
stock meets the acceptance threshold.  Returns two lists: confirmed peers
(corr ≥ threshold) and rejected peers (corr < threshold).

This is a pure computation task — no LLM or external I/O.  Lifecycle tracking
(create_task / complete_task) provides UI visibility and audit trail.

Public exports
--------------
``analyze_peer_corr``    — ``NodeTask`` instance used by ``AnalyzePeersNode``.
``AnalyzePeerCorrInput``  — Input model.
``AnalyzePeerCorrOutput`` — Output model.
"""

from __future__ import annotations

import logging

from langgraph.func import task
from pydantic import BaseModel, Field

from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "analyze_peer_corr"


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class AnalyzePeerCorrInput(BaseModel):
    """Input for the analyze_peer_corr task.

    Attributes:
        target:            Target stock ticker symbol.
        peer_correlations: Mapping of peer ticker → abs(Pearson r with target).
        corr_threshold:    Minimum abs(r) to accept a peer (0.0–1.0).
    """

    target: str = Field(description="Target stock ticker symbol.")
    peer_correlations: dict[str, float] = Field(
        description="Peer ticker → abs(Pearson r with target).",
    )
    corr_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum abs(r) to accept a peer as corr-validated.",
    )


class AnalyzePeerCorrOutput(BaseModel):
    """Output from the analyze_peer_corr task.

    Attributes:
        confirmed_peers: Tickers with abs(r) ≥ corr_threshold, sorted descending by abs(r).
        rejected_peers:  Tickers with abs(r) < corr_threshold.
    """

    confirmed_peers: list[str] = Field(
        default_factory=list,
        description="Peers meeting the correlation threshold, sorted descending by abs(r).",
    )
    rejected_peers: list[str] = Field(
        default_factory=list,
        description="Peers that did not meet the correlation threshold.",
    )


# ---------------------------------------------------------------------------
# LangGraph layer — @task (pure computation, no Celery delegation)
# ---------------------------------------------------------------------------


@task
async def _analyze_peer_corr_task(
    task_input: TaskInput[AnalyzePeerCorrInput],
) -> TaskOutput[AnalyzePeerCorrOutput]:
    """LangGraph @task: filter peer correlations by threshold and conclude confirmed peers.

    Peers with abs(Pearson r) ≥ corr_threshold are confirmed; the rest are
    rejected.  Confirmed peers are returned sorted by descending abs(r).

    Args:
        task_input: Typed envelope with TaskContext and AnalyzePeerCorrInput.

    Returns:
        TaskOutput wrapping AnalyzePeerCorrOutput.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Stats",
    )
    try:
        inp = task_input.content
        threshold = inp.corr_threshold

        confirmed = sorted(
            (sym for sym, r in inp.peer_correlations.items() if r >= threshold),
            key=lambda s: inp.peer_correlations[s],
            reverse=True,
        )
        rejected = [sym for sym, r in inp.peer_correlations.items() if r < threshold]

        output = AnalyzePeerCorrOutput(confirmed_peers=confirmed, rejected_peers=rejected)

        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=output.model_dump(),
            view_type="Stats",
        )
        return TaskOutput(ctx=ctx, content=output)

    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc), view_type="Stats",
        )
        raise


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

analyze_peer_corr = NodeTask(
    name=_TASK_NAME,
    description=(
        "Assess per-peer abs(Pearson r) scores against the acceptance threshold and "
        "conclude which tickers are corr-validated peers of the target stock."
    ),
    input_type=AnalyzePeerCorrInput,
    output_type=AnalyzePeerCorrOutput,
    task_fn=_analyze_peer_corr_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("analyze_peer_corr is a pure-computation task; no Celery handler.")
    ),
)

__all__ = ["analyze_peer_corr", "AnalyzePeerCorrInput", "AnalyzePeerCorrOutput"]
