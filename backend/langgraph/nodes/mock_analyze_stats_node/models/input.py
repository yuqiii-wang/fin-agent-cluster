"""Input model for analyze_stats_node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["AnalyzeStatsInput"]


class AnalyzeStatsInput(BaseModel):
    """Typed input for ``analyze_stats_node`` and its ``analyze_stats`` task.

    Attributes:
        stats_data: Serialised ``ReadStatsOutput`` dict from research_subgraph.
        query: Original user query for context in analysis.
    """

    stats_data: dict[str, Any] = Field(default_factory=dict)
    query: str = Field(default="", description="Original user query for context.")
