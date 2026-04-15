"""News task output models for market_data_collector.

Each model represents the JSON-structured result of one news sub-task.
All models include a ``to_context_lines()`` method that renders human-readable
lines suitable for injection into the LLM synthesis prompt.

Model hierarchy:
  NewsRawResults   — direct download from a source provider (articles list).
  NewsStatsResults — AI-enriched article matching the news_stats table schema.
  NewsStatsView    — UI display subset (title, source_name, published_at).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ArticleSummary(BaseModel):
    """Lightweight representation of one news article."""

    title: str = Field(..., description="Article headline")
    source_name: str = Field("", description="Publisher / source name")
    published_at: Optional[str] = Field(None, description="ISO date string, e.g. '2026-04-14'")


class NewsRawResults(BaseModel):
    """Direct download of source raw data for one fetch operation.

    Covers both yfinance company-news fetches and named web-search queries.
    Articles are persisted to ``news_raw`` and transformed into
    :class:`NewsStatsResults` via the enrichment pipeline (utils + AI).

    Task: ``company_news`` or ``web_search_<key>`` — parallel.
    """

    ticker: str = Field(..., description="Primary ticker symbol")
    query_key: Optional[str] = Field(None, description="Web-search query key, e.g. 'industry_news'")
    query: Optional[str] = Field(None, description="Full search query string (web searches only)")
    articles: list[ArticleSummary] = Field(default_factory=list, description="Fetched articles")
    summaries: list[str] = Field(default_factory=list, description="AI-generated article summaries")
    source: str = Field("yfinance", description="Data provider used")
    error: Optional[str] = Field(None, description="Error message if fetch failed")

    def to_context_lines(self) -> list[str]:
        """Render raw news articles as context lines for LLM synthesis."""
        if self.error or not self.articles:
            return []
        label = self.query_key or "Recent News"
        lines = [f"\n=== {label} ({len(self.articles)} articles) ==="]
        for a in self.articles[:10]:
            pub = (a.published_at or "")[:10]
            lines.append(f"  [{pub}] {a.title} — {a.source_name}")
        return lines


class NewsStatsResults(BaseModel):
    """AI-enriched news article matching the ``fin_markets.news_stats`` table schema.

    Produced by the enrichment pipeline (utils + AI) from :class:`NewsRawResults`.
    Persisted to ``fin_markets.news_stats``.
    """

    title: str = Field(..., description="Article headline")
    source_name: Optional[str] = Field(None, description="Publisher / media outlet name")
    published_at: Optional[str] = Field(None, description="ISO publication date, e.g. '2026-04-14'")
    symbol: Optional[str] = Field(None, description="Primary ticker; None for topic news")
    source: str = Field(..., description="Data provider: 'yfinance', 'alpha_vantage', 'web_search'")
    url_hash: str = Field(..., description="sha256(url) for deduplication index")
    ai_summary: Optional[str] = Field(None, description="2-3 sentence AI-generated summary")
    sentiment_level: Optional[str] = Field(None, description="9-point sentiment scale")
    sector: Optional[str] = Field(None, description="Primary GICS sector")
    topic_level1: Optional[str] = Field(None, description="Top-level topic domain, e.g. 'Corporate'")
    topic_level2: Optional[str] = Field(None, description="Topic category, e.g. 'Financial Performance'")
    impact_category: Optional[str] = Field(None, description="Level-3 event code, e.g. 'earnings_beat'")
    topics: list[str] = Field(default_factory=list, description="Free-form topic tags")
    region: Optional[str] = Field(None, description="Geographic region, e.g. 'us', 'cn'")

    def to_view(self) -> "NewsStatsView":
        """Extract the UI-facing display subset."""
        return NewsStatsView(
            title=self.title,
            source_name=self.source_name or "",
            published_at=self.published_at,
        )


class NewsStatsView(BaseModel):
    """UI-facing display subset of a :class:`NewsStatsResults` article.

    Used by frontend components to render news feeds.
    """

    title: str = Field(..., description="Article headline")
    source_name: str = Field("", description="Publisher / source name")
    published_at: Optional[str] = Field(None, description="ISO publication date")
