"""Models for the get_and_calculate_stats task sequence."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import (
    GetStatsOutput,
)


class CalculateStatsBaseOutput(BaseModel):
    """Base model for calculate_stats output, containing common fields."""
    rows_upserted: int
    symbol: str
    source: str
    stats_views: list[str]


class GetAndCalculateStatsInput(BaseModel):
    """Input for the get_and_calculate_stats task sequence.

    Attributes:
        symbol:           Instrument ticker, e.g. ``'AAPL'``.
        period:           Aggregation period, e.g. ``'1d'``, ``'1mo'``.
        pipeline:         Target pipeline for ``calculate_stats``; used to route to
                          the appropriate handler.  Defaults to ``'ohlcv'``. Also
                          accepted: ``'options'``, ``'futures'``.
        text_content:     Free-form text to inject instead of fetching.
        json_input:       Injected OHLCV matrix / StatsRecord dict from a previous task.
        maturity_horizon: Optional horizon for time-bounded products
                          (options, futures, bonds, repo, ...).  Controls how
                          far out to pull maturities.  Accepts a
                          :class:`~backend.quant.stats.constants.OPTIONS_PERIODS`
                          member, one of its ``display_name`` strings
                          (``'next'``, ``'one week'``, ``'one month'``,
                          ``'one quarter'``, ``'half year'``, ``'one year'``),
                          or a raw number of seconds.  ``None`` →
                          ``OPTIONS_PERIODS.ONE_YEAR``.
        src_task_id:      Optional source task id for provenance.
    """

    symbol: str = Field(description="Instrument ticker, e.g. 'AAPL'.")
    period: str = Field(default="1mo", description="Aggregation period, e.g. '1d', '1mo'.")
    pipeline: str = Field(default="ohlcv", description="Target pipeline for calculate_stats routing.")
    text_content: str | None = Field(default=None, description="Free-form text to inject.")
    json_input: dict | None = Field(default=None, description="Injected OHLCV matrix or StatsRecord dict.")
    maturity_horizon: Any = Field(
        default=None,
        description=(
            "Horizon for time-bounded products (options, futures, bonds, "
            "repo, ...). Accepts a OPTIONS_PERIODS member, its "
            "display_name string, or a raw number of seconds. None → "
            "OPTIONS_PERIODS.ONE_YEAR."
        ),
    )
    src_task_id: str | None = Field(default=None, description="Source task id for provenance.")


from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_ohlcv_stats import CalculateOhlcvStatsOutput
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_option_stats import CalculateOptionStatsOutput
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_futures_stats import CalculateFuturesStatsOutput

class GetAndCalculateStatsOutput(BaseModel):
    """Combined output from the get_stats -> calculate_stats pipeline.

    Attributes:
        get_stats:       Output from the ``get_stats`` task (resolved StatsRecord).
        calculate_stats: Output from the ``calculate_stats`` task (upserted bars).
    """

    get_stats: GetStatsOutput
    calculate_stats: CalculateOhlcvStatsOutput | CalculateOptionStatsOutput | CalculateFuturesStatsOutput


__all__ = ["GetAndCalculateStatsInput", "GetAndCalculateStatsOutput", "CalculateStatsBaseOutput"]
