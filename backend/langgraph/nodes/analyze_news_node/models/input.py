"""Input model for analyze_news_node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["AnalyzeNewsInput"]


class AnalyzeNewsInput(BaseModel):
    """Typed input for ``analyze_news_node`` and its ``analyze_news`` task.

    Attributes:
        news_data: Serialised ``ReadNewsOutput`` dict from research_subgraph.
        query: Original user query for context in sentiment analysis.
    """

    news_data: dict[str, Any] = Field(default_factory=dict)
    query: str = Field(default="", description="Original user query for context.")
