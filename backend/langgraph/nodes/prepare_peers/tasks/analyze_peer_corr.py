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


class PeerRawCorrData(BaseModel):
    """Raw calculate_corr output for a single peer symbol.

    Attributes:
        matrix:             Pearson matrix from calculate_corr: {symbol → {symbol → r}}.
        indicator_matrices: Per-indicator Pearson matrices: {indicator → {symbol → {symbol → r}}}.
    """

    matrix: dict[str, dict[str, float]]
    indicator_matrices: dict[str, dict[str, dict[str, float]]] = Field(default_factory=dict)


class AnalyzePeerCorrInput(BaseModel):
    """Input for the analyze_peer_corr task.

    Attributes:
        target:        Target stock ticker symbol.
        peer_raw_corr: Raw calculate_corr output per peer: {peer_sym → PeerRawCorrData}.
        corr_threshold: Minimum abs(r) to accept a peer (0.0–1.0).
    """

    target: str = Field(description="Target stock ticker symbol.")
    peer_raw_corr: dict[str, PeerRawCorrData] = Field(
        description="Peer ticker → raw calculate_corr output (matrix + indicator_matrices).",
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
        confirmed_peers:   Tickers with abs(r) ≥ corr_threshold, sorted descending by abs(r).
        rejected_peers:    Tickers with abs(r) < corr_threshold.
        peer_corr_scores:  Computed abs(r) score per peer sym.
        peer_corr_details: Detailed corr breakdown (close, sma_20, sma_50, ema_12, ema_26) per peer.
    """

    confirmed_peers: list[str] = Field(
        default_factory=list,
        description="Peers meeting the correlation threshold, sorted descending by abs(r).",
    )
    rejected_peers: list[str] = Field(
        default_factory=list,
        description="Peers that did not meet the correlation threshold.",
    )
    peer_corr_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Computed abs(r) score per peer sym.",
    )
    peer_corr_details: dict[str, dict] = Field(
        default_factory=dict,
        description="Detailed corr breakdown (close_corr, sma_20_corr, sma_50_corr, ema_12_corr, ema_26_corr) per peer.",
    )


# ---------------------------------------------------------------------------
# LangGraph layer — @task (pure computation, no Celery delegation)
# ---------------------------------------------------------------------------


@task
async def _analyze_peer_corr_task(
    task_input: TaskInput[AnalyzePeerCorrInput],
) -> TaskOutput[AnalyzePeerCorrOutput]:
    """LangGraph @task: compute abs(Pearson r) per peer then filter by threshold.

    For each peer in ``peer_raw_corr`` the best abs(r) is derived from
    indicator_matrices (sma/ema series) first, falling back to the close-price
    matrix.  Peers at or above corr_threshold are confirmed; the rest rejected.
    Confirmed peers are returned sorted by descending abs(r).

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
        target = inp.target
        threshold = inp.corr_threshold

        peer_corr_scores: dict[str, float] = {}
        peer_corr_details: dict[str, dict] = {}

        for sym, raw in inp.peer_raw_corr.items():
            indicator_corr = max(
                (
                    abs(mat.get(target, {}).get(sym, 0.0))
                    for mat in raw.indicator_matrices.values()
                ),
                default=0.0,
            )
            corr_val = indicator_corr or abs(raw.matrix.get(target, {}).get(sym, 0.0))
            peer_corr_scores[sym] = corr_val
            peer_corr_details[sym] = {
                "close_corr": raw.matrix.get(target, {}).get(sym),
                "sma_20_corr": raw.indicator_matrices.get("sma_20", {}).get(target, {}).get(sym),
                "sma_50_corr": raw.indicator_matrices.get("sma_50", {}).get(target, {}).get(sym),
                "ema_12_corr": raw.indicator_matrices.get("ema_12", {}).get(target, {}).get(sym),
                "ema_26_corr": raw.indicator_matrices.get("ema_26", {}).get(target, {}).get(sym),
            }

        confirmed = sorted(
            (sym for sym, r in peer_corr_scores.items() if r >= threshold),
            key=lambda s: peer_corr_scores[s],
            reverse=True,
        )
        rejected = [sym for sym, r in peer_corr_scores.items() if r < threshold]

        output = AnalyzePeerCorrOutput(
            confirmed_peers=confirmed,
            rejected_peers=rejected,
            peer_corr_scores=peer_corr_scores,
            peer_corr_details=peer_corr_details,
        )

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

__all__ = ["analyze_peer_corr", "AnalyzePeerCorrInput", "AnalyzePeerCorrOutput", "PeerRawCorrData"]
