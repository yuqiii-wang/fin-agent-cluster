"""Input model for prepare_peers node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["AnalyzePeersInput"]


class AnalyzePeersInput(BaseModel):
    """Typed input for ``prepare_peers``.

    Read from ``query_node``'s ``node_executions`` row via the PG replica.

    Attributes:
        stock_name: Company name or stock ticker resolved by query_node.
    """

    stock_name: str = Field(description="Company name or stock ticker.")
