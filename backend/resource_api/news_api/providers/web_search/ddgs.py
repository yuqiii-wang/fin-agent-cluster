"""DuckDuckGo web-search news backend."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from ddgs import DDGS

from backend.resource_api.news_api.models import NewsArticle, NewsQuery, NewsResult

logger = logging.getLogger(__name__)


def _search_news(search_query: str, limit: int) -> list[dict[str, Any]]:
    """Run DuckDuckGo news search synchronously (offloaded via asyncio.to_thread).

    Args:
        search_query: Free-text query string.
        limit:        Maximum number of results to return.

    Returns:
        List of raw DDGS result dicts.
    """
    with DDGS() as ddgs:
        return list(ddgs.news(search_query, max_results=limit))


async def fetch(query: NewsQuery) -> NewsResult:
    """Fetch news via DuckDuckGo.

    Supports both ``company_news`` (ticker → "<SYMBOL> stock news") and
    ``topic_news`` (free-text query).

    Args:
        query: Structured news query.

    Returns:
        Normalised :class:`~app.resource_api.news_api.models.NewsResult`.

    Raises:
        ValueError: If neither a symbol nor a query string is provided.
    """
    limit = int(query.params.get("limit", 20))

    if query.method == "company_news" and query.symbol:
        search_query = f"{query.symbol.upper()} stock news"
    elif query.method == "topic_news" and query.query:
        search_query = query.query
    else:
        raise ValueError("ddgs provider requires symbol (company_news) or query (topic_news)")

    raw_results = await asyncio.to_thread(_search_news, search_query, limit)
    logger.debug("[ddgs] query=%r returned %d articles", search_query, len(raw_results))

    articles = []
    for item in raw_results:
        published_at = item.get("date")
        if published_at:
            try:
                dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                published_at = dt.isoformat()
            except ValueError:
                pass

        articles.append(
            NewsArticle(
                title=item.get("title", ""),
                url=item.get("url"),
                source_name=item.get("source", "duckduckgo"),
                published_at=published_at,
                summary=item.get("body"),
            )
        )

    return NewsResult(
        method=query.method,
        source="web_search",
        symbol=query.symbol,
        query=query.query,
        articles=articles,
        fetched_at=datetime.now(timezone.utc),
    )
