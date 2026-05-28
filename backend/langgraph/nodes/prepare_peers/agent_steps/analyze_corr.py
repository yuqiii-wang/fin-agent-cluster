"""analyze_corr.py — Step 6: LLM-assisted peer correlation analysis."""

from __future__ import annotations

import logging

from backend.langgraph.nodes.prepare_peers.agent_steps.constants import (
    STEP_ANALYZE_CORR,
    _CORR_THRESHOLD,
)
from backend.langgraph.nodes.prepare_peers.agent_steps.state import StepResult, StepRunContext
from backend.langgraph.nodes.prepare_peers.tasks.analyze_peer_corr import (
    AnalyzePeerCorrInput,
    analyze_peer_corr,
)

logger = logging.getLogger(__name__)


async def step_analyze_corr(sctx: StepRunContext) -> None:
    """Step 6: run LLM-assisted peer correlation analysis.

    Calls the ``analyze_peer_corr`` task with the iteration's raw correlation
    data.  Confirmed and rejected peer lists are accumulated into the global
    state for use in subsequent iterations and the final output.

    Skips gracefully when ``sctx.s.iter_peer_raw`` is empty (all peers were
    excluded upstream); sets a failed ``StepResult`` and raises so the
    orchestration task can decide the recovery path.

    Args:
        sctx: Step run context.

    Raises:
        ValueError: When no raw correlation data is available for analysis.
        Exception:  Any error from the ``analyze_peer_corr`` task.
    """
    g, s = sctx.g, sctx.s

    if not s.iter_peer_raw:
        msg = f"[prepare_peers] iter={s.iteration}: no raw corr data for analyze_corr"
        s.step_results[STEP_ANALYZE_CORR] = StepResult(
            step=STEP_ANALYZE_CORR,
            success=False,
            failure_reason="no iter_peer_raw data",
        )
        raise ValueError(msg)

    try:
        apc_out = await sctx.run_task(
            analyze_peer_corr,
            sctx.ctx,
            AnalyzePeerCorrInput(
                target=g.target,
                peer_raw_corr=s.iter_peer_raw,
                corr_threshold=_CORR_THRESHOLD,
                excluded_peers=g.excluded_peers,
            ),
        )
        sctx.results[f"{analyze_peer_corr.name}_iter{s.iteration}"] = apc_out
        apc: "AnalyzePeerCorrOutput" = apc_out.content  # type: ignore[name-defined]

        # Accumulate global state
        for sym, score in apc.peer_corr_scores.items():
            if abs(score) > abs(g.all_peer_corr.get(sym, 0.0)):
                g.all_peer_corr[sym] = score
        g.all_confirmed.extend(apc.confirmed_peers)
        for sym in apc.rejected_peers:
            if sym not in g.excluded_peers:
                g.excluded_peers.append(sym)
        for sym, detail in apc.corr_detail.items():
            if sym not in g.all_corr_detail:
                g.all_corr_detail[sym] = detail

        s.apc_output = apc
        s.step_results[STEP_ANALYZE_CORR] = StepResult(
            step=STEP_ANALYZE_CORR,
            success=True,
            output_summary={
                "confirmed": apc.confirmed_peers,
                "rejected": apc.rejected_peers,
                "top_scores": {
                    sym: round(v, 4)
                    for sym, v in list(apc.peer_corr_scores.items())[:5]
                },
            },
        )
    except Exception as exc:
        s.step_results[STEP_ANALYZE_CORR] = StepResult(
            step=STEP_ANALYZE_CORR,
            success=False,
            failure_reason=str(exc),
        )
        raise


__all__ = ["step_analyze_corr"]
