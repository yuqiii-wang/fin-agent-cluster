"""Completion handlers for research_subgraph tasks."""

from __future__ import annotations

import logging

from backend.langgraph.models import (
    MergeResultsInput,
    MergeResultsOutput,
    ReadNewsInput,
    ReadNewsOutput,
    ReadStatsInput,
    ReadStatsOutput,
)

logger = logging.getLogger(__name__)


async def handle_read_stats(payload: dict) -> dict:
    """Fetch market statistics for the first symbol in *payload*."""
    from backend.resources.stats.client import StatsClient

    inp = ReadStatsInput.model_validate(payload)
    symbol = (inp.symbols or ["AAPL"])[0]
    client = StatsClient()
    try:
        response = await client.list_stats(symbol, inp.interval)
        records = [r.model_dump(mode="json") for r in response.items]
    finally:
        await client.aclose()
    output = ReadStatsOutput(symbol=symbol, interval=inp.interval, records=records)
    return output.model_dump()


async def handle_read_news(payload: dict) -> dict:
    """Fetch recent news articles for the first symbol in *payload*."""
    from backend.resources.news.client import NewsClient

    inp = ReadNewsInput.model_validate(payload)
    symbol = (inp.symbols or ["AAPL"])[0]
    client = NewsClient()
    try:
        response = await client.list_news(symbol=symbol, limit=5)
        articles = [a.model_dump(mode="json") for a in response.items]
    finally:
        await client.aclose()
    output = ReadNewsOutput(symbol=symbol, articles=articles)
    return output.model_dump()


async def handle_merge_results(payload: dict) -> dict:
    """Combine stats and news data into a research summary."""
    inp = MergeResultsInput.model_validate(payload)
    stats = inp.stats_data
    news = inp.news_data
    symbol = stats.get("symbol") or news.get("symbol") or "?"
    n_records = len(stats.get("records", []))
    n_articles = len(news.get("articles", []))
    summary = (
        f"Research summary for {symbol}: "
        f"{n_records} price records and {n_articles} news articles retrieved."
    )
    output = MergeResultsOutput(
        symbol=symbol,
        summary=summary,
        stats=stats,
        news=news,
    )
    return output.model_dump()

