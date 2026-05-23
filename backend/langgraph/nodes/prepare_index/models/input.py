"""Input model for prepare_index node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["AnalyzeIndexInput"]


class AnalyzeIndexInput(BaseModel):
    """Typed input for ``prepare_index``.

    Attributes:
        period:       Stats aggregation period passed to ``get_and_calculate_stats``
                      for all instruments.
        stock_symbol: Ticker of the stock under analysis (from query_node output).
                      Passed to ``propose_index`` to check whether the stock's home
                      index is already covered by the default set.
    """

    period: str = Field(default="2y", description="Stats aggregation period, e.g. '2y'.")
    stock_symbol: str = Field(
        default="",
        description="Ticker of the stock under analysis; used for index-coverage check.",
    )
