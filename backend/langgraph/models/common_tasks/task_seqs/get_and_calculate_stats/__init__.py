"""get_and_calculate_stats — fetch OHLCV stats and compute indicators as a TaskSeq pipeline."""

from __future__ import annotations

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculate_stats import (
    calculate_stats,
    CalculateStatsInput,
    CalculateStatsOutput,
    HANDLERS as _CS_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import (
    get_stats,
    GetStatsInput,
    GetStatsOutput,
    HANDLERS as _GS_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.models import (
    GetAndCalculateStatsInput,
    GetAndCalculateStatsOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.seq import (
    get_and_calculate_stats,
)

HANDLERS: dict = {**_GS_HANDLERS, **_CS_HANDLERS}

__all__ = [
    "get_and_calculate_stats",
    "GetAndCalculateStatsInput",
    "GetAndCalculateStatsOutput",
    "get_stats",
    "GetStatsInput",
    "GetStatsOutput",
    "calculate_stats",
    "CalculateStatsInput",
    "CalculateStatsOutput",
    "HANDLERS",
]
