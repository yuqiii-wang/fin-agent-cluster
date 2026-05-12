"""Input model for research_subgraph.

The subgraph reads ``state["query_analysis"]`` which is the serialised
``QueryNodeOutput``.  ``ResearchSubgraphInput`` is structurally identical
so ``build_input`` can validate directly from the state slice.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["ResearchSubgraphInput"]


class ResearchSubgraphInput(BaseModel):
    """Typed input for the research_subgraph node.

    Shape mirrors ``QueryNodeOutput`` — the previous node's output becomes
    this node's input via ``state["query_analysis"]``.

    Attributes:
        intent: Classified query intent from analyze_query.
        symbols: Equity tickers to fetch stats and news for.
        filters: Optional query filters (date range, interval, etc.).
    """

    intent: str = Field(default="", description="Query intent from query_node.")
    symbols: list[str] = Field(default_factory=list, description="Equity tickers.")
    filters: dict[str, Any] = Field(default_factory=dict, description="Optional filters.")
