"""Input model for regional_analyze_nodes.

The three regional nodes (apac, emea, amer) share an identical input shape
read from ``state["query_analysis"]``.  The ``region`` field is injected by
each node's ``build_input`` so downstream handlers know which region is active.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["RegionalAnalyzeInput"]


class RegionalAnalyzeInput(BaseModel):
    """Typed input for any regional analyze node.

    Attributes:
        intent: Query intent forwarded from query_node.
        symbols: Equity tickers forwarded from query_node.
        filters: Optional query filters forwarded from query_node.
        query_time: UTC ISO 8601 timestamp of query receipt (defaults to empty string).
        region: Region identifier injected by the node (``"apac"``, ``"emea"``, ``"amer"``).
    """

    intent: str = Field(default="", description="Query intent from query_node.")
    symbols: list[str] = Field(default_factory=list, description="Equity tickers.")
    filters: dict[str, Any] = Field(default_factory=dict, description="Optional filters.")
    query_time: str = Field(default="", description="UTC ISO 8601 timestamp of query receipt.")
    region: str = Field(description="Region identifier: 'apac', 'emea', or 'amer'.")
