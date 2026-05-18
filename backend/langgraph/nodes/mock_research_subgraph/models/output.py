"""Output model for research_subgraph.

Written to three state keys after the subgraph completes:
  - state["stats_data"]       — ReadStatsOutput serialised
  - state["news_data"]        — ReadNewsOutput serialised
  - state["merged_research"]  — MergeOutput serialised
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["ResearchSubgraphOutput"]


class ResearchSubgraphOutput(BaseModel):
    """Typed output for the research_subgraph node.

    Bundles the results of all three child nodes for ``get_state_updates``
    to fan out into separate ``GraphState`` slices.

    Attributes:
        stats_data: Serialised ``ReadStatsOutput`` dict.
        news_data: Serialised ``ReadNewsOutput`` dict.
        merged_research: Serialised ``MergeOutput`` dict.
    """

    stats_data: dict[str, Any] = Field(default_factory=dict)
    news_data: dict[str, Any] = Field(default_factory=dict)
    merged_research: dict[str, Any] = Field(default_factory=dict)
