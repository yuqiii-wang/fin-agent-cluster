"""Completion handlers for research_subgraph tasks."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def handle_read_stats(payload: dict[str, Any]) -> dict[str, Any]:
    """Fetch market statistics for the first symbol in *payload*."""
    from backend.resources.stats.client import StatsClient

    symbol: str = (payload.get("symbols") or ["AAPL"])[0]
    interval: str = payload.get("interval", "1d")
    logger.info("[read_stats] symbol=%s interval=%s", symbol, interval)
    client = StatsClient()
    try:
        response = await client.list_stats(symbol, interval)
        records = [r.model_dump(mode="json") for r in response.items]
    finally:
        await client.aclose()
    return {"symbol": symbol, "interval": interval, "records": records}


async def handle_read_news(payload: dict[str, Any]) -> dict[str, Any]:
    """Fetch recent news articles for the first symbol in *payload*."""
    from backend.resources.news.client import NewsClient

    symbol: str = (payload.get("symbols") or ["AAPL"])[0]
    logger.info("[read_news] symbol=%s", symbol)
    client = NewsClient()
    try:
        response = await client.list_news(symbol=symbol, limit=5)
        articles = [a.model_dump(mode="json") for a in response.items]
    finally:
        await client.aclose()
    return {"symbol": symbol, "articles": articles}


async def handle_merge_results(payload: dict[str, Any]) -> dict[str, Any]:
    """Combine stats and news data into a research summary."""
    stats = payload.get("stats_data", {})
    news = payload.get("news_data", {})
    symbol = stats.get("symbol") or news.get("symbol") or "?"
    n_records = len(stats.get("records", []))
    n_articles = len(news.get("articles", []))
    summary = (
        f"Research summary for {symbol}: "
        f"{n_records} price records and {n_articles} news articles retrieved."
    )
    logger.info("[merge_results] %s", summary)
    return {"symbol": symbol, "summary": summary, "stats": stats, "news": news}
