"""Output model for prepare_fundamentals node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["PrepareFundamentalsOutput"]


class PrepareFundamentalsOutput(BaseModel):
    """Typed output for ``prepare_fundamentals``.

    Persisted to ``fin_agents.node_executions`` for downstream nodes.

    Attributes:
        symbol: Queried equity ticker, e.g. ``'AAPL'``.
    """

    symbol: str = Field(default="", description="Queried equity ticker.")
