"""Input model for prepare_macro_news node."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = ["PrepareMacroNewsInput"]


class PrepareMacroNewsInput(BaseModel):
    """Typed input for ``prepare_macro_news``.

    Attributes:
        symbol:     Not used for symbol-specific lookup; kept as optional context
                    so downstream consumers can correlate with an equity query.
        topics:     Topic keywords to narrow / augment the macro news search.
        from_dt:    Start of the news date window (UTC).
        to_dt:      End of the news date window (UTC).
        news_limit: Max news articles passed to ``get_news``.
    """

    symbol: str | None = Field(
        default=None,
        description="Optional equity ticker for contextual correlation.",
    )
    topics: list[str] = Field(
        default_factory=list,
        description="Topic keywords to filter/augment macro news search.",
    )
    from_dt: datetime | None = Field(default=None, description="Start of date window (UTC).")
    to_dt: datetime | None = Field(default=None, description="End of date window (UTC).")
    news_limit: int = Field(default=20, ge=1, le=100, description="Max news articles to fetch.")
