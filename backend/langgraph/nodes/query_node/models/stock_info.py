"""Intermediate model shared by the parallel stock-info tasks."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["StockInfoInput"]


class StockInfoInput(BaseModel):
    """Input shared by ``get_stock_region`` and ``get_stock_industry_peers``.

    Attributes:
        stock_name: Company name or ticker extracted by the ``analyze_query`` task.
    """

    stock_name: str = Field(description="Company name or stock ticker.")
