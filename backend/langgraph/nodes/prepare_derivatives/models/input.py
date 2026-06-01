"""Input model for prepare_derivatives node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["PrepareDerivativesInput"]


class PrepareDerivativesInput(BaseModel):
    """Typed input for ``prepare_derivatives``.

    Attributes:
        stock_symbol: Ticker of the stock under analysis (from query_node output).
        stats_period: Aggregation period passed to ``get_and_calculate_stats``.
    """

    stock_symbol: str = Field(
        default="",
        description="Ticker of the stock under analysis; resolved from query_node output.",
    )
    stats_period: str = Field(
        default="1y",
        description="Aggregation period for get_and_calculate_stats: '1d', '1w', '1mo', '1y', '2y'.",
    )
