"""Input model for prepare_industry_news node."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = ["PrepareIndustryNewsInput"]


class PrepareIndustryNewsInput(BaseModel):
    """Typed input for ``prepare_industry_news``.

    Attributes:
        symbol:     Equity ticker resolved by ``query_node``, e.g. ``'AAPL'``.
                    Used as context to anchor industry/sector relevance.
        topics:     Topic keywords to narrow / augment the industry news search.
        from_dt:    Start of the news date window (UTC).
        to_dt:      End of the news date window (UTC).
        news_limit: Max news articles passed to ``get_news``.
    """

    symbol: str | None = Field(default=None, description="Equity ticker, e.g. 'AAPL'.")
    topics: list[str] = Field(
        default_factory=list,
        description="Topic keywords to filter/augment industry news search.",
    )
    from_dt: datetime | None = Field(default=None, description="Start of date window (UTC).")
    to_dt: datetime | None = Field(default=None, description="End of date window (UTC).")
    news_limit: int = Field(default=20, ge=1, le=100, description="Max news articles to fetch.")
