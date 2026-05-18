"""Output model for query_node.

Written to node_executions after the node completes.
Downstream nodes read this output via ``read_node_output(node_id)``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["QueryNodeOutput"]


class QueryNodeOutput(BaseModel):
    """Typed output for ``query_node``.

    Persisted to ``fin_agents.node_executions`` for the ``query_node`` row.

    Attributes:
        intent: Classified query intent (e.g. ``"market_analysis"``).
        symbols: Equity ticker symbols extracted from the query.
        filters: Optional filter key/values (e.g. date range, interval).
    """

    intent: str = Field(description="Classified query intent.")
    symbols: list[str] = Field(default_factory=list, description="Extracted equity tickers.")
    filters: dict[str, Any] = Field(default_factory=dict, description="Optional query filters.")

