"""get_stats.py — Step 3: fetch OHLCV bars and compute technical indicators."""

from __future__ import annotations

import logging

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats import (
    GetAndCalculateStatsInput,
    get_and_calculate_stats,
)
from backend.langgraph.nodes.prepare_derivatives.agent_steps.state import DerivativesStepContext

logger = logging.getLogger(__name__)


async def step_get_stats(sctx: DerivativesStepContext) -> None:
    """Step 3: fetch OHLCV bars and compute technical indicators.

    Passes ``g.json_input`` (may be ``None``) to ``get_and_calculate_stats``
    so derivatives data from the sandbox is stored alongside OHLCV rows when
    available.

    Fail-open: errors are logged but do not raise so the node output is still
    produced (albeit without computed stats).

    Args:
        sctx: Step context.
    """
    g = sctx.g

    try:
        await get_and_calculate_stats.run(
            sctx.run_task,
            sctx.ctx,
            GetAndCalculateStatsInput(
                symbol=g.symbol,
                period=sctx.stats_period,
                json_input=g.json_input,
            ),
        )
    except Exception as exc:
        logger.error("[PD-004] get_and_calculate_stats failed symbol=%r: %s", g.symbol, exc)


__all__ = ["step_get_stats"]
