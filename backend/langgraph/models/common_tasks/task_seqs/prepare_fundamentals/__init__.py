"""prepare_fundamentals -- fan-out fetch fundamentals then aggregate into quant_static_stats."""

from __future__ import annotations

from backend.langgraph.models.common_tasks.task_seqs.prepare_fundamentals.calculate_fundamental_stats import (
    calculate_fundamental_stats,
    CalculateFundamentalStatsInput,
    CalculateFundamentalStatsOutput,
    HANDLERS as _CF_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.prepare_fundamentals.get_fundamentals import (
    get_fundamentals,
    GetFundamentalsInput,
    GetFundamentalsOutput,
    VALID_ENDPOINT_TYPES,
    HANDLERS as _GF_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.prepare_fundamentals.models import (
    PrepareFundamentalsInput,
    PrepareFundamentalsOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.prepare_fundamentals.seq import (
    prepare_fundamentals,
)

HANDLERS: dict = {**_GF_HANDLERS, **_CF_HANDLERS}

__all__ = [
    "prepare_fundamentals",
    "PrepareFundamentalsInput",
    "PrepareFundamentalsOutput",
    "get_fundamentals",
    "GetFundamentalsInput",
    "GetFundamentalsOutput",
    "VALID_ENDPOINT_TYPES",
    "calculate_fundamental_stats",
    "CalculateFundamentalStatsInput",
    "CalculateFundamentalStatsOutput",
    "HANDLERS",
]
