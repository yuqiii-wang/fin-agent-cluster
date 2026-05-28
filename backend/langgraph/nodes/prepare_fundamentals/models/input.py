"""Input model for prepare_fundamentals node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["PrepareFundamentalsInput"]


class PrepareFundamentalsInput(BaseModel):
    """Typed input for ``prepare_fundamentals``.

    Attributes:
        stock_symbol: Ticker of the stock under analysis (from query_node output).
    """

    stock_symbol: str = Field(
        default="",
        description="Ticker of the stock under analysis; resolved from query_node output.",
    )
