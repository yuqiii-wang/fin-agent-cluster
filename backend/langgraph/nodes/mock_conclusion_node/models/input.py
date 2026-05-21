"""Input model for conclusion_node.

Reads from three predecessor node outputs:
  - analyze_stats_node output — stats analysis narrative and key metrics
  - analyze_news_node output  — news sentiment narrative and highlights
  - state["query"]            — original user query for LLM context
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["ConclusionNodeInput"]


class ConclusionNodeInput(BaseModel):
    """Typed input for ``conclusion_node`` and its ``stream_llm`` task.

    Attributes:
        stats_analysis: Narrative from analyze_stats_node (return, volatility, trend).
        stats_key_metrics: Key OHLCV metrics dict from analyze_stats_node.
        news_sentiment: Narrative from analyze_news_node (sentiment score, label).
        news_highlights: Top headline strings from analyze_news_node.
        query: Original user query string for LLM prompt context.
    """

    stats_analysis: str = Field(default="", description="Statistical analysis narrative.")
    stats_key_metrics: dict[str, Any] = Field(default_factory=dict)
    news_sentiment: str = Field(default="", description="News sentiment narrative.")
    news_highlights: list[str] = Field(default_factory=list)
    query: str = Field(default="", description="Original user query for LLM context.")
