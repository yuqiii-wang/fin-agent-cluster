"""Models for the get_and_calculate_stats task sequence."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculate_stats import CalculateStatsOutput
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import GetStatsOutput


class GetAndCalculateStatsInput(BaseModel):
    """Input for the get_and_calculate_stats task sequence.

    Attributes:
        symbol:                   Equity ticker symbol, e.g. ``'AAPL'``.
        period:                   Aggregation period: ``'1d'``, ``'1w'``, ``'1mo'``, ``'3mo'``, ``'1y'``, ``'2y'``.
        news_limit:               Max news articles passed to ``get_stats``.
        bypass_threshold_minutes: Cache bypass threshold passed to ``get_stats``.
        src_task_id:              Optional ``task_id`` of the upstream task that produced
                                  the injected data (``text_content`` or ``json_input``).
                                  Forwarded to ``get_stats`` for source reference validation.
    """

    symbol: str = Field(description="Equity ticker symbol, e.g. 'AAPL'.")
    period: str = Field(description="Aggregation period: '1d', '1w', '1mo', '3mo', '1y', '2y'.")
    news_limit: int = Field(default=10, ge=1, le=50, description="Max news articles to fetch.")
    bypass_threshold_minutes: int = Field(
        default=60, ge=1, description="Minutes within which downstream stats recomputation is skipped."
    )
    text_content: str | None = Field(
        default=None,
        description=(
            "Optional pre-fetched text content forwarded to get_stats. "
            "When provided, bypasses the external stats API and stores the text in quant_raw."
        ),
    )
    json_input: dict | None = Field(
        default=None,
        description=(
            "Optional structured JSON data forwarded to get_stats (e.g. from run_sandbox). "
            "When provided, bypasses the external stats API and stores the dict in quant_raw."
        ),
    )
    src_task_id: str | None = Field(
        default=None,
        description=(
            "Optional task_id of the upstream task that produced the injected data. "
            "Forwarded to get_stats for validate_src_reference cross-check."
        ),
    )


class GetAndCalculateStatsOutput(BaseModel):
    """Combined output from the get_stats → calculate_stats pipeline.

    Attributes:
        get_stats:        Output from the ``get_stats`` task.
        calculate_stats:  Output from the ``calculate_stats`` task.
    """

    get_stats: GetStatsOutput
    calculate_stats: CalculateStatsOutput


__all__ = ["GetAndCalculateStatsInput", "GetAndCalculateStatsOutput"]
