"""Models for the get_and_calculate_stats task sequence."""

from __future__ import annotations

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
        symbol:       Instrument ticker, e.g. ``'AAPL'``.
        period:       Aggregation period, e.g. ``'1d'``, ``'1mo'``.
        text_content: Free-form text to inject instead of fetching.
        json_input:   Injected OHLCV matrix / StatsRecord dict from a previous task.
        src_task_id:  Optional source task id for provenance.
    """

    symbol: str = Field(description="Instrument ticker, e.g. 'AAPL'.")
    period: str = Field(default="1mo", description="Aggregation period, e.g. '1d', '1mo'.")
    text_content: str | None = Field(default=None, description="Free-form text to inject.")
    json_input: dict | None = Field(default=None, description="Injected OHLCV matrix or StatsRecord dict.")
    src_task_id: str | None = Field(default=None, description="Source task id for provenance.")


from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_ohlcv_stats import CalculateOhlcvStatsOutput
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_option_stats import CalculateOptionStatsOutput

class GetAndCalculateStatsOutput(BaseModel):
    """Combined output from the get_stats → calculate_stats pipeline.

    Attributes:
        get_stats:       Output from the ``get_stats`` task (resolved StatsRecord).
        calculate_stats: Output from the ``calculate_stats`` task (upserted bars).
    """

    get_stats: GetStatsOutput
    calculate_stats: CalculateOhlcvStatsOutput | CalculateOptionStatsOutput


__all__ = ["GetAndCalculateStatsInput", "GetAndCalculateStatsOutput", "CalculateStatsBaseOutput"]
