"""calculation_utils — instrument-specific calculation handlers for get_and_calculate_stats."""

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_fundamental_stats import (
    FundamentalsDataItem,
    CalculateFundamentalStatsInput,
    CalculateFundamentalStatsOutput,
    calculate_fundamental_stats_handler,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_option_stats import (
    CalculateOptionStatsInput,
    CalculateOptionStatsOutput,
    calculate_option_stats,
    HANDLERS as _OPT_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_ohlcv_stats import (
    CalculateOhlcvStatsInput,
    CalculateOhlcvStatsOutput,
    calculate_ohlcv_stats_handler,
    PERIOD_TO_GRANULARITY,
)

HANDLERS: dict = {**_OPT_HANDLERS}

__all__ = [
    "FundamentalsDataItem",
    "CalculateFundamentalStatsInput",
    "CalculateFundamentalStatsOutput",
    "calculate_fundamental_stats_handler",
    "CalculateOptionStatsInput",
    "CalculateOptionStatsOutput",
    "calculate_option_stats",
    "CalculateOhlcvStatsInput",
    "CalculateOhlcvStatsOutput",
    "calculate_ohlcv_stats_handler",
    "PERIOD_TO_GRANULARITY",
    "HANDLERS",
]

