"""Output model for regional_analyze_nodes.

Written to ``state["regional_context"]`` (and ``state["region"]``) after the
selected regional node completes.  The research_subgraph may read this slice
for region-aware market context.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["RegionalAnalyzeOutput"]


class RegionalAnalyzeOutput(BaseModel):
    """Typed output for any regional analyze node.

    Attributes:
        region: Region identifier (``"apac"``, ``"emea"``, ``"amer"``).
        active_exchanges: Primary exchanges active during this region's session.
        session_note: Human-readable note describing the current trading session.
        intent: Query intent forwarded for downstream use.
        symbols: Equity tickers forwarded for downstream use.
    """

    region: str = Field(description="Region identifier.")
    active_exchanges: list[str] = Field(description="Primary exchanges active in this session.")
    session_note: str = Field(description="Description of the current trading session.")
    intent: str = Field(default="", description="Query intent from query_node.")
    symbols: list[str] = Field(default_factory=list, description="Equity tickers.")
