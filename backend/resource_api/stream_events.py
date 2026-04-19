"""Resource API stream event publishers for Redis Streams.

Provides fire-and-forget coroutines that publish market data and news
enrichment events after successful live fetches.  These run as background
coroutines (``asyncio.ensure_future``) so they never block the main fetch
path.

Usage
-----
From ``resource_api.quant_api.client``::

    import asyncio
    from backend.resource_api.stream_events import publish_market_tick

    asyncio.ensure_future(publish_market_tick(query, result, source))

From ``resource_api.news_api.client``::

    import asyncio
    from backend.resource_api.stream_events import publish_news_enrichment

    asyncio.ensure_future(publish_news_enrichment(query, result, source))
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from backend.streaming.schemas import MarketTickMessage, NewsEnrichmentMessage
from backend.streaming.streams import STREAM_MARKET_TICKS, STREAM_NEWS_ENRICHED, xadd

if TYPE_CHECKING:
    from backend.resource_api.news_api.models import NewsQuery, NewsResult
    from backend.resource_api.quant_api.models import QuantQuery, QuantResult

logger = logging.getLogger(__name__)


async def publish_market_tick(
    query: "QuantQuery",
    result: "QuantResult",
    source: str,
) -> None:
    """Publish a market data fetch result to ``fin:market:ticks``.

    Best-effort — never raises.  Call via ``asyncio.ensure_future`` to avoid
    blocking the fetch caller.

    Args:
        query:  The :class:`~backend.resource_api.quant_api.models.QuantQuery`
                that produced the result.
        result: The :class:`~backend.resource_api.quant_api.models.QuantResult`
                returned by the provider.
        source: Resolved provider name (e.g. ``'yfinance'``).
    """
    try:
        bars_raw: list[dict] = []
        if result.bars:
            bars_raw = [b.model_dump() if hasattr(b, "model_dump") else dict(b) for b in result.bars]
        elif result.quote:
            bars_raw = [result.quote.model_dump() if hasattr(result.quote, "model_dump") else dict(result.quote)]

        msg = MarketTickMessage(
            symbol=query.symbol.upper(),
            source=source,
            method=query.method,
            thread_id=query.thread_id or "",
            node_name=query.node_name or "",
            bar_count=len(bars_raw),
            bars=json.dumps(bars_raw, default=str),
        )
        await xadd(STREAM_MARKET_TICKS, msg.model_dump())
    except Exception as exc:
        logger.debug("[resource_api.stream_events] publish_market_tick failed: %s", exc)


async def publish_news_enrichment(
    query: "NewsQuery",
    result: "NewsResult",
    source: str,
) -> None:
    """Publish a news fetch result to ``fin:news:enriched``.

    Best-effort — never raises.  Call via ``asyncio.ensure_future`` to avoid
    blocking the fetch caller.

    Args:
        query:  The :class:`~backend.resource_api.news_api.models.NewsQuery`
                that produced the result.
        result: The :class:`~backend.resource_api.news_api.models.NewsResult`
                returned by the provider.
        source: Resolved provider name (e.g. ``'yfinance'``).
    """
    try:
        articles_raw: list[dict] = []
        if result.articles:
            articles_raw = [
                a.model_dump() if hasattr(a, "model_dump") else dict(a)
                for a in result.articles
            ]

        msg = NewsEnrichmentMessage(
            thread_id=query.thread_id or "",
            symbol=query.symbol or "",
            query=query.query or "",
            source=source,
            article_count=len(articles_raw),
            articles=json.dumps(articles_raw, default=str),
        )
        await xadd(STREAM_NEWS_ENRICHED, msg.model_dump())
    except Exception as exc:
        logger.debug("[resource_api.stream_events] publish_news_enrichment failed: %s", exc)
