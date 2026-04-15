"""Bing News Search API v7 backend (Azure Cognitive Services)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from backend.config import get_settings
from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.news_api.models import NewsArticle, NewsQuery, NewsResult

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    """Return True when a Bing API key is present in settings."""
    return bool(get_settings().BING_SEARCH_API_KEY)


async def fetch(query: NewsQuery) -> NewsResult:
    """Fetch news via Bing News Search API v7.

    Docs: https://learn.microsoft.com/en-us/bing/search-apis/bing-news-search/reference/endpoints

    Args:
        query: Structured news query (symbol for company_news, query for topic_news).

    Returns:
        Normalised :class:`~app.resource_api.news_api.models.NewsResult`.

    Raises:
        ValueError: When ``BING_SEARCH_API_KEY`` is not configured.
        httpx.HTTPStatusError: On non-2xx Bing API responses.
    """
    s = get_settings()
    if not s.BING_SEARCH_API_KEY:
        raise ValueError("BING_SEARCH_API_KEY is not configured")

    limit = min(int(query.params.get("limit", 20)), 100)

    if query.method == "company_news" and query.symbol:
        q_text = f"{query.symbol.upper()} stock news"
    elif query.method == "topic_news" and query.query:
        q_text = query.query
    else:
        raise ValueError("bing provider requires symbol (company_news) or query (topic_news)")

    params = {
        "q": q_text,
        "count": str(limit),
        "mkt": "en-US",
        "textFormat": "Raw",
    }
    headers = {"Ocp-Apim-Subscription-Key": s.BING_SEARCH_API_KEY}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(s.BING_SEARCH_ENDPOINT, params=params, headers=headers)
    if resp.status_code == 404:
        raise ProviderNotFoundError("bing", "Bing News Search API v7", q_text, "HTTP 404 Not Found")
    resp.raise_for_status()
    data = resp.json()

    raw_articles = data.get("value", [])
    logger.debug("[bing] query=%r returned %d articles", q_text, len(raw_articles))

    articles = []
    for item in raw_articles:
        published_at: str | None = item.get("datePublished")
        if published_at:
            try:
                dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                published_at = dt.isoformat()
            except ValueError:
                pass

        url = item.get("url") or (item.get("webSearchUrl"))
        source_name = (item.get("provider") or [{}])[0].get("name", "bing")

        articles.append(
            NewsArticle(
                title=item.get("name", ""),
                url=url,
                source_name=source_name,
                published_at=published_at,
                summary=item.get("description"),
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
