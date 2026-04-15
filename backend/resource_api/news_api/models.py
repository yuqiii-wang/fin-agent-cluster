"""Pydantic models for the unified news API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

NewsMethod = Literal["company_news", "topic_news"]
NewsSource = Literal["yfinance", "alpha_vantage", "web_search"]


class NewsQuery(BaseModel):
    """Input specification for a news fetch."""

    method: NewsMethod = Field(..., description="'company_news' or 'topic_news'")
    symbol: Optional[str] = Field(None, description="Ticker symbol for company_news, e.g. 'AAPL'")
    query: Optional[str] = Field(None, description="Free-text query for topic_news")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra provider params, e.g. {limit: 20, time_from: 'YYYYMMDDTHHMM'}",
    )
    thread_id: Optional[str] = Field(None, description="LangGraph thread id for traceability")
    node_name: str = Field("unknown", description="Graph node that issued this query")


class NewsArticle(BaseModel):
    """Single news article normalised across all providers."""

    title: str
    url: Optional[str] = None
    source_name: str = Field(..., description="Publisher / media outlet name")
    published_at: Optional[str] = Field(None, description="ISO-8601 datetime when published")
    summary: Optional[str] = None
    sentiment_score: Optional[float] = Field(
        None, description="Normalised sentiment in [-1, 1]; None if unavailable"
    )
    tickers: list[str] = Field(default_factory=list)


class NewsResult(BaseModel):
    """Unified output from any news provider."""

    method: NewsMethod
    source: NewsSource
    symbol: Optional[str] = None
    query: Optional[str] = None
    articles: list[NewsArticle] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    not_found_attempts: list[str] = Field(
        default_factory=list,
        description="Non-empty when all providers returned not-found; each entry describes an attempted provider.",
    )
