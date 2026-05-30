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

logger = logging.getLogger(__name__)


async def step_calculate_options(sctx: DerivativesStepContext) -> None:
    """Step 5: aggregate the extracted options chain into the stats tables.

    Skips immediately when ``sctx.g.json_input`` is absent, is not an options
    payload, or carries no call/put contracts.

    Fail-open: errors are logged but do not raise so the node output is still
    produced.

    Args:
        sctx: Step context.
    """
    g = sctx.g
    json_input = g.json_input

    if not json_input or json_input.get("data_type") != "options":
        logger.error(
            "[PD-005] json_input missing or not options, skipping calculate_options symbol=%r",
            g.symbol,
        )
        return

    options = json_input.get("options") or []
    if not options:
        logger.error(
            "[PD-005] no contracts to aggregate symbol=%r", g.symbol
        )
        return

    try:
        await sctx.run_task(
            calculate_option_stats,
            sctx.ctx,
            CalculateOptionStatsInput(
                symbol=g.symbol,
                source="web_content",
                options=options,
            ),
        )
    except Exception as exc:
        logger.error(
            "[PD-005] calculate_option_stats failed symbol=%r: %s", g.symbol, exc
        )


__all__ = ["step_calculate_options"]
