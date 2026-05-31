"""get_stats.py — Step 2: fetch OHLCV bars and compute technical indicators."""

from __future__ import annotations

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats import (
    GetAndCalculateStatsInput,
    get_and_calculate_stats,
)
from backend.langgraph.nodes.prepare_derivatives.models.state import DerivativesStepContext


async def step_get_stats(sctx: DerivativesStepContext) -> None:
    """Step 4: fetch OHLCV bars and compute technical indicators.

    Passes ``g.json_input`` (may be ``None``) to ``get_and_calculate_stats``
    so derivatives data from the sandbox is stored alongside OHLCV rows when
    available.  When ``g.json_input`` is ``None`` but ``g.load_md_output`` is
    present, falls back to passing the ``html_to_markdown`` Markdown text as
    ``text_content`` so the web content is at least stored in ``input_raw``.

    ``g.load_md_output`` markdown text as ``text_content`` so the web content
    is at least stored in ``input_raw``.

    Raises on failure so the agent loop can trigger orchestration-driven
    recovery of an earlier step.

    Args:
        sctx: Step context.

    Raises:
        Exception: Propagated from ``get_and_calculate_stats``.
    """
    g = sctx.g

    # Determine injection inputs.
    json_input = g.json_input
    text_content: str | None = None

    if json_input is None and g.load_md_output is not None:
        # Sandbox extraction failed but markdown is available — store it in input_raw.
        text_content = g.load_md_output.html_to_markdown.markdown

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


__all__ = ["step_get_stats"]
