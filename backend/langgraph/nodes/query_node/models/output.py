"""Output model for query_node.

Written to ``state["query_analysis"]`` after the node completes.
The research_subgraph reads this slice as its node input.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["QueryNodeOutput"]


class QueryNodeOutput(BaseModel):
    """Typed output for ``query_node``.

    Stored as the ``query_analysis`` JSONB slice in ``GraphState`` and
    persisted to ``fin_agents.nodes.output`` for the ``query_node`` row.

    Attributes:
        intent: Classified query intent (e.g. ``"market_analysis"``).
        symbols: Equity ticker symbols extracted from the query.
        filters: Optional filter key/values (e.g. date range, interval).
        query_time: UTC ISO 8601 timestamp captured when the query entered the graph.
    """

    intent: str = Field(description="Classified query intent.")
    symbols: list[str] = Field(default_factory=list, description="Extracted equity tickers.")
    filters: dict[str, Any] = Field(default_factory=dict, description="Optional query filters.")
    query_time: str = Field(default="", description="UTC ISO 8601 timestamp when the query entered the graph.")
