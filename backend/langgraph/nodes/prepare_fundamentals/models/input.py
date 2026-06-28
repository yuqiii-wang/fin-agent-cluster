"""Input model for prepare_fundamentals node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["PrepareFundamentalsInput"]


class PrepareFundamentalsInput(BaseModel):
    """Typed input for ``prepare_fundamentals``.

    Attributes:
        stock_symbol: Equity ticker resolved from ``query_node`` output.
        endpoint_types: Fundamental endpoint labels to fetch
                        (e.g. ``income_statement`` / ``balance_sheet`` /
                        ``cash_flow`` / ``key_metrics``).
    """

    stock_symbol: str = Field(default="", description="Equity ticker, e.g. 'AAPL'.")
    endpoint_types: list[str] = Field(
        default_factory=list,
        description="Fundamental endpoint labels to fetch.",
    )
