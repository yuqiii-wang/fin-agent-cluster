"""Pydantic models for the news sub-API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NewsArticle(BaseModel):
    """A single news article."""

    id: str = Field(..., description="Unique article identifier.")
    symbol: str = Field(..., description="Related equity symbol, e.g. 'AAPL'.")
    title: str = Field(..., description="Article title.")
    source: str = Field(..., description="Publisher or data provider name.")
    published_at: datetime = Field(..., description="Publication timestamp (UTC).")
    content: str = Field(..., description="Full article body text.")
    url: str | None = Field(default=None, description="Original article URL.")


class NewsListResponse(BaseModel):
    """Paginated list of news articles."""

    items: list[NewsArticle]
    total: int = Field(..., description="Total number of matching articles.")
