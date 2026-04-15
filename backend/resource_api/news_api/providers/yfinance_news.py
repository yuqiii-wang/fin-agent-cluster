"""yfinance news provider."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import yfinance as yf

from backend.resource_api.news_api.models import NewsArticle, NewsQuery, NewsResult


def _fetch_company_news(symbol: str, limit: int) -> NewsResult:
    """Fetch company news for a ticker from yfinance (blocking, runs in thread).

    Supports both yfinance 0.2.x (flat dict) and 0.3.x (nested ``content`` dict)
    response formats.
    """
    ticker = yf.Ticker(symbol)
    raw: list[dict[str, Any]] = ticker.news or []
    articles = []
    for item in raw[:limit]:
        # yfinance 0.3.x: news items are {"id": "...", "content": {...}}
        content: dict[str, Any] = item.get("content") or item

        title = content.get("title", "")
        if not title:
            continue  # skip items with no title

        # URL: try clickThroughUrl → canonicalUrl → legacy "link"
        click_through = content.get("clickThroughUrl") or {}
        canonical = content.get("canonicalUrl") or {}
        url = (
            click_through.get("url")
            or canonical.get("url")
            or item.get("link")
        )

        # Publisher: nested provider object (0.3.x) or flat publisher string (0.2.x)
        provider = content.get("provider") or {}
        source_name = (
            provider.get("displayName")
            or item.get("publisher")
            or "yfinance"
        )

        # Published date: ISO string (0.3.x pubDate) or Unix timestamp (0.2.x)
        pub_date_str = content.get("pubDate")
        if pub_date_str:
            published_at = pub_date_str  # already ISO-8601
        else:
            pub_ts = item.get("providerPublishTime")
            published_at = (
                datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat()
                if pub_ts
                else None
            )

        # Summary: present in 0.3.x content
        summary = content.get("summary") or content.get("description") or None
        if summary == "":
            summary = None

        articles.append(
            NewsArticle(
                title=title,
                url=url,
                source_name=source_name,
                published_at=published_at,
                summary=summary,
                tickers=item.get("relatedTickers", []),
            )
        )
    return NewsResult(
        method="company_news",
        source="yfinance",
        symbol=symbol.upper(),
        articles=articles,
        fetched_at=datetime.now(timezone.utc),
    )


async def fetch(query: NewsQuery) -> NewsResult:
    """Async entry-point for yfinance news provider.

    Only ``company_news`` is supported; ``topic_news`` is not available via yfinance.
    """
    if query.method != "company_news" or not query.symbol:
        raise ValueError("yfinance news provider only supports company_news with a symbol")
    limit = int(query.params.get("limit", 20))
    return await asyncio.to_thread(_fetch_company_news, query.symbol.upper(), limit)
