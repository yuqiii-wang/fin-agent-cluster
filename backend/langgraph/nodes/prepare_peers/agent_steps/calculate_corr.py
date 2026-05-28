"""calculate_corr.py — Step 5: compute Pearson correlation for each peer vs. the target."""

from __future__ import annotations

import asyncio
import logging

from backend.langgraph.models.common_tasks import CalculateCorrInput, calculate_corr
from backend.langgraph.models.models import TaskOutput
from backend.langgraph.nodes.prepare_peers.agent_steps.constants import (
    STEP_CALCULATE_CORR,
    _CORR_WINDOW_BARS,
    _VALIDATION_GRANULARITY,
)
from backend.langgraph.nodes.prepare_peers.agent_steps.state import StepResult, StepRunContext
from backend.langgraph.nodes.prepare_peers.tasks.analyze_peer_corr import PeerRawCorrData

logger = logging.getLogger(__name__)


async def step_calculate_corr(sctx: StepRunContext) -> None:
    """Step 5: compute Pearson correlation for each valid peer vs. the target.

    Checks ``sctx.s.input_overrides`` for:

    - ``"peers"``: compute correlation only for this peer subset, overriding
      ``s.valid_peers`` (useful for targeted retries after partial failures).

    Runs all peers in parallel via ``asyncio.gather``. Peers that fail are added
    to ``sctx.g.excluded_peers``. Successful results are stored in
    ``sctx.s.iter_peer_raw`` and written to the shared ``sctx.results`` dict.

    Args:
        sctx: Step run context.

    Raises:
        ValueError: When no peers are available, or all peers fail correlation.
    """
    g, s = sctx.g, sctx.s

    override_peers: list[str] = s.input_overrides.get("peers", [])
    corr_candidates = override_peers if override_peers else s.valid_peers

    if not corr_candidates:
        s.step_results[STEP_CALCULATE_CORR] = StepResult(
            step=STEP_CALCULATE_CORR,
            success=False,
            failure_reason="no peers available for corr calculation",
        )
        raise ValueError(
            f"[prepare_peers] iter={s.iteration}: no peers provided to calculate_corr"
        )

    async def _calc(sym: str) -> tuple[str, TaskOutput]:
        """Run calculate_corr for *sym* vs *target*; returns (sym, task output)."""
        corr_out = await sctx.run_task(
            calculate_corr,
            sctx.ctx,
            CalculateCorrInput(
                symbols=[g.target, sym],
                granularity=_VALIDATION_GRANULARITY,
                window_bars=_CORR_WINDOW_BARS,
            ),
        )
        return sym, corr_out

    corr_gather = await asyncio.gather(
        *[_calc(sym) for sym in corr_candidates],
        return_exceptions=True,
    )

    for sym, res in zip(corr_candidates, corr_gather):
        if isinstance(res, Exception):
            g.excluded_peers.append(sym)
            logger.error(
                "[prepare_peers] iter=%d corr failed for %s: %s", s.iteration, sym, res,
            )
        else:
            sym2, corr_out = res
            s.iter_peer_raw[sym2] = PeerRawCorrData(
                matrix=corr_out.content.matrix,
                indicator_matrices=corr_out.content.indicator_matrices,
            )
            sctx.results[f"{calculate_corr.name}_{sym2}_iter{s.iteration}"] = corr_out

    if not s.iter_peer_raw:
        s.step_results[STEP_CALCULATE_CORR] = StepResult(
            step=STEP_CALCULATE_CORR,
            success=False,
            failure_reason="all peers failed corr calculation",
        )
        raise ValueError(f"[AP-004] iter={s.iteration}: all peers failed corr calculation")

    s.step_results[STEP_CALCULATE_CORR] = StepResult(
        step=STEP_CALCULATE_CORR,
        success=True,
        output_summary={"peers_with_corr": list(s.iter_peer_raw.keys())},
    )


__all__ = ["step_calculate_corr"]
