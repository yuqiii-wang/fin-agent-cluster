"""Output model for analyze_news_node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["AnalyzeNewsOutput"]


class AnalyzeNewsOutput(BaseModel):
    """Typed output for ``analyze_news_node``.

    Attributes:
        symbol: The primary ticker whose news was analysed.
        news_sentiment: Human-readable sentiment narrative.
        sentiment_score: Aggregate sentiment score in [-1.0, 1.0].
        highlights: List of notable headline strings from the article set.
    """

    symbol: str = Field(default="")
    news_sentiment: str = Field(default="", description="Narrative sentiment analysis.")
    sentiment_score: float = Field(default=0.0, description="Aggregate sentiment [-1.0, 1.0].")
    highlights: list[str] = Field(default_factory=list)
