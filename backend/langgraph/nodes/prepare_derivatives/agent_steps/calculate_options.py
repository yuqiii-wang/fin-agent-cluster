"""calculate_options.py — Step 5: aggregate the options chain into stats tables.

Reads the structured options JSON produced by ``step_study_web_content``
(``sctx.g.json_input``) and runs the ``calculate_option_stats`` NodeTask, which
upserts each call/put contract into ``fin_markets.quant_options_stats`` and one
aggregate row per expiry into ``fin_markets.quant_derivative_stats``.
"""

from __future__ import annotations

import logging

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_option_stats import (
    CalculateOptionStatsInput,
    calculate_option_stats,
)
from backend.langgraph.nodes.prepare_derivatives.models.state import DerivativesStepContext
from backend.quant.field_name_conversion import normalize_keys

logger = logging.getLogger(__name__)


async def step_calculate_options(sctx: DerivativesStepContext) -> None:
    """Step 5: aggregate the extracted options chain into the stats tables.

    Skips immediately when ``sctx.g.json_input`` is absent, is not an options
    payload, or carries no call/put contracts.

    Raises on ``calculate_option_stats`` failure so the agent loop can trigger
    orchestration-driven recovery of an earlier step.

    Args:
        sctx: Step context.

    Raises:
        Exception: Propagated from ``calculate_option_stats``.
    """
    g = sctx.g
    json_input = g.json_input

    if not json_input or json_input.get("data_type") != "options":
        logger.error(
            "[PD-005] json_input missing or not options, skipping calculate_options symbol=%r",
            g.symbol,
        )
        return

    calls_raw = json_input.get("calls") or []
    puts_raw = json_input.get("puts") or []
    calls_norm = [{**normalize_keys(c), "options_type": "call"} for c in calls_raw if isinstance(c, dict)]
    puts_norm = [{**normalize_keys(p), "options_type": "put"} for p in puts_raw if isinstance(p, dict)]
    options = calls_norm + puts_norm
    if not options:
        logger.error(
            "[PD-005] no contracts to aggregate symbol=%r", g.symbol
        )
        return

    await sctx.run_task(
        calculate_option_stats,
        sctx.ctx,
        CalculateOptionStatsInput(
            symbol=g.symbol,
            source="web_content",
            options=options,
        ),
    )


__all__ = ["step_calculate_options"]
