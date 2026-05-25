"""Pydantic models for the news sub-API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NewsArticle(BaseModel):
    """A single news article."""

    id: str = Field(..., description="Unique article identifier.")
    symbol: str | None = Field(default=None, description="Related equity symbol, e.g. 'AAPL'. None for topic news.")
    title: str = Field(..., description="Article title.")
    source: str = Field(..., description="Provider label, e.g. 'ddgs'.")
    source_name: str | None = Field(default=None, description="Publisher or media outlet name, e.g. 'Reuters'.")
    published_at: datetime | None = Field(default=None, description="Publication timestamp (UTC). None for web-search results.")
    content: str = Field(..., description="Full article body text.")
    url: str | None = Field(default=None, description="Original article URL.")


class NewsListResponse(BaseModel):
    """Paginated list of news articles."""

    items: list[NewsArticle]
    total: int = Field(..., description="Total number of matching articles.")


class InfoResult(BaseModel):
    """A single web search result from DDGS text search."""

    url: str = Field(default="", description="Landing page URL.")
    title: str = Field(default="", description="Page or article title.")
    content: str = Field(default="", description="Plain-text body.")
