"""get_stats.py — Step 2: fetch OHLCV bars and compute technical indicators."""

from __future__ import annotations

import logging

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats import (
    GetAndCalculateStatsInput,
    get_and_calculate_stats,
)
from backend.langgraph.nodes.prepare_derivatives.models.state import DerivativesStepContext

logger = logging.getLogger(__name__)


async def step_get_stats(sctx: DerivativesStepContext) -> None:
    """Step 4: fetch OHLCV bars and compute technical indicators.

    Passes ``g.json_input`` (may be ``None``) to ``get_and_calculate_stats``
    so derivatives data from the sandbox is stored alongside OHLCV rows when
    available.  When ``g.json_input`` is ``None`` but ``g.load_md_output`` is
    present, falls back to passing the ``html_to_markdown`` Markdown text as
    ``text_content`` so the web content is at least stored in ``quant_raw``.

    ``g.load_md_output`` markdown text as ``text_content`` so the web content
    is at least stored in ``quant_raw``.

    Fail-open: errors are logged but do not raise so the node output is still
    produced (albeit without computed stats).

    Args:
        sctx: Step context.
    """
    g = sctx.g

    # Determine injection inputs.
    json_input = g.json_input
    text_content: str | None = None

    if json_input is None and g.load_md_output is not None:
        # Sandbox extraction failed but markdown is available — store it in quant_raw.
        text_content = g.load_md_output.html_to_markdown.markdown

    try:
        await get_and_calculate_stats.run(
            sctx.run_task,
            sctx.ctx,
            GetAndCalculateStatsInput(
                symbol=g.symbol,
                period=sctx.stats_period,
                json_input=json_input,
                text_content=text_content,
                src_task_id=None,
            ),
        )
    except Exception as exc:
        logger.error("[PD-004] get_and_calculate_stats failed symbol=%r: %s", g.symbol, exc)


__all__ = ["step_get_stats"]
