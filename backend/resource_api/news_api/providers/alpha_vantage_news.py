"""Alpha Vantage NEWS_SENTIMENT provider."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.news_api.models import NewsArticle, NewsQuery, NewsResult

_BASE_URL = "https://www.alphavantage.co/query"


def _parse_published_at(raw: str | None) -> str | None:
    """Convert AV's 'YYYYMMDDTHHMM' format to ISO-8601, returning None on failure."""
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, "%Y%m%dT%H%M")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return raw


async def fetch(query: NewsQuery, api_key: str) -> NewsResult:
    """Fetch news and sentiment from Alpha Vantage NEWS_SENTIMENT endpoint.

    Supports both ``company_news`` (ticker-based) and ``topic_news`` (keyword query).
    """
    params: dict[str, Any] = {"function": "NEWS_SENTIMENT", "apikey": api_key}
    limit = int(query.params.get("limit", 50))
    params["limit"] = min(limit, 1000)  # AV max is 1000

    if query.method == "company_news" and query.symbol:
        params["tickers"] = query.symbol.upper()
    elif query.method == "topic_news" and query.query:
        params["q"] = query.query
    else:
        raise ValueError("alpha_vantage news provider requires symbol (company_news) or query (topic_news)")

    # Optional time filter
    if "time_from" in query.params:
        params["time_from"] = query.params["time_from"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(_BASE_URL, params=params)
    if resp.status_code == 404:
        raise ProviderNotFoundError(
            "alpha_vantage", "NEWS_SENTIMENT",
            query.symbol or query.query or "",
            "HTTP 404 Not Found",
        )
    resp.raise_for_status()
    data = resp.json()
    if "Error Message" in data:
        raise ProviderNotFoundError(
            "alpha_vantage", "NEWS_SENTIMENT",
            query.symbol or query.query or "",
            data["Error Message"],
        )

    feed: list[dict[str, Any]] = data.get("feed", [])
    articles = []
    for item in feed:
        # sentiment_score from AV is in [-1, 1] scale via their label
        overall_score = item.get("overall_sentiment_score")
        sentiment = float(overall_score) if overall_score is not None else None
        tickers = [t.get("ticker", "") for t in item.get("ticker_sentiment", [])]
        articles.append(
            NewsArticle(
                title=item.get("title", ""),
                url=item.get("url"),
                source_name=item.get("source", "alpha_vantage"),
                published_at=_parse_published_at(item.get("time_published")),
                summary=item.get("summary"),
                sentiment_score=sentiment,
                tickers=tickers,
            )
        )

    return NewsResult(
        method=query.method,
        source="alpha_vantage",
        symbol=query.symbol,
        query=query.query,
        articles=articles,
        fetched_at=datetime.now(timezone.utc),
    )
