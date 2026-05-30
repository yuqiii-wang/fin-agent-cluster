"""Models for the prepare_fundamentals task sequence."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_fundamental_stats import (
    CalculateFundamentalStatsOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.prepare_fundamentals.get_fundamentals import (
    GetFundamentalsOutput,
)


class PrepareFundamentalsInput(BaseModel):
    """Input for the prepare_fundamentals task sequence.

    Attributes:
        symbol:         Equity ticker symbol, e.g. ``'AAPL'``.
        endpoint_types: Ordered list of fundamental endpoint types to fetch in parallel.
                        Defaults to all four standard endpoints.
    """

    symbol: str = Field(description="Equity ticker symbol, e.g. 'AAPL'.")
    endpoint_types: list[str] = Field(
        default_factory=lambda: [
            "income_statement",
            "balance_sheet",
            "cash_flow",
            "key_metrics",
        ],
        description=(
            "Fundamental endpoint types to fetch. Each maps to a separate get_fundamentals "
            "invocation that runs in parallel."
        ),
    )


class PrepareFundamentalsOutput(BaseModel):
    """Combined output from the prepare_fundamentals pipeline.

    Attributes:
        get_fundamentals:            List of outputs from each parallel get_fundamentals call,
                                     one per requested endpoint type.
        calculate_fundamental_stats: Output from the single calculate_fundamental_stats call.
    """

    get_fundamentals: list[GetFundamentalsOutput]
    calculate_fundamental_stats: CalculateFundamentalStatsOutput


__all__ = ["PrepareFundamentalsInput", "PrepareFundamentalsOutput"]
