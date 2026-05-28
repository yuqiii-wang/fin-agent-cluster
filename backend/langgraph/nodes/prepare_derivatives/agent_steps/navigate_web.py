"""navigate_web.py — Step 2: crawl the derivatives URL and extract structured JSON."""

from __future__ import annotations

import json
import logging

from backend.langgraph.models.common_tasks.task_seqs.navigate_web import (
    NavigateWebInput,
    navigate_web,
)
from backend.langgraph.nodes.prepare_derivatives.agent_steps.state import DerivativesStepContext

logger = logging.getLogger(__name__)

_NAVIGATE_OBJECTIVE = (
    "Find options chain, derivatives contracts, and related market data for the equity symbol {symbol}."
)

_DERIVATIVES_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string", "description": "Equity ticker symbol."},
        "period": {"type": "string", "description": "Data period, e.g. '1y', '3mo'."},
        "records": {
            "type": "array",
            "items": {"type": "object", "description": "Single row of extracted financial data."},
        },
        "metadata": {"type": "object", "description": "Supplementary key-value pairs."},
    },
    "required": ["symbol", "period", "records", "metadata"],
}


async def step_navigate_web(sctx: DerivativesStepContext) -> None:
    """Step 2: crawl the derivatives URL and parse sandbox JSON into ``g.json_input``.

    Fail-open: errors and invalid sandbox output are logged but do not raise.
    ``get_and_calculate_stats`` can proceed without ``json_input`` (``None``
    triggers a plain OHLCV-only fetch).

    Args:
        sctx: Step context.
    """
    g = sctx.g

    try:
        nav_output = await navigate_web.run(
            sctx.run_task,
            sctx.ctx,
            NavigateWebInput(
                url=g.web_knowledge_url,
                objective=_NAVIGATE_OBJECTIVE.format(symbol=g.symbol),
                output_json_schema=_DERIVATIVES_OUTPUT_SCHEMA,
            ),
        )
        if nav_output.run_sandbox.exit_code == 0 and nav_output.run_sandbox.stdout:
            try:
                g.json_input = json.loads(nav_output.run_sandbox.stdout)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.error(
                    "[PD-003b] sandbox stdout not valid JSON symbol=%r: %s", g.symbol, exc
                )
        else:
            logger.error(
                "[PD-003c] sandbox failed exit_code=%d symbol=%r stderr=%r",
                nav_output.run_sandbox.exit_code,
                g.symbol,
                nav_output.run_sandbox.stderr,
            )
    except Exception as exc:
        logger.error(
            "[PD-003] navigate_web failed symbol=%r url=%r: %s",
            g.symbol,
            g.web_knowledge_url,
            exc,
        )


__all__ = ["step_navigate_web"]
